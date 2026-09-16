"""Phase 0 wire contracts only. No extraction or adjudication implementation.

Edit here, export JSON Schema, then regenerate frontend types. IDs are opaque.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
    error: ApiError
