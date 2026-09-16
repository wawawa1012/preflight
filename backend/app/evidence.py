"""Quote → Span 的纯函数验证门：HTTP 与未来 Agent pipeline 共用同一实现。

规则：精确子串匹配、Unicode 代码点索引、重复出现取第一次；未命中抛 QuoteNotFound。
"""


class QuoteNotFound(Exception):
    """quote 在 Block 原文中不存在；由 API 层转成 400 quote_not_found。"""

    def __init__(self, message: str = "quote 不在该 Block 原文中") -> None:
        self.message = message
        super().__init__(message)


def resolve_span(text: str, quote: str) -> tuple[int, int]:
    """返回半开区间 [start, end) 的代码点索引；text[start:end] 必然等于 quote。"""
    if quote == "":
        raise QuoteNotFound("quote 不能为空")
    start = text.find(quote)
    if start < 0:
        raise QuoteNotFound("quote 不在该 Block 原文中")
    return start, start + len(quote)
