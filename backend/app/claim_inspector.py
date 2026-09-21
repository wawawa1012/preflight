"""I7 关键陈述扫描：在 Block 原文中标出数字/比例/比较/绝对化信号。

纯函数、零 IO；只标出「值得核对的陈述」，不判真假、不产生 Finding、不落库。
匹配索引是 Unicode code point（Python str 语义），与 Span 契约一致。
输出上限 20 条，重叠匹配按 比例 > 绝对化 > 比较 > 数字 去重。
"""
import re

from .contracts import Block, DetectedStatement, Locator

MAX_STATEMENTS = 20


def line_number_of(block: Block) -> int | None:
    """真实行号只对行格式存在；非行来源一律 null，不用 index 冒充行号。"""
    return block.locator.index if block.locator.kind == "line" else None


def locator_label(locator: Locator) -> str:
    """人类可读的位置标签；prompt 与非行来源展示共用，避免把段落/表格说成行。"""
    if locator.kind == "line":
        return f"line {locator.index}"
    if locator.kind == "paragraph":
        return f"paragraph {locator.index}"
    if locator.kind == "page":
        return f"page {locator.index}"
    if locator.kind == "slide":
        return f"slide {locator.index}"
    if locator.kind == "table_cell":
        return (
            f"table {locator.index} row {locator.row_index} cell {locator.cell_index}"
            f" paragraph {locator.paragraph_index}"
        )
    return f"{locator.kind} {locator.index}"

PERCENTAGE_PATTERN = re.compile(r"\d+(?:\.\d+)?%")
ABSOLUTE_PATTERN = re.compile(r"首创|唯一|完全解决|100%")
COMPARATIVE_PATTERN = re.compile(r"(?:优于|高于|低于|提升|降低)[^，。；;！？!?\n]{0,12}|(?:\d+(?:\.\d+)?\s*倍)")
NUMERIC_PATTERN = re.compile(r"\d+(?:\.\d+)?")

# 数字只有带单位或带上下文才值得核对；纯题号/页码不算关键陈述。
NUMERIC_UNITS = (
    "秒", "毫秒", "ms", "MB", "GB", "KB", "倍", "万", "亿",
    "个", "条", "次", "份", "页", "人", "天", "小时", "分钟",
)
NUMERIC_CONTEXT = (
    "达到", "准确", "延迟", "耗时", "响应", "吞吐", "提高", "提升", "降低",
    "超过", "不足", "至少", "最多", "平均",
)

_SIGNALS = (
    ("percentage", 1, PERCENTAGE_PATTERN),
    ("absolute", 2, ABSOLUTE_PATTERN),
    ("comparative", 3, COMPARATIVE_PATTERN),
    ("numeric", 4, NUMERIC_PATTERN),
)


def _numeric_context_ok(text: str, start: int, end: int) -> bool:
    tail = text[end:end + 3].lstrip()
    if tail.startswith(NUMERIC_UNITS):
        return True
    head = text[max(0, start - 8):start]
    return any(word in head for word in NUMERIC_CONTEXT)


def inspect_statements(blocks: list[Block]) -> list[DetectedStatement]:
    found: list[DetectedStatement] = []
    for block in blocks:
        text = block.text
        candidates: list[tuple[int, int, int, str]] = []
        for signal, priority, pattern in _SIGNALS:
            for match in pattern.finditer(text):
                if signal == "numeric" and not _numeric_context_ok(text, match.start(), match.end()):
                    continue
                candidates.append((match.start(), priority, match.end(), signal))
        accepted: list[tuple[int, int]] = []
        rows: list[tuple[int, int, str]] = []
        for start, _priority, end, signal in sorted(candidates):
            if any(start < used_end and end > used_start for used_start, used_end in accepted):
                continue
            accepted.append((start, end))
            rows.append((start, end, signal))
        for start, end, signal in sorted(rows):
            found.append(
                DetectedStatement(
                    block_id=block.id,
                    line_number=line_number_of(block),
                    locator=block.locator,
                    quote=text[start:end],
                    start=start,
                    end=end,
                    signal=signal,
                )
            )
            if len(found) >= MAX_STATEMENTS:
                return found
    return found
