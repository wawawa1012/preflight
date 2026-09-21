"""Phase 0 wire contracts only. No extraction or adjudication implementation.

Edit here, export JSON Schema, then regenerate frontend types. IDs are opaque.
"""
from typing import Annotated, Literal
import math
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Project(Contract):
    id: str
    name: str


class RubricLevel(Contract):
    """源标准里真实写出过的评分档位；label 必须能在源文本中定位，缺失一律不填。"""

    label: str = Field(min_length=1)
    description: str | None = None
    score: float | None = None
    anchor_id: str | None = Field(default=None, min_length=1)
    min_score: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_score: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class Criterion(Contract):
    id: str
    title: str
    requirement: str
    required_evidence: list[str]
    # 评分语义：只有源标准真实写出时才允许填写，否则一律 null。
    # 模型不得自行设计分数/权重/档位/锚点；plain_text/markdown 来源的每个评分字段
    # 必须由 scoring_sources 里的逐字原文片段支持（见 scoring_provenance）。
    max_score: float | None = None
    weight: float | None = None
    rubric_levels: list[RubricLevel] | None = None
    scoring_anchors: list[str] | None = None
    scoring_sources: list[str] | None = None
    scoring_definition_version: Literal["anchors-v1"] | None = None

    @model_validator(mode="after")
    def executable_scoring(self) -> "Criterion":
        if self.scoring_definition_version is None:
            return self
        if self.max_score is None or not math.isfinite(self.max_score) or self.max_score < 0:
            raise ValueError("executable criterion requires finite nonnegative max_score")
        if self.weight is not None and (not math.isfinite(self.weight) or self.weight < 0):
            raise ValueError("weight must be finite and nonnegative")
        levels = self.rubric_levels or []
        ids = [level.anchor_id for level in levels]
        if not levels or any(not aid or not aid.strip() for aid in ids) or len(set(ids)) != len(ids):
            raise ValueError("executable criterion requires unique anchor IDs")
        for level in levels:
            if not level.description or not level.description.strip():
                raise ValueError("anchor conditions are required")
            if level.score is not None:
                if level.min_score is not None or level.max_score is not None:
                    raise ValueError("anchor must define exact score OR range")
                if not math.isfinite(level.score) or not 0 <= level.score <= self.max_score:
                    raise ValueError("anchor score outside criterion bounds")
            elif (level.min_score is None or level.max_score is None
                  or not 0 <= level.min_score <= level.max_score <= self.max_score):
                raise ValueError("anchor requires bounded min/max range")
        return self


class Rubric(Contract):
    id: str
    revision: int = Field(ge=1)
    title: str
    source_note: str
    criteria: list[Criterion]
    # 溯源：publish 时原样保留用户提供的来源与整理方式；旧文件永不改写。
    source_text: str | None = None
    source_type: Literal["plain_text", "markdown", "rubric_json", "manual"] | None = None
    source_name: str | None = None
    aggregation_rule: str | None = None
    aggregation_rule_source: str | None = None
    model_assisted: bool | None = None
    scoring_aggregation: Literal["sum_points_v1"] | None = None


class RubricDraftRequest(Contract):
    text: str = Field(min_length=1, max_length=20000)
    source_type: Literal["plain_text", "markdown", "rubric_json"] = "plain_text"
    source_name: str | None = Field(default=None, max_length=200)


class CriterionDraft(Criterion):
    """草稿项：order 只存在于发布前；publish 校验 id/order 后按 order 排序。"""

    order: int = Field(ge=0)


class RubricDraft(Contract):
    title: str = Field(min_length=1)
    source_note: str = Field(min_length=1)
    # 草稿端点只产生前三种；"manual" 供模型不可用时用户手工发布留档。
    source_type: Literal["plain_text", "markdown", "rubric_json", "manual"]
    source_name: str | None = None
    source_text: str = Field(min_length=1, max_length=20000)
    aggregation_rule: str | None = None
    # aggregation_rule 的逐字来源片段（plain_text/markdown 必填，否则 publish 拒绝）。
    aggregation_rule_source: str | None = None
    model_assisted: bool = False
    criteria: list[CriterionDraft] = Field(min_length=1, max_length=50)
    scoring_aggregation: Literal["sum_points_v1"] | None = None


