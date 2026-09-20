"""Criteria Builder 后端：原始要求 → 可编辑 Criterion 草稿；发布必须人工确认。

- plain_text / markdown：LLM 只负责整理，输出严格 JSON；模型不可用时 API 返回 503，
  用户仍可手工填好 criteria 后直接 POST /api/v1/rubrics 发布（RubricPublish 不依赖草稿）。
- rubric_json：结构化标准由代码确定性转写，不调用模型，评分语义原样保留。
- 评分语义（max_score/weight/rubric_levels/scoring_anchors/aggregation_rule）只有源文本
  真实写出时才允许保留；模型给出的每个数值/档位/锚点都要能在源文本中定位，否则丢弃。
- 草稿不是正式标准：发布必须 confirmed=true，服务端生成新的 (rubric_id, revision)，旧文件永不改写。
"""
import json
import uuid

from pydantic import Field, ValidationError

from . import llm
from .contracts import Contract, CriterionDraft, RubricDraft, RubricDraftRequest, RubricLevel
from .scoring_provenance import (
    resolve_source_quotes,
    retain_supported_scoring,
    validate_aggregation_rule,
)


class DraftRejected(Exception):
    """用户提供的结构化标准无法转写（400 invalid_rubric_source）。"""

    code = "invalid_rubric_source"

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class _ModelLevel(Contract):
    label: str = Field(min_length=1)
    description: str | None = None
    score: float | None = None


class _ModelCriterion(Contract):
    title: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    required_evidence: list[str] = Field(default_factory=list)
    max_score: float | None = None
    weight: float | None = None
    rubric_levels: list[_ModelLevel] | None = None
    scoring_anchors: list[str] | None = None
    # 模型必须给出支持上述评分语义的逐字原文片段；程序逐条复验，支持不了就丢弃。
    scoring_sources: list[str] = Field(default_factory=list)


class _ModelDraft(Contract):
    title: str = Field(min_length=1)
    aggregation_rule: str | None = None
    aggregation_rule_source: str | None = None
    criteria: list[_ModelCriterion] = Field(min_length=1, max_length=50)


_DRAFT_SYSTEM_PROMPT = llm.UNTRUSTED_DATA_POLICY + (
    "任务：把用户提供的要求原文整理成评分标准草稿。"
    "只输出严格 JSON，不要任何其他文字。结构："
    '{"title":"标准标题","aggregation_rule":null,"aggregation_rule_source":null,'
    '"criteria":[{"title":"要求名","requirement":"原要求",'
    '"required_evidence":["需要的依据"],"scoring_sources":["支持评分语义的原文片段"],'
    '"max_score":null,"weight":null,"rubric_levels":null,"scoring_anchors":null}]}。'
    "规则："
    "1. 只整理原文已有的要求，不添加原文没有的要求；最多 50 项。"
    "2. 评分语义只有原文真实写出时才填写，否则必须为 null；"
    "严禁自行设计分数、权重、档位名或评分锚点。"
    "3. 评分语义必须附逐字原文出处：scoring_sources 列出支持它们的原文片段（不得改写）；"
    "aggregation_rule 需要 aggregation_rule_source。程序会逐字复验，支持不了的字段会被丢弃。"
    '4. rubric_levels 每项为 {"label":"档位名（原文原词）","description":"原文描述","score":null}；'
    "scoring_anchors 只放原文原句；description 与 label 一样必须能在来源片段中逐字定位。"
    "5. required_evidence 没有依据时输出 []。"
)


def _model_levels(levels: list[_ModelLevel] | None) -> list[RubricLevel] | None:
    if not levels:
        return None
    cleaned: list[RubricLevel] = []
    for level in levels:
        label = level.label.strip()
        if not label:
            continue
        cleaned.append(
            RubricLevel(
                label=label,
                description=level.description.strip() if level.description and level.description.strip() else None,
                score=level.score,
            )
        )
    return cleaned or None


