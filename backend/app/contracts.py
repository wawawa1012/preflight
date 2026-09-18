"""Phase 0 wire contracts only. No extraction or adjudication implementation.

Edit here, export JSON Schema, then regenerate frontend types. IDs are opaque.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Project(Contract):
    id: str
    name: str


class Criterion(Contract):
    id: str
    title: str
    requirement: str
    required_evidence: list[str]


class Rubric(Contract):
    id: str
    revision: int = Field(ge=1)
    title: str
    source_note: str
    criteria: list[Criterion]


class MaterialVersion(Contract):
    id: str
    project_id: str
    label: str
    document_ids: list[str]


class Document(Contract):
    id: str
    material_version_id: str
    logical_key: str
    filename: str
    format: Literal["pdf", "pptx", "docx", "md"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_status: Literal["pending", "ready", "rejected", "failed"]


class Locator(Contract):
    # One-based source position. DOCX has paragraph positions, never invented pages.
    kind: Literal["page", "slide", "paragraph", "line"]
    index: int = Field(ge=1)
    end_index: int | None = Field(default=None, ge=1)
    block_index: int = Field(ge=1)


class Block(Contract):
    id: str
    document_id: str
    ordinal: int = Field(ge=0)
    text: str
    locator: Locator


class Span(Contract):
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1)


class Claim(Contract):
    id: str
    criterion_ids: list[str]
    text: str
    source: Span
    comparison_key: str | None = None


class Evidence(Contract):
    id: str
    criterion_id: str
    claim_id: str | None = None
    source: Span
    relation: Literal["supports", "contradicts", "context"]
    citation_valid: bool
    validation_error: str | None = None


class Finding(Contract):
    id: str
    fingerprint: str
    criterion_id: str
    kind: Literal["missing_evidence", "weak_evidence", "unsupported_claim", "cross_document_conflict", "overclaim"]
    severity: Literal["critical", "warning", "info"]
    title: str
    explanation: str
    claim_ids: list[str]
    evidence_ids: list[str]
    searched_document_ids: list[str]


class Repair(Contract):
    id: str
    finding_id: str
    instruction: str
    status: Literal["todo", "done"]


class ReviewQuestion(Contract):
    id: str
    finding_id: str
    question: str
    why: str
    outline: list[str]
    evidence_ids: list[str]


class CriterionAssessment(Contract):
    criterion_id: str
    status: Literal["supported", "weak", "missing", "critical", "conflict", "not_evaluated"]
    evidence_ids: list[str]
    finding_ids: list[str]


class Metrics(Contract):
    submission_readiness: Literal["not_evaluated", "blocked", "needs_review", "ready"]
    rubric_coverage: float | None = Field(ge=0, le=1)
    verified_evidence: int = Field(ge=0)
    critical_risks: int = Field(ge=0)
    resolved_risks: int | None = Field(ge=0)


class Run(Contract):
    id: str
    project_id: str
    material_version_id: str
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    mode: Literal["mock", "live", "replay"]
    status: Literal["queued", "running", "completed", "failed"]
    stage: Literal["pending", "extract", "retrieve", "adjudicate", "verify", "aggregate", "done"]
    provider: str | None = None
    model: str | None = None
    prompt_version: str
    error: str | None = None


class RunReport(Contract):
    contract_version: Literal["0.1.0"]
    project: Project
    material_version: MaterialVersion
    rubric: Rubric
    run: Run
    documents: list[Document]
    blocks: list[Block]
    claims: list[Claim]
    evidence: list[Evidence]
    findings: list[Finding]
    repairs: list[Repair]
    assessments: list[CriterionAssessment]
    metrics: Metrics
    review_questions: list[ReviewQuestion]


class DiffEntry(Contract):
    fingerprint: str
    status: Literal["resolved", "new", "unchanged"]
    before_finding_id: str | None
    after_finding_id: str | None


class VersionDiff(Contract):
    before_run_id: str
    after_run_id: str
    comparable: bool
    reason: str | None
    entries: list[DiffEntry]


class RunRequest(Contract):
    material_version_id: str
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    mode: Literal["live", "replay"]


class MarkdownPreview(Contract):
    # 临时预览响应：documents 尚未入库，因此只有文件身份和只读 blocks。
    document_id: str
    filename: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_count: int = Field(ge=0)
    blocks: list[Block]


class SavedMaterial(Contract):
    # 2B 最小持久化实体：一份材料 + 全部 Blocks；不是 RunReport 的 Document/MaterialVersion。
    # blocks[].document_id 指向本材料 id（当前只有 Material → Block 两级）。
    id: str
    filename: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_count: int = Field(ge=0)
    created_at: str
    blocks: list[Block]


class MaterialSummary(Contract):
    # 列表专用：不含 blocks，避免列表接口返回全量内容；文件类型由 filename 后缀展示。
    id: str
    filename: str = Field(min_length=1)
    created_at: str
    block_count: int = Field(ge=0)


class EvidenceAnnotation(Contract):
    # Iteration 3 最小证据层：引用真实 Block 的一段原文（Span 复用冻结结构）。
    # material_id 由服务端从 block 行派生，不接受客户端提交；proposed_by 由服务端按路径设定。
    id: str
    material_id: str
    block_id: str
    source: Span
    note: str | None = None
    proposed_by: Literal["human", "agent"] = "human"
    created_at: str


class EvidenceAnnotationCreate(Contract):
    # 请求体：只提交 block 与 quote；proposed_by 不出现在 Create，防止客户端伪造溯源。
    # HTTP 路径固定写入 "human"；agent 物化路径由服务端设置。
    block_id: str
    quote: str = Field(min_length=1)
    note: str | None = None


class RubricBinding(Contract):
    # 材料 ↔ 只读评分标准的绑定：每份材料最多一条，不换绑、不解绑。
    material_id: str
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    created_at: str


class RubricBindingCreate(Contract):
    rubric_id: str
    rubric_revision: int = Field(ge=1)


class CriterionEvidenceLink(Contract):
    # adjudication 层：人工或 Agent 提出的“这条引用与某评分要求相关”，只记录用途，不做满足/覆盖判定。
    id: str
    material_id: str
    annotation_id: str
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    criterion_id: str
    rationale: str = Field(min_length=1)
    proposed_by: Literal["human", "agent"] = "human"
    created_at: str


class CriterionEvidenceLinkCreate(Contract):
    annotation_id: str
    criterion_id: str
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale 不能为空白")
        return value


class ProposalCandidate(Contract):
    # Agent 提案中的一个候选引用：物化前必须通过服务端验证门；review 为人工裁决。
    id: str
    proposal_id: str
    ordinal: int = Field(ge=0)
    block_id: str
    quote: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    risk_note: str | None = None
    validation_status: Literal["pending", "passed", "invalid"]
    validation_code: str | None = None
    review_status: Literal["unreviewed", "accepted", "rejected"]
    reject_reason: str | None = None
    created_annotation_id: str | None = None
    created_link_id: str | None = None
    created_at: str


class AgentProposal(Contract):
    # 一次单 criterion 预检的记录；失败也落库（status=failed），便于列表审计。
    id: str
    material_id: str
    criterion_id: str
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    provider: str
    model: str
    prompt_version: str
    status: Literal["completed", "failed"]
    error: str | None = None
    created_at: str
    candidates: list[ProposalCandidate]


class AgentProposalCreate(Contract):
    criterion_id: str


class ProposalCandidateReject(Contract):
    reason: str | None = None


class ProposalAcceptance(Contract):
    # accept 的原子结果：物化出的 annotation 与 link（proposed_by=agent）。
    annotation: EvidenceAnnotation
    link: CriterionEvidenceLink


class MaterialPreflightCitation(Contract):
    link_id: str
    annotation_id: str
    criterion_id: str
    block_id: str
    line_number: int = Field(ge=1)
    quote: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    proposed_by: Literal["human", "agent"]
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class MaterialPreflightMissing(Contract):
    searched_block_count: int = Field(ge=0)
    searched_filename: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class MaterialPreflightCriterionRow(Contract):
    criterion_id: str
    title: str
    requirement: str
    verified_citation_count: int = Field(ge=0)
    status: Literal["has_verified_citations", "no_verified_citations_in_scope"]
    citations: list[MaterialPreflightCitation]
    missing: MaterialPreflightMissing | None = None


class MaterialPreflightReport(Contract):
    material_id: str
    filename: str
    block_count: int = Field(ge=0)
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    rubric_title: str
    criteria: list[MaterialPreflightCriterionRow]
    blocks: list[Block]


class MaterialPreflightSummary(Contract):
    material_id: str
    filename: str
    created_at: str
    block_count: int = Field(ge=0)
    bound: bool
    rubric_revision: int | None = None
    verified_citation_count: int = Field(ge=0)
    criteria_total: int | None = None
    criteria_with_citations: int | None = None
    criteria_without_citations: int | None = None


class DetectedStatement(Contract):
    """I7 关键陈述信号：quote == text[start:end]（code point 索引），不判真假。"""

    block_id: str
    line_number: int = Field(ge=1)
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    signal: Literal["numeric", "percentage", "comparative", "absolute"]


class ApiError(Contract):
    code: str
    message: str
    details: list[str]


class ContractBundle(Contract):
    report: RunReport
    diff: VersionDiff
    run_request: RunRequest
    preview: MarkdownPreview
    saved_material: SavedMaterial
    material_summary: MaterialSummary
    evidence_annotation: EvidenceAnnotation
    evidence_annotation_create: EvidenceAnnotationCreate
    rubric_binding: RubricBinding
    rubric_binding_create: RubricBindingCreate
    criterion_evidence_link: CriterionEvidenceLink
    criterion_evidence_link_create: CriterionEvidenceLinkCreate
    proposal_candidate: ProposalCandidate
    agent_proposal: AgentProposal
    agent_proposal_create: AgentProposalCreate
    proposal_candidate_reject: ProposalCandidateReject
    proposal_acceptance: ProposalAcceptance
    material_preflight_report: MaterialPreflightReport
    material_preflight_summary: MaterialPreflightSummary
    material_preflight_criterion_row: MaterialPreflightCriterionRow
    material_preflight_citation: MaterialPreflightCitation
    material_preflight_missing: MaterialPreflightMissing
    detected_statement: DetectedStatement
    error: ApiError