class RubricPublish(RubricDraft):
    # 显式人工确认后才发布；每次 publish 生成新 identity/revision，旧文件永不改写。
    confirmed: Literal[True]


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
    format: Literal["pdf", "pptx", "docx", "md", "txt"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_status: Literal["pending", "ready", "rejected", "failed"]


class Locator(Contract):
    # One-based source position. DOCX has paragraph positions, never invented pages.
    # table_cell: index = 一基 table 序号；row_index/cell_index/paragraph_index 是表内一基结构序号；
    # block_index 保留既有含义（同一来源单位内的块分组序号），不承载表格结构。
    # 非行格式的 line_number/line_count 为 null：调用方不得用 index 冒充行号。
    kind: Literal["page", "slide", "paragraph", "line", "table_cell"]
    index: int = Field(ge=1)
    end_index: int | None = Field(default=None, ge=1)
    block_index: int = Field(ge=1)
    row_index: int | None = Field(default=None, ge=1)
    cell_index: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=1)


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


class SourceRef(Contract):
    """统一来源引用：material/block 身份 + 半开 code-point span；位置由服务端解析并逐字复验。

    客户端与模型只能选择 block 与 quote（可选显式 start/end 精确选中某次 occurrence），
    不得把 locator/行号当权威提交。
    """

    material_id: str
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def end_after_start(self) -> "SourceRef":
        if self.end <= self.start:
            raise ValueError("end 必须大于 start（半开区间）")
        return self


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
    # resolved 只表示「修改后本次规则未再检出同一 fingerprint」，不代表事实已正确、
    # 风险已解决或修改一定有效；new/unchanged 同理只是本轮规则输出。
    fingerprint: str
    status: Literal["resolved", "new", "unchanged"]
    before_finding_id: str | None
    after_finding_id: str | None


class VersionDiff(Contract):
    """Phase 0 冻结的 Run-based 版本差（尚未实现）；不是 /api/v1/diffs 的 Finding 集合差。"""

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
    # 临时预览响应（旧 Markdown 入口兼容）：documents 尚未入库，因此只有文件身份和只读 blocks。
    document_id: str
    filename: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_count: int = Field(ge=0)
    blocks: list[Block]


class SourcePreview(Contract):
    # 通用预览响应：不写入存储；line_count 只对行格式（md/txt）是真实行数，非行格式为 null。
    document_id: str
    filename: str = Field(min_length=1)
    format: Literal["md", "txt", "docx"]
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_count: int | None = Field(default=None, ge=0)
    parser_version: str | None = None
    blocks: list[Block]


class SavedMaterial(Contract):
    # 2B 最小持久化实体：一份材料 + 全部 Blocks；不是 RunReport 的 Document/MaterialVersion。
    # blocks[].document_id 指向本材料 id（当前只有 Material → Block 两级）。
    # line_count 只对行格式真实；DOCX 为 null（不伪造行号）。
    id: str
    filename: str = Field(min_length=1)
    format: Literal["md", "txt", "docx"]
    parser_version: str | None = None
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_count: int | None = Field(default=None, ge=0)
    created_at: str
    blocks: list[Block]


class MaterialSummary(Contract):
    # 列表专用：不含 blocks，避免列表接口返回全量内容。
    id: str
    filename: str = Field(min_length=1)
    format: Literal["md", "txt", "docx"]
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
    # 请求体：只提交 block 与 quote（可选精确 start/end）；proposed_by 不出现在 Create，防止客户端伪造溯源。
    # HTTP 路径固定写入 "human"；agent 物化路径由服务端设置。
    # material_id 可选：显式断言归属，与 block 实际所属材料不符时 400 material_mismatch；
    # 不提供时由服务端从 block 行派生。显式 start/end 必须同时出现并逐字复验，失败 400 span_mismatch。
    block_id: str
    quote: str = Field(min_length=1)
    note: str | None = None
    material_id: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def span_pair_complete(self) -> "EvidenceAnnotationCreate":
        if (self.start is None) != (self.end is None):
            raise ValueError("start 与 end 必须同时提供或同时省略")
        return self


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
    line_number: int | None = Field(default=None, ge=1)
    locator: Locator
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
    """I7 关键陈述信号：quote == text[start:end]（code point 索引），不判真假。

    line_number 只对行格式（md/txt）是真实行号，其余为 null；位置一律以 locator 为准。
    """

    block_id: str
    line_number: int | None = Field(default=None, ge=1)
    locator: Locator
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    signal: Literal["numeric", "percentage", "comparative", "absolute"]


