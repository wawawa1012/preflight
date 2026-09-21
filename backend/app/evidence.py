"""Quote → Span 的纯函数验证门：HTTP、存储与 Agent pipeline 共用同一实现。

规则：精确子串匹配、Unicode 代码点半开区间索引。
- quote-only（旧请求）：保留第一次 occurrence 的兼容行为；未命中抛 QuoteNotFound。
- 显式 start/end（新精确 span）：逐字复验 text[start:end] == quote，失败抛 SpanMismatch，
  绝不静默退回第一次匹配；重复文本因此可以选择第二次及以后的 occurrence。
"""


class QuoteNotFound(Exception):
    """quote 在 Block 原文中不存在；由 API 层转成 400 quote_not_found。"""

    def __init__(self, message: str = "quote 不在该 Block 原文中") -> None:
        self.message = message
        super().__init__(message)


class SpanMismatch(Exception):
    """显式 span 与原文/quote 不一致（越界或逐字不符）；由 API 层转成 400 span_mismatch。"""

    def __init__(self, message: str = "显式 span 与 Block 原文不一致") -> None:
        self.message = message
        super().__init__(message)


def resolve_span(text: str, quote: str) -> tuple[int, int]:
    """旧 quote-only 语义：返回第一次匹配的半开区间；text[start:end] 必然等于 quote。"""
    if quote == "":
        raise QuoteNotFound("quote 不能为空")
    start = text.find(quote)
    if start < 0:
        raise QuoteNotFound("quote 不在该 Block 原文中")
    return start, start + len(quote)


def resolve_source_ref(
    text: str, quote: str, start: int | None = None, end: int | None = None
) -> tuple[int, int]:
    """统一来源复验：quote-only 走第一次匹配；显式 span 必须逐字命中，不做回退。"""
    if start is None and end is None:
        return resolve_span(text, quote)
    if start is None or end is None:
        raise SpanMismatch("start 与 end 必须同时提供")
    if not (0 <= start < end <= len(text)):
        raise SpanMismatch(
            f"span [{start},{end}) 超出 Block 文本范围（长度 {len(text)}）"
        )
    if text[start:end] != quote:
        raise SpanMismatch("span 指向的原文与 quote 不一致")
    return start, end


def span_matches(text: str, start: int, end: int, quote: str) -> bool:
    """读取路径的复验：存储的 span 必须仍与不可变 Block 文本逐字一致。"""
    return 0 <= start < end <= len(text) and text[start:end] == quote
