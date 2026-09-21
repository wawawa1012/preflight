"""I8 同材料数值一致性：从 I7 关键陈述派生「待核对问题」。

纯函数、零 IO、不调 LLM、不写库；Block 原文只用于复验 span 与读取数值/度量上下文。
判定纪律（宁漏勿错）：
- 同一度量词 + 同一单位 + 不同数值 → numeric_inconsistency；
- 同一度量词但单位写法不一致，或没有度量词、只有同一量纲单位 + 不同数值 → needs_review；
- 其余一律不报：同值、不同度量词、单条无对照、span 复验不过的陈述。
本模块只报告材料内部可复验的数值差异，不判断外部真实性，也不给分。
"""
import re

from .claim_inspector import MAX_STATEMENTS
from .contracts import Block, ConsistencyCitation, ConsistencyFinding, DetectedStatement
from .evidence import span_matches
from .numeric_value import value_key

NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")

# 单位按长度倒序匹配（「个百分点」先于「个」，「毫秒」先于「秒」）。
UNITS = (
    "个百分点", "毫秒", "小时", "分钟", "ms", "MS", "KB", "MB", "GB",
    "秒", "倍", "万", "亿", "个", "条", "次", "份", "页", "人", "天", "%", "％",
)
_UNITS_BY_LENGTH = tuple(sorted(UNITS, key=len, reverse=True))
UNIT_ALIASES = {"％": "%", "ms": "毫秒", "MS": "毫秒"}

# 量纲单位：够得上「同一个量」的比较；只有它们在没有度量词时才降级为 needs_review。
QUANTITATIVE_UNITS = {"%", "个百分点", "倍", "毫秒", "秒", "分钟", "小时", "KB", "MB", "GB"}

# 数值前的连接词/动词/修饰：剥掉后剩下的才是度量词（「准确率降低到 90%」→「准确率」）。
CONNECTORS = (
    "超过", "不足", "至少", "最多", "达到", "平均", "提升", "提高", "降低", "保持",
    "约", "为", "是", "占", "达", "至", "到", "有", "在", "共", "从",
)
_CONNECTORS_BY_LENGTH = tuple(sorted(CONNECTORS, key=len, reverse=True))
MEASURE_PREFIXES = ("平均", "大约")
PARTICLES = ("的", "之")
MEASURE_MAX = 6


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _match_unit_token(text: str) -> str | None:
    """返回原文里匹配到的单位写法（未归一化），没有则 None。"""
    stripped = text.lstrip(" \t　")
    for unit in _UNITS_BY_LENGTH:
        if stripped.startswith(unit):
            return unit
    return None


def _trailing_measure(text: str) -> str:
    """取窗口末尾的汉字串作为度量词；剥离「的/之」前缀与「平均/大约」修饰。"""
    run = ""
    for char in reversed(text):
        if not _is_cjk(char):
            break
        run = char + run
    for particle in PARTICLES:
        if particle in run:
            run = run.rsplit(particle, 1)[1]
    for prefix in MEASURE_PREFIXES:
        if run.startswith(prefix):
            run = run[len(prefix):]
    return run[-MEASURE_MAX:] if len(run) > MEASURE_MAX else run


def _measure_before(text: str, start: int) -> str:
    window = text[max(0, start - 14):start].rstrip(" \t　:：,，、（(")
    # 连续剥掉连接词：如「准确率降低到」→「准确率」。
    for _ in range(3):
        for connector in _CONNECTORS_BY_LENGTH:
            if window.endswith(connector):
                window = window[: -len(connector)].rstrip(" \t　")
                break
        else:
            break
    return _trailing_measure(window)


def _measure_after(text: str, end: int) -> str:
    """数值后置写法（如「95% 的准确率」）：只有消费掉单位或「的」之后才承认度量词。"""
    window = text[end:end + 12].lstrip(" \t　")
    consumed = False
    unit_token = _match_unit_token(window)
    if unit_token is not None:
        window = window[len(unit_token):].lstrip(" \t　")
        consumed = True
    if window[:1] in PARTICLES:
        window = window[1:].lstrip(" \t　")
        consumed = True
    if not consumed:
        return ""
    run = ""
    for char in window:
        if not _is_cjk(char):
            break
        run += char
    return run[-MEASURE_MAX:] if len(run) > MEASURE_MAX else run


