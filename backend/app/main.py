from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Literal

from . import criteria_builder, cross_compare, diff, grill, llm, repair_suggest, rubric_store, storage
from .claim_inspector import inspect_statements
from .consistency import find_numeric_findings
from .contracts import (
    AgentProposal,
    AgentProposalCreate,
    ApiError,
    ConsistencyFinding,
    CriterionEvidenceLink,
    CriterionEvidenceLinkCreate,
    CrossCompareRequest,
    CrossCompareResponse,
    DetectedStatement,
    EditableSource,
    EvidenceAnnotation,
    EvidenceAnnotationCreate,
    MarkdownPreview,
    MaterialPreflightReport,
    MaterialPreflightSummary,
    MaterialRevisionCreate,
    MaterialRevisionCreated,
    MaterialSummary,
    ProposalAcceptance,
    ProposalCandidate,
    ProposalCandidateReject,
    RepairSuggestion,
    Review,
    ReviewCreate,
    ReviewDetail,
    ReviewMaterialEntry,
    ReviewMaterialUpsert,
    ReviewUpdate,
    RevisionContext,
    Rubric,
    RubricBinding,
    RubricBindingCreate,
    RubricDraft,
    RubricDraftRequest,
    RubricPublish,
    RunReport,
    SavedMaterial,
)
from .evidence import QuoteNotFound
from .markdown_preview import MAX_BYTES, PreviewRejected, build_preview
from .mock_report import MOCK_REPORT
from .preflight_report import assemble_report, assemble_summaries
from .storage import CandidateInput, InvalidCandidate, ParentNotInReview, RubricNotBound, SpanMismatch, StorageConflict


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保 SQLite 表和 data 目录存在；不做迁移。
    storage.init_db()
    # backend/.env（如存在）加载到环境；不覆盖既有环境变量。
    llm.load_env_file()
    # 评分标准文件仓：非法/重复文件直接拒绝启动，不降级为空列表。
    rubric_store.set_index(rubric_store.load_index())
    yield


app = FastAPI(title="Preflight", version="0.1.0", lifespan=lifespan)


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    contract_version: Literal["0.1.0"] = "0.1.0"


class LookupFailed(Exception):
    """读取不到材料；由处理器转成 404 + ApiError。"""

    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


@app.get("/api/v1/health", response_model=Health)
def health() -> Health:
    return Health()


# 只读 mock：数据在 import 时已通过 RunReport 校验；当前不接解析、LLM 或数据库。
@app.get("/api/v1/report", response_model=RunReport)
def report() -> RunReport:
    return MOCK_REPORT


# 临时预览：只在内存中处理一次请求，不保存文件；用后关闭上传缓冲。
@app.post("/api/v1/preview/markdown", response_model=MarkdownPreview)
async def preview_markdown(file: UploadFile = File(...)) -> MarkdownPreview:
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    return build_preview(file.filename or "", data)


# 保存材料：服务端重新校验并重新解析上传文件（不信任浏览器回传的 blocks），原子写入 SQLite。
@app.post("/api/v1/materials", response_model=SavedMaterial, status_code=201)
async def save_material(file: UploadFile = File(...)) -> SavedMaterial:
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    preview = build_preview(file.filename or "", data)
    return storage.save_material(preview)


# 注意：/recent 必须先于 /{material_id} 注册，否则会被当作 ID。
@app.get("/api/v1/materials", response_model=list[MaterialSummary])
def saved_materials() -> list[MaterialSummary]:
    # 列表摘要：不返回 blocks，避免列表接口携带全量内容。
    return storage.list_materials()


@app.get("/api/v1/materials/recent", response_model=SavedMaterial)
def recent_material() -> SavedMaterial:
    material = storage.get_recent_material()
    if material is None:
        raise LookupFailed("no_saved_material", "还没有保存过任何材料", ["先上传并保存一份 .md"])
    return material