class ConsistencyCitation(Contract):
    """I8 待核对问题的引用：quote == text[start:end]，可点回原文 Drawer。

    line_number 只对行格式是真实行号，其余为 null；非行来源不得展示为行。
    """

    block_id: str
    line_number: int | None = Field(default=None, ge=1)
    locator: Locator
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    value: str = Field(min_length=1)
    unit: str


class ConsistencyFinding(Contract):
    """I8 同材料数值一致性：只在同一度量词下数值不同（或降级需人工判断）时产生。

    searched_statement_count 是本 Finding 实际参与检查的信号数；statement_scan_limit 是
    「每份材料」的关键陈述提取上限。单材料 Finding 满足 count <= limit；跨材料 Finding 的
    count 是两侧之和（每侧最多 limit 条），可能大于 limit。两者相等只意味着提取达到上限、
    材料可能还有未提取信号，绝不表示已检查全文。
    """

    material_id: str
    kind: Literal["numeric_inconsistency", "needs_review"]
    measure: str
    values: list[str] = Field(min_length=2)
    searched_block_count: int = Field(ge=0)
    searched_statement_count: int = Field(ge=0)
    statement_scan_limit: int = Field(ge=1)
    explanation: str = Field(min_length=1)
    citations: list[ConsistencyCitation] = Field(min_length=2)


class FindingSetDiffRequest(Contract):
    """实际 POST /api/v1/diffs 的请求：用户显式选中的修改前 / 修改后两个材料 id。"""

    material_id_before: str = Field(min_length=1)
    material_id_after: str = Field(min_length=1)


class FindingSetDiffResponse(Contract):
    """实际 POST /api/v1/diffs 的数值 Finding 集合差（resolved/unchanged/new）；不落库、不给分。

    与 VersionDiff 语义不同：这里比较的是两份材料的同材料数值一致性 Finding 指纹集合。
    resolved 只表示修改后本次规则未再检出同一 fingerprint，不代表事实已正确或风险已解决。
    """

    material_id_before: str
    material_id_after: str
    filename_before: str = Field(min_length=1)
    filename_after: str = Field(min_length=1)
    note: str = Field(min_length=1)
    resolved: list[ConsistencyFinding]
    unchanged: list[ConsistencyFinding]
    new: list[ConsistencyFinding]


class RepairSuggestion(Contract):
    """待核对问题的改稿建议：只给文本修改方向，不落库、不改材料、不含结论判词。"""

    suggestion: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1)


class CrossCompareRequest(Contract):
    """两材料数值对照请求：只接受用户显式选中的两个材料 id。"""

    material_id_a: str = Field(min_length=1)
    material_id_b: str = Field(min_length=1)


class CrossCompareResponse(Contract):
    """两材料数值对照结果：findings 只保留引用横跨两份材料的数值对照；不落库、不给分。"""

    material_id_a: str
    material_id_b: str
    filename_a: str = Field(min_length=1)
    filename_b: str = Field(min_length=1)
    findings: list[ConsistencyFinding]


GRILL_PROMPT_MAX_CHARS = 200
GrillTrigger = Literal["numeric_discrepancy", "numeric_statement", "comparative", "absolute", "generic"]


class GrillRequest(Contract):
    """答辩追问请求：只接受用户显式选中的一份材料。"""

    material_id: str = Field(min_length=1)


class GrillQuestion(Contract):
    """答辩追问：quote == block.text[start:end]（复验通过才返回，否则整条丢弃）。

    trigger / why / preparation 由程序按来源特征确定性生成，模型不能提供：why 是「为什么可能
    被问」的人话映射，checklist 是准备方向；两者都不是答案、不是结论，也不表示真实评委会问。
    """

    prompt: str = Field(min_length=1, max_length=GRILL_PROMPT_MAX_CHARS)
    quote: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    locator: Locator
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    trigger: GrillTrigger
    why: str = Field(min_length=1, max_length=120)
    preparation: list[str] = Field(max_length=6)