def _draft_from_text(request: RubricDraftRequest) -> RubricDraft:
    settings = llm.load_settings()
    if not settings.configured:
        raise llm.LlmNotConfigured()
    content = llm.complete(
        settings,
        [
            {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": llm.untrusted_data(request.text)},
        ],
    )
    payload = llm.load_model_json(content)
    try:
        model = _ModelDraft.model_validate(payload)
    except ValidationError as exc:
        raise llm.LlmInvalidResponse("标准草稿结构不合法，请手工编辑或重试") from exc
    if not model.title.strip():
        raise llm.LlmInvalidResponse("标准草稿缺少标题")
    criteria: list[CriterionDraft] = []
    for index, item in enumerate(model.criteria):
        quotes = resolve_source_quotes(request.text, list(item.scoring_sources))
        draft = CriterionDraft(
            id=f"crit_{uuid.uuid4().hex}",
            order=index,
            title=item.title.strip(),
            requirement=item.requirement.strip(),
            required_evidence=[entry.strip() for entry in item.required_evidence if entry.strip()],
            max_score=item.max_score,
            weight=item.weight,
            rubric_levels=_model_levels(item.rubric_levels),
            scoring_anchors=item.scoring_anchors,
        )
        draft = retain_supported_scoring(draft, quotes)
        has_scoring = (
            draft.max_score is not None
            or draft.weight is not None
            or bool(draft.rubric_levels)
            or bool(draft.scoring_anchors)
        )
        criteria.append(draft.model_copy(update={"scoring_sources": quotes if has_scoring else None}))

    rule: str | None = None
    rule_source: str | None = None
    if model.aggregation_rule and model.aggregation_rule.strip():
        candidate = model.aggregation_rule.strip()
        quote = (model.aggregation_rule_source or "").strip()
        if not validate_aggregation_rule(candidate, quote, request.text):
            rule, rule_source = candidate, quote
    return RubricDraft(
        title=model.title.strip(),
        source_note="由模型从用户提供的要求原文整理；草稿未经人工确认，不是正式标准。",
        source_type=request.source_type,
        source_name=request.source_name,
        source_text=request.text,
        aggregation_rule=rule,
        aggregation_rule_source=rule_source,
        model_assisted=True,
        criteria=criteria,
    )


def _draft_from_structured_json(request: RubricDraftRequest) -> RubricDraft:
    """结构化标准确定性转写：不调用模型，源里写明的评分语义原样保留。"""
    try:
        raw = json.loads(request.text)
    except json.JSONDecodeError as exc:
        raise DraftRejected("结构化标准不是合法 JSON", [str(exc)]) from exc
    if not isinstance(raw, dict):
        raise DraftRejected("结构化标准必须是 JSON 对象")
    raw_criteria = raw.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise DraftRejected("结构化标准缺少非空 criteria 数组")
    if len(raw_criteria) > 50:
        raise DraftRejected("结构化标准最多 50 项要求", [f"收到 {len(raw_criteria)} 项"])

    drafts: list[CriterionDraft] = []
    for index, item in enumerate(raw_criteria):
        if not isinstance(item, dict):
            raise DraftRejected(f"criteria[{index}] 不是对象")
        data = dict(item)
        if not str(data.get("id", "")).strip():
            data["id"] = f"crit_{uuid.uuid4().hex}"
        if "order" not in data:
            data["order"] = index
        if "required_evidence" not in data:
            data["required_evidence"] = []
        try:
            draft = CriterionDraft.model_validate(data)
        except ValidationError as exc:
            details = [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]
            raise DraftRejected(f"criteria[{index}] 不符合 Criterion 结构", details) from exc
        # 空列表等价于「源里没有评分语义」：统一为 null，避免下游把空数组当已提供。
        if not draft.rubric_levels:
            draft = draft.model_copy(update={"rubric_levels": None})
        if not draft.scoring_anchors:
            draft = draft.model_copy(update={"scoring_anchors": None})
        if not draft.scoring_sources:
            draft = draft.model_copy(update={"scoring_sources": None})
        drafts.append(draft)

    ids = [draft.id for draft in drafts]
    orders = [draft.order for draft in drafts]
    if len(set(ids)) != len(ids):
        raise DraftRejected("结构化标准含重复的 criterion id")
    if len(set(orders)) != len(orders):
        raise DraftRejected("结构化标准含重复的 criterion order")
    aggregation = raw.get("aggregation_rule")
    if aggregation is not None and not isinstance(aggregation, str):
        raise DraftRejected("aggregation_rule 必须是字符串或 null")
    aggregation_source = raw.get("aggregation_rule_source")
    if aggregation_source is not None and not isinstance(aggregation_source, str):
        raise DraftRejected("aggregation_rule_source 必须是字符串或 null")
    raw_note = raw.get("source_note")
    source_note = raw_note.strip() if isinstance(raw_note, str) and raw_note.strip() else (
        "从用户提供的结构化标准转写；草稿未经人工确认，不是正式标准。"
    )
    raw_title = raw.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else "未命名标准"
    return RubricDraft(
        title=title,
        source_note=source_note,
        source_type=request.source_type,
        source_name=request.source_name,
        source_text=request.text,
        aggregation_rule=aggregation.strip() if aggregation and aggregation.strip() else None,
        aggregation_rule_source=(
            aggregation_source.strip() if aggregation_source and aggregation_source.strip() else None
        ),
        model_assisted=False,
        criteria=drafts,
    )


def draft_requirements(request: RubricDraftRequest) -> RubricDraft:
    if request.source_type == "rubric_json":
        return _draft_from_structured_json(request)
    return _draft_from_text(request)
