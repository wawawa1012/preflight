"""Backend-internal 数值归一化与数字定位。

不是 wire contract：不进入 contracts.py / schema.json / 前端生成类型。
consistency 的候选去重与 cross_compare 的集合比较共用同一实现；不做单位换算。
"""
import re


def value_key(raw: str) -> str:
    """95 与 95.0 视为同一数值；单位仍由调用方单独比较。"""
    number = float(raw)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def number_forms(value: float) -> tuple[str, ...]:
    """一个数值的可靠写法：小数/整数形式，0-1 之间再补百分数形式（权重 30%）。"""
    forms = [f"{value:g}"]
    if float(value).is_integer():
        forms.append(str(int(value)))
    if 0 < value < 1:
        forms.append(f"{value * 100:g}")
    return tuple(dict.fromkeys(forms))


def contains_number(text: str, value: float) -> bool:
    """数值必须以独立 token 出现：20 不得命中 120、20.5 或 200。"""
    alternatives = "|".join(
        re.escape(form) for form in sorted(number_forms(value), key=len, reverse=True)
    )
    return re.search(rf"(?<![\d.]){alternatives}(?![\d.])", text) is not None