@app.get("/api/v1/materials/{material_id}", response_model=SavedMaterial)
def material_by_id(material_id: str) -> SavedMaterial:
    material = storage.get_material(material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return material


# 删除材料：本体与全部从属行（blocks/证据/关联/提案）一次事务移除，不可恢复。
@app.delete("/api/v1/materials/{material_id}", status_code=204)
def remove_material(material_id: str) -> Response:
    if not storage.delete_material(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return Response(status_code=204)


# —— Material Revision v1：只支持 .md；旧材料不可变，child 是全新 Material ——


@app.post("/api/v1/materials/{parent_id}/revisions", response_model=MaterialRevisionCreated, status_code=201)
def create_material_revision(parent_id: str, payload: MaterialRevisionCreate) -> MaterialRevisionCreated:
    if not storage.material_exists(parent_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={parent_id}"])
    try:
        data = payload.text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PreviewRejected("invalid_encoding", "text 不是有效 UTF-8", [str(exc)]) from exc
    preview = build_preview(payload.filename, data)

    binding: tuple[str, int] | None = None
    if payload.review_id is not None:
        review = storage.get_review_detail(payload.review_id)
        if review is None:
            raise LookupFailed("review_not_found", "找不到该 Review", [f"id={payload.review_id}"])
        if all(entry.material_id != parent_id for entry in review.materials):
            raise ParentNotInReview(
                "父材料不在该 Review 中",
                [f"review_id={payload.review_id}", f"material_id={parent_id}"],
            )
        binding = (review.rubric_id, review.rubric_revision)
    else:
        parent_binding = storage.get_binding(parent_id)
        if parent_binding is not None:
            binding = (parent_binding.rubric_id, parent_binding.rubric_revision)
    if binding is not None and rubric_store.get_rubric(binding[0], binding[1]) is None:
        raise LookupFailed("rubric_not_found", "找不到该评分标准版本", [f"{binding[0]} rev{binding[1]}"])

    result = storage.create_material_revision(
        parent_id,
        preview,
        review_id=payload.review_id,
        label=payload.label,
        inherit_binding=binding if payload.review_id is None else None,
    )
    if result is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={parent_id}"])
    material, revision = result
    return MaterialRevisionCreated(material=material, revision=revision)


@app.get("/api/v1/materials/{material_id}/revision-context", response_model=RevisionContext)
def material_revision_context(material_id: str) -> RevisionContext:
    context = storage.get_revision_context(material_id)
    if context is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return context


@app.get("/api/v1/materials/{material_id}/editable-source", response_model=EditableSource)
def material_editable_source(material_id: str) -> EditableSource:
    source = storage.get_editable_source(material_id)
    if source is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return source


# 只读预审装配：从现有绑定与已确认关联计算，不写库、不做满足判定。
@app.get("/api/v1/preflight-summaries", response_model=list[MaterialPreflightSummary])
def preflight_summaries() -> list[MaterialPreflightSummary]:
    return assemble_summaries()


@app.get("/api/v1/materials/{material_id}/preflight-report", response_model=MaterialPreflightReport)
def material_preflight_report(material_id: str) -> MaterialPreflightReport:
    if not storage.material_exists(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    report = assemble_report(material_id)
    if report is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return report


# I7 关键陈述扫描：确定性纯函数现算，不写库、不调 LLM。
@app.get("/api/v1/materials/{material_id}/statement-signals", response_model=list[DetectedStatement])
def material_statement_signals(material_id: str) -> list[DetectedStatement]:
    material = storage.get_material(material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return inspect_statements(material.blocks)


# I8 同材料数值一致性：从关键陈述现算「待核对问题」，不写库、不调 LLM。
@app.get("/api/v1/materials/{material_id}/consistency-findings", response_model=list[ConsistencyFinding])
def material_consistency_findings(material_id: str) -> list[ConsistencyFinding]:
    material = storage.get_material(material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return find_numeric_findings(inspect_statements(material.blocks), material.blocks)


# 两材料数值对照：只比较用户显式选中的两个 id；同 id 请求级拒绝（400），缺一 404。
@app.post("/api/v1/comparisons", response_model=CrossCompareResponse)
def create_comparison(payload: CrossCompareRequest) -> CrossCompareResponse:
    if payload.material_id_a == payload.material_id_b:
        raise cross_compare.SameMaterialCompare(payload.material_id_a)
    material_a = storage.get_material(payload.material_id_a)
    if material_a is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={payload.material_id_a}"])
    material_b = storage.get_material(payload.material_id_b)
    if material_b is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={payload.material_id_b}"])
    return cross_compare.compare_materials(material_a, material_b)


# 修改前后 Finding 集合差：人显式选两份材料；同 id 400，缺一 404。不落库。
@app.post("/api/v1/diffs", response_model=diff.FindingSetDiffResponse)
def create_diff(payload: diff.FindingSetDiffRequest) -> diff.FindingSetDiffResponse:
    if payload.material_id_before == payload.material_id_after:
        raise diff.SameMaterialDiff(payload.material_id_before)
    before = storage.get_material(payload.material_id_before)
    if before is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={payload.material_id_before}"])
    after = storage.get_material(payload.material_id_after)
    if after is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={payload.material_id_after}"])
    return diff.diff_findings(before, after)


# 答辩追问：当前材料的 findings + 陈述 → LLM；引用复验不过则丢弃。不落库。
@app.post("/api/v1/grill", response_model=list[grill.GrillQuestion])
def create_grill(payload: grill.GrillRequest) -> list[grill.GrillQuestion]:
    material = storage.get_material(payload.material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={payload.material_id}"])
    return grill.generate_grill(material)


# 修复建议：一条「待核对问题」交给 LLM 给改稿方向；不落库、不改材料。
# 引用先在 repair_suggest 内逐条复验（quote == text[start:end]），对不上不调用 LLM。
@app.post("/api/v1/materials/{material_id}/repair-suggestions", response_model=RepairSuggestion)
def create_repair_suggestion(material_id: str, payload: ConsistencyFinding) -> RepairSuggestion:
    material = storage.get_material(material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return repair_suggest.suggest_repair(payload, material.blocks)


# 证据标注：quote 服务端校验必须来自 Block 原文；material_id/proposed_by 由服务端设定。
@app.post("/api/v1/evidence-annotations", response_model=EvidenceAnnotation, status_code=201)
def create_evidence_annotation(payload: EvidenceAnnotationCreate) -> EvidenceAnnotation:
    annotation = storage.save_evidence_annotation(payload.block_id, payload.quote, payload.note, "human")
    if annotation is None:
        raise LookupFailed("block_not_found", "找不到该 Block", [f"block_id={payload.block_id}"])
    return annotation


@app.get("/api/v1/materials/{material_id}/evidence-annotations", response_model=list[EvidenceAnnotation])
def material_evidence_annotations(material_id: str) -> list[EvidenceAnnotation]:
    if not storage.material_exists(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return storage.list_evidence_annotations(material_id)


@app.get("/api/v1/evidence-annotations/{annotation_id}", response_model=EvidenceAnnotation)
def evidence_annotation_by_id(annotation_id: str) -> EvidenceAnnotation:
    annotation = storage.get_evidence_annotation(annotation_id)
    if annotation is None:
        raise LookupFailed("annotation_not_found", "找不到该证据标注", [f"id={annotation_id}"])
    return annotation


@app.delete("/api/v1/materials/{material_id}/evidence-annotations/{annotation_id}", status_code=204)
def remove_evidence_annotation(material_id: str, annotation_id: str) -> Response:
    # WHERE 同时限定 material，防跨材料探测；关联由 FK CASCADE 清理。
    if not storage.delete_evidence_annotation(material_id, annotation_id):
        raise LookupFailed("annotation_not_found", "找不到该证据标注", [f"id={annotation_id}"])
    return Response(status_code=204)


# —— 只读评分标准 + 材料绑定 + 人工关联（adjudication 层） ——


@app.get("/api/v1/rubrics", response_model=list[Rubric])
def available_rubrics() -> list[Rubric]:
    return rubric_store.list_rubrics()


@app.post("/api/v1/rubrics/draft", response_model=RubricDraft)
def draft_rubric(payload: RubricDraftRequest) -> RubricDraft:
    return criteria_builder.draft_requirements(payload)


@app.post("/api/v1/rubrics", response_model=Rubric, status_code=201)
def publish_rubric(payload: RubricPublish) -> Rubric:
    # 已确认的草稿在这里成为不可变新标准；每次调用都是新 identity，不覆盖旧文件。
    return rubric_store.publish(payload)


@app.get("/api/v1/materials/{material_id}/rubric-binding", response_model=RubricBinding | None)
def material_rubric_binding(material_id: str) -> RubricBinding | None:
    if not storage.material_exists(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return storage.get_binding(material_id)


@app.put("/api/v1/materials/{material_id}/rubric-binding", response_model=RubricBinding)
def bind_material_rubric(material_id: str, payload: RubricBindingCreate, response: Response) -> RubricBinding:
    if rubric_store.get_rubric(payload.rubric_id, payload.rubric_revision) is None:
        raise LookupFailed(
            "rubric_not_found", "找不到该评分标准版本", [f"{payload.rubric_id} rev{payload.rubric_revision}"]
        )
    result = storage.bind_material_rubric(material_id, payload.rubric_id, payload.rubric_revision)
    if result is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    binding, created = result
    response.status_code = 201 if created else 200
    return binding


@app.get("/api/v1/materials/{material_id}/criterion-evidence-links", response_model=list[CriterionEvidenceLink])
def material_criterion_links(material_id: str) -> list[CriterionEvidenceLink]:
    if not storage.material_exists(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return storage.list_links(material_id)


@app.post("/api/v1/materials/{material_id}/criterion-evidence-links", response_model=CriterionEvidenceLink, status_code=201)
def create_criterion_link(material_id: str, payload: CriterionEvidenceLinkCreate) -> CriterionEvidenceLink:
    # 顺序：annotation 身份 → 绑定 → criterion 有效性 → 写入（storage 内再做 span/重复防御性复验）。
    annotation = storage.get_evidence_annotation(payload.annotation_id)
    if annotation is None or annotation.material_id != material_id:
        raise LookupFailed(
            "annotation_not_found", "找不到该证据标注，或它不属于该材料", [f"annotation_id={payload.annotation_id}"]
        )
    binding = storage.get_binding(material_id)
    if binding is None:
        raise RubricNotBound("该材料尚未绑定评分标准")
    rubric = rubric_store.get_rubric(binding.rubric_id, binding.rubric_revision)
    if rubric is None:
        raise RubricNotBound(
            "绑定的评分标准版本已不可用", [f"{binding.rubric_id} rev{binding.rubric_revision}"]
        )
    if all(criterion.id != payload.criterion_id for criterion in rubric.criteria):
        raise LookupFailed("criterion_not_found", "找不到该评分要求", [f"criterion_id={payload.criterion_id}"])
    link = storage.create_link(material_id, payload.annotation_id, payload.criterion_id, payload.rationale)
    if link is None:
        raise LookupFailed(
            "annotation_not_found", "找不到该证据标注，或它不属于该材料", [f"annotation_id={payload.annotation_id}"]
        )
    return link


@app.delete("/api/v1/materials/{material_id}/criterion-evidence-links/{link_id}", status_code=204)
def delete_criterion_link(material_id: str, link_id: str) -> Response:
    if not storage.delete_link(material_id, link_id):
        raise LookupFailed("link_not_found", "找不到该关联", [f"id={link_id}"])
    return Response(status_code=204)


# —— Agent 提案（单 criterion 预检）：LLM 只提出候选，服务端验证，人工裁决 ——


def _save_failed_proposal(material: SavedMaterial, criterion_id: str, binding: RubricBinding, message: str, raw):
    settings = llm.load_settings()
    return storage.save_agent_proposal(
        material,
        criterion_id,
        binding.rubric_id,
        binding.rubric_revision,
        settings.base_url or "",
        settings.model or "",
        llm.PROMPT_VERSION,
        "failed",
        message,
        raw,
        [],
    )


@app.post("/api/v1/materials/{material_id}/agent-proposals", response_model=AgentProposal, status_code=201)
def create_agent_proposal(material_id: str, payload: AgentProposalCreate) -> AgentProposal:
    material = storage.get_material(material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    binding = storage.get_binding(material_id)
    if binding is None:
        raise RubricNotBound("该材料尚未绑定评分标准")
    rubric = rubric_store.get_rubric(binding.rubric_id, binding.rubric_revision)
    if rubric is None:
        raise RubricNotBound("绑定的评分标准版本已不可用", [f"{binding.rubric_id} rev{binding.rubric_revision}"])
    criterion = next((item for item in rubric.criteria if item.id == payload.criterion_id), None)
    if criterion is None:
        raise LookupFailed("criterion_not_found", "找不到该评分要求", [f"criterion_id={payload.criterion_id}"])

    try:
        raw_candidates, raw_content, provider, model = llm.propose_candidates(criterion, material.blocks)
    except llm.PromptTooLarge as exc:
        _save_failed_proposal(material, criterion.id, binding, f"material_too_large: {exc.message}", None)
        raise
    except llm.LlmNotConfigured as exc:
        _save_failed_proposal(material, criterion.id, binding, f"llm_unconfigured: {exc.message}", None)
        raise
    except llm.LlmTimeout as exc:
        _save_failed_proposal(material, criterion.id, binding, f"llm_timeout: {exc.message}", None)
        raise
    except llm.LlmUnavailable as exc:
        _save_failed_proposal(material, criterion.id, binding, f"llm_unavailable: {exc.message}", None)
        raise
    except llm.LlmInvalidResponse as exc:
        _save_failed_proposal(material, criterion.id, binding, f"llm_invalid_response: {exc.message}", exc.raw_response)
        raise

    candidates = [
        CandidateInput(item.block_id, item.quote, item.rationale, item.risk_note) for item in raw_candidates
    ]
    return storage.save_agent_proposal(
        material,
        criterion.id,
        binding.rubric_id,
        binding.rubric_revision,
        provider,
        model,
        llm.PROMPT_VERSION,
        "completed",
        None,
        raw_content,
        candidates,
    )


@app.get("/api/v1/materials/{material_id}/agent-proposals", response_model=list[AgentProposal])
def material_agent_proposals(material_id: str, criterion_id: str | None = None) -> list[AgentProposal]:
    if not storage.material_exists(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return storage.list_agent_proposals(material_id, criterion_id)


@app.get("/api/v1/agent-proposals/{proposal_id}", response_model=AgentProposal)
def agent_proposal_by_id(proposal_id: str) -> AgentProposal:
    proposal = storage.get_agent_proposal(proposal_id)
    if proposal is None:
        raise LookupFailed("proposal_not_found", "找不到该提案", [f"id={proposal_id}"])
    return proposal


@app.post(
    "/api/v1/materials/{material_id}/proposal-candidates/{candidate_id}/accept",
    response_model=ProposalAcceptance,
    status_code=201,
)
def accept_proposal_candidate(material_id: str, candidate_id: str) -> ProposalAcceptance:
    acceptance = storage.accept_candidate(material_id, candidate_id)
    if acceptance is None:
        raise LookupFailed("candidate_not_found", "找不到该候选", [f"id={candidate_id}"])
    return acceptance


@app.post(
    "/api/v1/materials/{material_id}/proposal-candidates/{candidate_id}/reject",
    response_model=ProposalCandidate,
)
def reject_proposal_candidate(
    material_id: str, candidate_id: str, payload: ProposalCandidateReject
) -> ProposalCandidate:
    candidate = storage.reject_candidate(material_id, candidate_id, payload.reason)
    if candidate is None:
        raise LookupFailed("candidate_not_found", "找不到该候选", [f"id={candidate_id}"])
    return candidate


# —— P1 Review：一次评审绑定一个评分标准版本，成员引用已保存材料（不做 Finding/报告聚合）——


@app.post("/api/v1/reviews", response_model=Review, status_code=201)
def create_review(payload: ReviewCreate) -> Review:
    # rubric 是文件仓：先校验版本存在，再落库；不存在 404 rubric_not_found。
    if rubric_store.get_rubric(payload.rubric_id, payload.rubric_revision) is None:
        raise LookupFailed(
            "rubric_not_found", "找不到该评分标准版本", [f"{payload.rubric_id} rev{payload.rubric_revision}"]
        )
    return storage.create_review(payload.title, payload.rubric_id, payload.rubric_revision)


@app.get("/api/v1/reviews", response_model=list[Review])
def reviews() -> list[Review]:
    return storage.list_reviews()


@app.get("/api/v1/reviews/{review_id}", response_model=ReviewDetail)
def review_by_id(review_id: str) -> ReviewDetail:
    detail = storage.get_review_detail(review_id)
    if detail is None:
        raise LookupFailed("review_not_found", "找不到该 Review", [f"id={review_id}"])
    return detail


@app.patch("/api/v1/reviews/{review_id}", response_model=Review)
def update_review(review_id: str, payload: ReviewUpdate) -> Review:
    # ReviewUpdate extra="forbid"：带 rubric_id/rubric_revision 的 PATCH 会在校验层被 400 拒绝。
    review = storage.rename_review(review_id, payload.title)
    if review is None:
        raise LookupFailed("review_not_found", "找不到该 Review", [f"id={review_id}"])
    return review


@app.delete("/api/v1/reviews/{review_id}", status_code=204)
def remove_review(review_id: str) -> Response:
    # 只删 Review 本体与成员关系（FK CASCADE）；Material 及其内容、其他历史一律不动。
    if not storage.delete_review(review_id):
        raise LookupFailed("review_not_found", "找不到该 Review", [f"id={review_id}"])
    return Response(status_code=204)


@app.put("/api/v1/reviews/{review_id}/materials/{material_id}", response_model=ReviewMaterialEntry)
def upsert_review_material(
    review_id: str, material_id: str, payload: ReviewMaterialUpsert, response: Response
) -> ReviewMaterialEntry:
    # 区分 404：review 先于 material。首次加入时，未绑定材料由 storage 在同一事务里
    # 绑定本 Review 的标准版本（完成首次 binding，不要求用户理解 binding）；
    # 已绑定其他版本时抛 BindingConflict → 409，绝不自动换绑、不覆盖历史绑定。
    if storage.get_review_detail(review_id) is None:
        raise LookupFailed("review_not_found", "找不到该 Review", [f"id={review_id}"])
    if not storage.material_exists(material_id):
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    result = storage.upsert_review_material(review_id, material_id, payload.label, payload.position)
    if result is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    entry, created = result
    response.status_code = 201 if created else 200
    return entry


@app.delete("/api/v1/reviews/{review_id}/materials/{material_id}", status_code=204)
def remove_review_material(review_id: str, material_id: str) -> Response:
    if storage.get_review_detail(review_id) is None:
        raise LookupFailed("review_not_found", "找不到该 Review", [f"id={review_id}"])
    if not storage.remove_review_material(review_id, material_id):
        raise LookupFailed(
            "membership_not_found", "该材料不在该 Review 中", [f"review_id={review_id}", f"material_id={material_id}"]
        )
    return Response(status_code=204)


@app.exception_handler(PreviewRejected)
async def preview_rejected(request: Request, exc: PreviewRejected) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(criteria_builder.DraftRejected)
async def draft_rejected(request: Request, exc: criteria_builder.DraftRejected) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(rubric_store.RubricRejected)
async def rubric_rejected(request: Request, exc: rubric_store.RubricRejected) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(QuoteNotFound)
async def quote_not_found(request: Request, exc: QuoteNotFound) -> JSONResponse:
    error = ApiError(code="quote_not_found", message=exc.message, details=[])
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(repair_suggest.CitationMismatch)
async def citation_mismatch(request: Request, exc: repair_suggest.CitationMismatch) -> JSONResponse:
    error = ApiError(code="citation_mismatch", message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(cross_compare.SameMaterialCompare)
async def same_material_compare(request: Request, exc: cross_compare.SameMaterialCompare) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(diff.SameMaterialDiff)
async def same_material_diff(request: Request, exc: diff.SameMaterialDiff) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(RequestValidationError)
async def request_invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        f"{'.'.join(str(part) for part in item.get('loc', []))}: {item.get('msg', 'invalid')}"
        for item in exc.errors()
    ]
    error = ApiError(code="invalid_request", message="请求体校验失败", details=details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(LookupFailed)
async def lookup_failed(request: Request, exc: LookupFailed) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=404, content=error.model_dump())


@app.exception_handler(StorageConflict)
async def storage_conflict(request: Request, exc: StorageConflict) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=409, content=error.model_dump())


@app.exception_handler(SpanMismatch)
async def span_mismatch(request: Request, exc: SpanMismatch) -> JSONResponse:
    error = ApiError(code="span_mismatch", message=exc.message, details=[])
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(InvalidCandidate)
async def invalid_candidate(request: Request, exc: InvalidCandidate) -> JSONResponse:
    error = ApiError(code="invalid_candidate", message=exc.message, details=[])
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(llm.LlmNotConfigured)
async def llm_unconfigured(request: Request, exc: llm.LlmNotConfigured) -> JSONResponse:
    error = ApiError(code="llm_unconfigured", message=exc.message, details=["配置 backend/.env 后重启后端"])
    return JSONResponse(status_code=503, content=error.model_dump())


@app.exception_handler(llm.LlmUnavailable)
async def llm_unavailable(request: Request, exc: llm.LlmUnavailable) -> JSONResponse:
    error = ApiError(code="llm_unavailable", message=exc.message, details=[])
    return JSONResponse(status_code=502, content=error.model_dump())


@app.exception_handler(llm.LlmTimeout)
async def llm_timeout(request: Request, exc: llm.LlmTimeout) -> JSONResponse:
    error = ApiError(code="llm_timeout", message=exc.message, details=[])
    return JSONResponse(status_code=504, content=error.model_dump())


@app.exception_handler(llm.LlmInvalidResponse)
async def llm_invalid_response(request: Request, exc: llm.LlmInvalidResponse) -> JSONResponse:
    error = ApiError(code="llm_invalid_response", message=exc.message, details=[])
    return JSONResponse(status_code=502, content=error.model_dump())


@app.exception_handler(llm.PromptTooLarge)
async def prompt_too_large(request: Request, exc: llm.PromptTooLarge) -> JSONResponse:
    error = ApiError(code="material_too_large", message=exc.message, details=[f"上限 {llm.MAX_PROMPT_CHARS} 字符"])
    return JSONResponse(status_code=400, content=error.model_dump())
