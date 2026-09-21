"""Imported-source（plain_text / markdown）评分语义的局部 provenance。

规则（只用于 plain_text / markdown 来源；rubric_json 结构化原文与 manual 用户自撰规则不走本校验）：
- 每个评分字段必须由 criterion.scoring_sources 里的逐字原文片段支持；
- 片段必须逐字存在于 source_text（resolve_span 复验）；
- 数值必须以独立 token 出现：max_score=20 不得被「120 个样本」命中；
- 档位 label、description、score 与 scoring_anchors 必须能在来源片段中定位；
  仅有 label 不能认证模型虚构的 description；
- 无法可靠确认：草稿路径丢弃该字段，publish 路径拒绝（RubricRejected）。
"""
from .contracts import Criterion, CriterionDraft
from .evidence import QuoteNotFound, resolve_span
from .numeric_value import contains_number


def resolve_source_quotes(source_text: str, quotes: list[str]) -> list[str]:
    """静默丢弃不在 source_text 中的片段；保序、去除空白与重复。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in quotes:
        quote = raw.strip()
        if not quote or quote in seen:
            continue
        try:
            resolve_span(source_text, quote)
        except QuoteNotFound:
            continue
        seen.add(quote)
        result.append(quote)
    return result


def _text_supported(quotes: list[str], text: str | None) -> bool:
    return bool(text) and any(text in quote for quote in quotes)


def _number_supported(quotes: list[str], value: float) -> bool:
    return any(contains_number(quote, value) for quote in quotes)


def retain_supported_scoring(criterion: CriterionDraft, quotes: list[str]) -> CriterionDraft:
    """草稿路径：丢弃无法由来源片段支持的评分字段，而不是把它交给用户去确认。"""
    update: dict[str, object] = {}
    if criterion.max_score is not None and not _number_supported(quotes, criterion.max_score):
        update["max_score"] = None
    if criterion.weight is not None and not _number_supported(quotes, criterion.weight):
        update["weight"] = None
    if criterion.rubric_levels:
        kept = []
        for level in criterion.rubric_levels:
            if not _text_supported(quotes, level.label):
                continue
            description = level.description if _text_supported(quotes, level.description) else None
            score = level.score if level.score is None or _number_supported(quotes, level.score) else None
            kept.append(level.model_copy(update={"description": description, "score": score}))
        if kept != criterion.rubric_levels:
            update["rubric_levels"] = kept or None
    if criterion.scoring_anchors:
        kept_anchors = [anchor for anchor in criterion.scoring_anchors if _text_supported(quotes, anchor.strip())]
        if kept_anchors != criterion.scoring_anchors:
            update["scoring_anchors"] = kept_anchors or None
    return criterion.model_copy(update=update) if update else criterion


def validate_imported_scoring(criterion: Criterion, source_text: str) -> list[str]:
    """publish 路径：确认=true 不能跳过本校验；返回不支持项，空列表才是通过。"""
    problems: list[str] = []
    quotes: list[str] = []
    seen: set[str] = set()
    for raw in criterion.scoring_sources or []:
        quote = raw.strip()
        if not quote:
            problems.append(f"{criterion.id}: scoring_sources 不能含空白片段")
            continue
        if quote in seen:
            continue
        seen.add(quote)
        try:
            resolve_span(source_text, quote)
        except QuoteNotFound:
            problems.append(f"{criterion.id}: 评分来源片段不在 source_text 中：{quote[:40]}")
            continue
        quotes.append(quote)
    has_scoring = (
        criterion.max_score is not None
        or criterion.weight is not None
        or bool(criterion.rubric_levels)
        or bool(criterion.scoring_anchors)
    )
    if has_scoring and not quotes:
        problems.append(f"{criterion.id}: 评分语义缺少可由 source_text 复验的来源片段")
    if criterion.max_score is not None and not _number_supported(quotes, criterion.max_score):
        problems.append(f"{criterion.id}: max_score={criterion.max_score:g} 未被任何来源片段支持")
    if criterion.weight is not None and not _number_supported(quotes, criterion.weight):
        problems.append(f"{criterion.id}: weight={criterion.weight:g} 未被任何来源片段支持")
    for level in criterion.rubric_levels or []:
        for bound in (level.min_score, level.max_score):
            if bound is not None and not _number_supported(quotes, bound):
                problems.append(f"{criterion.id}: anchor bound 未被来源片段支持")
        if not _text_supported(quotes, level.label):
            problems.append(f"{criterion.id}: 档位「{level.label}」未在来源片段中出现")
        if level.description and not _text_supported(quotes, level.description):
            problems.append(f"{criterion.id}: 档位「{level.label}」的 description 未在来源片段中出现")
        if level.score is not None and not _number_supported(quotes, level.score):
            problems.append(f"{criterion.id}: 档位「{level.label}」的 score 未被来源片段支持")
    for anchor in criterion.scoring_anchors or []:
        if not _text_supported(quotes, anchor.strip()):
            problems.append(f"{criterion.id}: scoring_anchor 未在来源片段中出现：{anchor[:40]}")
    return problems


def validate_aggregation_rule(rule: str | None, rule_source: str | None, source_text: str) -> list[str]:
    """aggregation_rule 也必须由逐字片段支持；rule 为空时不要求来源。"""
    if rule is None:
        return []
    quote = (rule_source or "").strip()
    if not quote:
        return ["aggregation_rule 缺少逐字来源片段"]
    try:
        resolve_span(source_text, quote)
    except QuoteNotFound:
        return [f"aggregation_rule 来源片段不在 source_text 中：{quote[:40]}"]
    if rule.strip() not in quote:
        return ["aggregation_rule 未被其来源片段支持"]
    return []