COACH_QUESTION_MAX_CHARS = 300
COACH_ANSWER_MAX_CHARS = 4000
COACH_CLAIM_MAX_CHARS = 200
COACH_NOTE_MAX_CHARS = 120
COACH_OVERALL_MAX_CHARS = 400
CoachAspect = Annotated[str, Field(min_length=1, max_length=120)]
CoachCondition = Annotated[str, Field(min_length=1, max_length=120)]
CoachFollowUp = Annotated[str, Field(min_length=1, max_length=200)]


class CoachSourceRef(Contract):
    """用户显式选择带入 Coach 的来源（来自当前追问或材料原文）；服务端逐条复验。

    可选显式 start/end 用于精确选中重复文本的某次 occurrence；两者必须同时提供。
    """

    block_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def span_pair_complete(self) -> "CoachSourceRef":
        if (self.start is None) != (self.end is None):
            raise ValueError("start 与 end 必须同时提供或同时省略")
        return self


class ResponseCoachRequest(Contract):
    """答辩教练请求：用户已经写出回答，教练只检查这条回答能否由给定来源支持。"""

    material_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=COACH_QUESTION_MAX_CHARS)
    user_answer: str = Field(min_length=1, max_length=COACH_ANSWER_MAX_CHARS)
    source_refs: list[CoachSourceRef] = Field(default_factory=list, max_length=8)
    review_id: str | None = None

    @field_validator("question", "user_answer")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空白")
        return value


class CoachSource(Contract):
    """程序回填的已验证来源：模型只选择 source_id，quote/block/坐标由代码给出。

    line_number 只对行格式是真实行号，其余为 null；位置以 locator 为准。
    """

    source_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    line_number: int | None = Field(default=None, ge=1)
    locator: Locator
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    basis: str = Field(min_length=1)


class CoachClaim(Contract):
    """用户回答里的一条关键陈述；supported 一方的 source_ids 必须经服务端白名单回填。"""

    text: str = Field(min_length=1, max_length=COACH_CLAIM_MAX_CHARS)
    note: str | None = Field(default=None, max_length=COACH_NOTE_MAX_CHARS)
    source_ids: list[str] = Field(max_length=8)


class ResponseCoachResponse(Contract):
    """答辩教练输出：只评价用户已写出的回答；不给分、不代写答案、不判定现实真假。"""

    material_id: str
    status: Literal["coached", "abstain", "insufficient_context"]
    abstain_reason: str | None = Field(max_length=COACH_NOTE_MAX_CHARS)
    answered_aspects: list[CoachAspect] = Field(max_length=6)
    supported_claims: list[CoachClaim] = Field(max_length=6)
    unsupported_claims: list[CoachClaim] = Field(max_length=6)
    missing_conditions: list[CoachCondition] = Field(max_length=8)
    follow_up_questions: list[CoachFollowUp] = Field(max_length=5)
    source_ids: list[str]
    sources: list[CoachSource]
    overall_note: str = Field(max_length=COACH_OVERALL_MAX_CHARS)


class Review(Contract):
    # P1 Review 领域：一次评审绑定一个评分标准版本，成员材料引用已保存材料（不复制内容）。
    # P1：暂不加入 ContractBundle，前端契约导出阶段再挂。
    id: str
    title: str = Field(min_length=1)
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    created_at: str
    updated_at: str


class ReviewCreate(Contract):
    # P1：暂不加入 ContractBundle，前端契约导出阶段再挂。
    title: str = Field(min_length=1)
    rubric_id: str
    rubric_revision: int = Field(ge=1)


class ReviewUpdate(Contract):
    # 本期只允许改 title；extra="forbid" 使带 rubric_id/rubric_revision 的 PATCH 被 400 拒绝。
    # P1：暂不加入 ContractBundle，前端契约导出阶段再挂。
    title: str = Field(min_length=1)