class _Measurement:
    __slots__ = ("value", "unit", "display", "value_key", "measure")

    def __init__(self, value: str, unit: str, measure: str) -> None:
        self.value = value
        self.unit = unit
        self.display = f"{value}{unit}"
        self.value_key = value_key(value)
        self.measure = measure


def _measurement_for(statement: DetectedStatement, block: Block) -> _Measurement | None:
    """从一条关键陈述提取数值与度量词；span 复验不过或没有数字则 None（宁漏勿错）。"""
    text = block.text
    # 原文是事实源：复用统一 span 规则，对不上就不参与判定。
    if not span_matches(text, statement.start, statement.end, statement.quote):
        return None
    match = NUMBER_PATTERN.search(statement.quote)
    if match is None:
        return None
    value = match.group(0)
    unit_token = _match_unit_token(statement.quote[match.end():])
    if unit_token is None:
        unit_token = _match_unit_token(text[statement.end:statement.end + 4])
    unit = UNIT_ALIASES.get(unit_token, unit_token) if unit_token else ""
    measure = _measure_before(text, statement.start) or _measure_after(text, statement.end)
    return _Measurement(value, unit, measure)


def _ordered(
    entries: list[tuple[DetectedStatement, _Measurement]], block_order: dict[str, int]
) -> list[tuple[DetectedStatement, _Measurement]]:
    """按 Block.ordinal（blocks 列表即正文顺序）+ span 排序；不用 line_number 排序。"""
    return sorted(entries, key=lambda entry: (block_order[entry[0].block_id], entry[0].start))


def _canonical_measures(measures: set[str]) -> dict[str, str]:
    """把「系统准确率」这类带主语的写法归并到「准确率」。

    规则：度量词若以另一个长度 ≥ 3 的度量词结尾，就归并到那个更短的；
    长度 2 的词（如「延迟」）不参与归并，避免把「模型延迟」与「系统延迟」误判成同一度量。
    """
    canonicals: list[str] = []
    mapping: dict[str, str] = {}
    for measure in sorted(measures, key=lambda item: (len(item), item)):
        targets = [item for item in canonicals if measure.endswith(item) and len(item) >= 3]
        chosen = max(targets, key=len) if targets else measure
        if not targets:
            canonicals.append(measure)
        mapping[measure] = chosen
    return mapping


def _distinct_values(
    entries: list[tuple[DetectedStatement, _Measurement]],
    block_order: dict[str, int],
    *,
    unit_aware: bool = False,
) -> list[str]:
    """按首次出现顺序列出不同数值（展示形式，带单位）。

    unit_aware=True 时以 (数值, 单位) 判重，供 cross_compare 使用：95 ms 与 95 秒
    不能因为裸数值相同就被合并成一条；默认 False 保持同材料历史语义不变。
    """
    seen_keys: set[object] = set()
    values: list[str] = []
    for _statement, item in _ordered(entries, block_order):
        key: object = (item.value_key, item.unit) if unit_aware else item.value_key
        if key in seen_keys:
            continue
        seen_keys.add(key)
        values.append(item.display)
    return values


