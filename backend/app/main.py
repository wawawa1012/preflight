from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Literal

from . import llm, rubric_store, storage
from .claim_inspector import inspect_statements
from .consistency import find_numeric_findings
from .contracts import (
    AgentProposal,
    AgentProposalCreate,
    ApiError,
    ConsistencyFinding,
    CriterionEvidenceLink,
    CriterionEvidenceLinkCreate,
    DetectedStatement,
    EvidenceAnnotation,
    EvidenceAnnotationCreate,
    MarkdownPreview,
    MaterialPreflightReport,
    MaterialPreflightSummary,
    MaterialSummary,
    ProposalAcceptance,
    ProposalCandidate,
    ProposalCandidateReject,
    Rubric,
    RubricBinding,
    RubricBindingCreate,
    RunReport,
    SavedMaterial,
)
from .evidence import QuoteNotFound
from .markdown_preview import MAX_BYTES, PreviewRejected, build_preview
from .mock_report import MOCK_REPORT
from .preflight_report import assemble_report, assemble_summaries
from .storage import CandidateInput, InvalidCandidate, RubricNotBound, SpanMismatch, StorageConflict


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


@app.exception_handler(PreviewRejected)
async def preview_rejected(request: Request, exc: PreviewRejected) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(QuoteNotFound)
async def quote_not_found(request: Request, exc: QuoteNotFound) -> JSONResponse:
    error = ApiError(code="quote_not_found", message=exc.message, details=[])
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