class ReviewMaterialEntry(Contract):
    # P1：暂不加入 ContractBundle，前端契约导出阶段再挂。
    material_id: str
    label: str = Field(min_length=1)
    position: int = Field(ge=0)


class ReviewMaterialUpsert(Contract):
    # upsert 请求体：省略 label/position 时服务端分别取 filename / 追加到末尾。
    # P1：暂不加入 ContractBundle，前端契约导出阶段再挂。
    label: str | None = Field(default=None, min_length=1)
    position: int | None = Field(default=None, ge=0)


class ReviewDetail(Review):
    # P1：暂不加入 ContractBundle，前端契约导出阶段再挂。
    materials: list[ReviewMaterialEntry]


class MaterialRevision(Contract):
    # Revision v1：只表示“基于此材料创建”，不代表质量改善/审核完成；创建后不可修改。
    child_material_id: str
    parent_material_id: str
    created_at: str


class MaterialRevisionCreate(Contract):
    # text 是完整 Markdown 文本；服务端按真实 UTF-8 bytes 重算 sha256 并重新解析，不信任客户端 locator。
    text: str
    filename: str = Field(min_length=1)
    review_id: str | None = None
    label: str | None = Field(default=None, min_length=1)


class MaterialRevisionCreated(Contract):
    material: SavedMaterial
    revision: MaterialRevision


class RevisionParent(Contract):
    material_id: str
    parent_available: bool


class RevisionChild(Contract):
    material_id: str
    available: bool
    created_at: str


class RevisionContext(Contract):
    # 只返回直接 parent/children；不构成版本树。
    material_id: str
    parent: RevisionParent | None = None
    children: list[RevisionChild]


class EditableSource(Contract):
    # 规范化可编辑文本：LF 换行、按 line_count 补回空行；不承诺 BOM/CRLF/原始终末换行。
    # 仅行格式（md/txt）提供；DOCX 原格式编辑明确拒绝（400 format_not_editable）。
    material_id: str
    format: Literal["md", "txt"]
    text: str
    normalization: Literal["lf"]


AssessmentStatus = Literal["assessed", "insufficient_evidence", "abstain", "execution_failed", "not_scorable"]


class AssessmentScore(Contract):
    kind: Literal["exact", "range"]
    minimum: float = Field(ge=0, allow_inf_nan=False)
    maximum: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> "AssessmentScore":
        if self.minimum > self.maximum or (self.kind == "exact" and self.minimum != self.maximum):
            raise ValueError("invalid score bounds")
        return self


class AssessorProposal(Contract):
    """Only this narrow shape is accepted from the LLM; no scores or SourceRefs."""
    criterion_id: str
    status: Literal["assessed", "insufficient_evidence", "abstain", "not_scorable"]
    selected_anchor_id: str | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=200)
    rationale: str = Field(min_length=1, max_length=4000)
    missing_conditions: list[str] = Field(default_factory=list, max_length=50)
    caveats: list[str] = Field(default_factory=list, max_length=50)


class AssessmentCreate(Contract):
    """Empty request: scope and execution rules are resolved exclusively by the server."""
    pass


class AssessmentResult(Contract):
    criterion_id: str
    status: AssessmentStatus
    selected_anchor_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    rationale: str
    missing_conditions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    score: AssessmentScore | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def numeric_status(self) -> "AssessmentResult":
        if self.status == "assessed":
            if self.score is None or not self.selected_anchor_id or not self.source_ids or self.error_code:
                raise ValueError("assessed requires mapped score, anchor and citations")
        elif self.score is not None or self.selected_anchor_id is not None:
            raise ValueError("non-assessed statuses cannot carry numbers or anchors")
        if (self.status == "execution_failed") != (self.error_code is not None):
            raise ValueError("execution failure requires an error code only on failure")
        return self


class AssessmentSource(Contract):
    """Source ID is the accepted link ID; provenance is frozen, never model-authored."""
    link: CriterionEvidenceLink
    annotation: EvidenceAnnotation
    source: SourceRef


class AssessmentMaterial(Contract):
    material_id: str
    sha256: str
    label: str
    position: int
    ancestor_ids: list[str]