def _build_finding(
    kind: str,
    entries: list[tuple[DetectedStatement, _Measurement]],
    values: list[str],
    measure: str,
    block_count: int,
    statement_count: int,
    material_id: str,
    block_order: dict[str, int],
) -> ConsistencyFinding:
    ordered = _ordered(entries, block_order)
    citations = [
        ConsistencyCitation(
            block_id=statement.block_id,
            line_number=statement.line_number,
            locator=statement.locator,
            quote=statement.quote,
            start=statement.start,
            end=statement.end,
            value=item.value,
            unit=item.unit,
        )
        for statement, item in ordered
    ]
    joined = "、".join(values)
    coverage = "已达提取上限" if statement_count >= MAX_STATEMENTS else "未达提取上限"
    scope = (
        f"扫描范围：{block_count} 段原文，参与检查 {statement_count} 条已提取信号"
        f"（关键信号提取上限 {MAX_STATEMENTS} 条，{coverage}，非全文穷尽检查）"
    )
    if kind == "numeric_inconsistency":
        explanation = (
            f"同一度量词「{measure}」在本材料 {len(citations)} 处给出不同数值：{joined}；"
            f"{scope}，请核对后决定以哪一处为准。"
        )
    elif measure:
        explanation = (
            f"同一度量词「{measure}」出现不同数值：{joined}，但单位写法不一致，不能直接比较；"
            f"{scope}，需人工判断。"
        )
    else:
        explanation = (
            f"同一单位「{entries[0][1].unit}」出现不同数值：{joined}，但没有共同度量词，"
            f"无法判定是否同一指标；{scope}，需人工判断。"
        )
    return ConsistencyFinding(
        material_id=material_id,
        kind=kind,
        measure=measure,
        values=values,
        searched_block_count=block_count,
        searched_statement_count=statement_count,
        statement_scan_limit=MAX_STATEMENTS,
        explanation=explanation,
        citations=citations,
    )


def find_numeric_findings(
    statements: list[DetectedStatement], blocks: list[Block], *, unit_aware: bool = False
) -> list[ConsistencyFinding]:
    """返回数值一致性 Finding；宁漏勿错，空列表是合法结果。

    unit_aware=False 是单材料历史语义（同数值不同单位不报）；cross_compare 传 True，
    候选形成阶段就保留单位 identity（95 ms vs 95 秒 不能被裸数值去重吞掉）。
    """
    blocks_by_id = {block.id: block for block in blocks}
    # blocks 列表即正文顺序（存储按 ordinal 读出）；排序与展示都以此为准。
    block_order = {block.id: index for index, block in enumerate(blocks)}
    measured: list[tuple[DetectedStatement, _Measurement]] = []
    for statement in statements:
        block = blocks_by_id.get(statement.block_id)
        if block is None:
            continue
        item = _measurement_for(statement, block)
        if item is not None:
            measured.append((statement, item))

    block_count = len(blocks)
    statement_count = len(statements)
    findings: list[ConsistencyFinding] = []

    # 1) 有度量词：按度量词归并（同义写法先收敛到更短的通用词）；同一单位 + 不同数值才算数值不一致。
    by_measure: dict[str, list[tuple[DetectedStatement, _Measurement]]] = {}
    canonical = _canonical_measures({item.measure for _statement, item in measured if item.measure})
    for entry in measured:
        if entry[1].measure:
            by_measure.setdefault(canonical[entry[1].measure], []).append(entry)
    for measure, entries in by_measure.items():
        values = _distinct_values(entries, block_order, unit_aware=unit_aware)
        if len(values) < 2:
            continue
        units = {item.unit for _statement, item in entries}
        kind = "numeric_inconsistency" if len(units) == 1 else "needs_review"
        findings.append(
            _build_finding(
                kind,
                entries,
                values,
                measure,
                block_count,
                statement_count,
                blocks_by_id[entries[0][0].block_id].document_id,
                block_order,
            )
        )

    # 2) 没有度量词：只有同一量纲单位 + 不同数值才降级为 needs_review，其余不报。
    #    unit_aware（cross-material）时把所有量纲单位放进同一桶，单位差异留给分类降级；
    #    单材料默认按单位分桶，历史语义不变。
    by_unit: dict[str, list[tuple[DetectedStatement, _Measurement]]] = {}
    for entry in measured:
        if not entry[1].measure and entry[1].unit in QUANTITATIVE_UNITS:
            bucket = "" if unit_aware else entry[1].unit
            by_unit.setdefault(bucket, []).append(entry)
    for _unit, entries in by_unit.items():
        values = _distinct_values(entries, block_order, unit_aware=unit_aware)
        if len(values) < 2:
            continue
        findings.append(
            _build_finding(
                "needs_review",
                entries,
                values,
                "",
                block_count,
                statement_count,
                blocks_by_id[entries[0][0].block_id].document_id,
                block_order,
            )
        )

    findings.sort(key=lambda item: (block_order[item.citations[0].block_id], item.citations[0].start))
    return findings