class EvaluationScope(Contract):
    review_id: str
    rubric: Rubric
    scoring_definition_hash: str
    criterion_ids: list[str]
    materials: list[AssessmentMaterial]
    sources: list[AssessmentSource]
    blocks: list[Block]
    source_policy_version: str
    assessment_method_version: str


class AssessmentAggregation(Contract):
    status: Literal["available", "unavailable"]
    score: AssessmentScore | None = None
    reason_codes: list[str]
    assessed_criterion_count: int = Field(ge=0)
    scorable_criterion_count: int = Field(ge=0)
    total_criterion_count: int = Field(ge=0)
    missing_criterion_ids: list[str]

    @model_validator(mode="after")
    def availability(self) -> "AssessmentAggregation":
        if (self.status == "available") != (self.score is not None):
            raise ValueError("only available aggregation has a score")
        if self.status == "available" and (self.reason_codes or self.missing_criterion_ids):
            raise ValueError("available aggregation cannot have blockers")
        return self


class AssessmentSnapshot(Contract):
    id: str
    scope: EvaluationScope
    results: list[AssessmentResult]
    aggregation: AssessmentAggregation
    created_at: str
    model_identifier: str | None = None
    prompt_version: str


class AssessmentSummary(Contract):
    id: str
    review_id: str
    created_at: str
    aggregation: AssessmentAggregation
    assessment_method_version: str


class AssessmentCriterionChange(Contract):
    """observation 只声明本条目哪个维度变化；identical 仅当 status/anchor/score/reason 全等。

    reason 指 error_code、missing_conditions、caveats 与 rationale 的组合；引用来源的增减
    仍以 before/after 原文与 comparison.evidence_scope_changed 呈现，不折叠进本枚举。
    """
    criterion_id: str
    before: AssessmentResult
    after: AssessmentResult
    observation: Literal["identical", "anchor_changed", "reason_changed", "status_changed",
                         "newly_assessable", "became_insufficient",
                         "range_overlaps", "range_shifted_upward", "range_shifted_downward"]
    score_changed: bool
    anchor_changed: bool
    reason_changed: bool


class AssessmentComparison(Contract):
    before_id: str
    after_id: str
    status: Literal["comparable", "not_comparable"]
    reason_codes: list[str]
    evidence_scope_changed: bool
    criteria: list[AssessmentCriterionChange]
    aggregation_before: AssessmentAggregation
    aggregation_after: AssessmentAggregation


class ApiError(Contract):
    code: str
    message: str
    details: list[str]


class ContractBundle(Contract):
    assessment_create: AssessmentCreate
    assessment_snapshot: AssessmentSnapshot
    assessment_summary: AssessmentSummary
    assessment_comparison: AssessmentComparison
    assessor_proposal: AssessorProposal
    rubric_draft_request: RubricDraftRequest
    rubric_draft: RubricDraft
    rubric_publish: RubricPublish
    rubric_level: RubricLevel
    criterion_draft: CriterionDraft
    review: Review
    review_create: ReviewCreate
    review_detail: ReviewDetail
    review_material: ReviewMaterialEntry
    report: RunReport
    diff: VersionDiff
    finding_set_diff_request: FindingSetDiffRequest
    finding_set_diff_response: FindingSetDiffResponse
    run_request: RunRequest
    preview: MarkdownPreview
    source_preview: SourcePreview
    saved_material: SavedMaterial
    material_summary: MaterialSummary
    source_ref: SourceRef
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
    consistency_citation: ConsistencyCitation
    consistency_finding: ConsistencyFinding
    repair_suggestion: RepairSuggestion
    cross_compare_request: CrossCompareRequest
    cross_compare_response: CrossCompareResponse
    grill_request: GrillRequest
    grill_question: GrillQuestion
    coach_source_ref: CoachSourceRef
    response_coach_request: ResponseCoachRequest
    response_coach_response: ResponseCoachResponse
    coach_claim: CoachClaim
    coach_source: CoachSource
    material_revision: MaterialRevision
    material_revision_create: MaterialRevisionCreate
    material_revision_created: MaterialRevisionCreated
    revision_parent: RevisionParent
    revision_child: RevisionChild
    revision_context: RevisionContext
    editable_source: EditableSource
    error: ApiError
