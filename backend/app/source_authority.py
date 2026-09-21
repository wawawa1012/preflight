"""SourceAuthority：程序已加载、允许访问的固定来源范围内唯一的引用验证规则。

结构：
    SourceScope（allowed material ids + blocks by id + text/ordinal/locator）
        ↓
    SourceAuthority.resolve(...)  →  ResolvedSource

规则统一（所有业务角色共用同一实现）：
- material ownership：block.document_id 必须在 scope 允许的材料集合内；显式 material_id 断言必须一致；
- block ownership：block_id 必须在 scope 的 blocks 内；
- start/end range、quote == text[start:end]、explicit occurrence、Unicode code point span：
  复用 evidence.resolve_source_ref（quote-only 第一次 occurrence 兼容；显式 span 不回退）。

边界：
- SourceAuthority 只证明“这个引用确实位于允许的材料中”，绝不证明相关、充分支持或事实正确。
- SourceAuthority 自己决定失败类型（抛规则违例），不决定 HTTP status / 是否丢弃候选；
  人工输入、LLM 候选、Repair 引用各自的失败策略由调用角色决定。
- 不查全库：scope 由调用方从已加载的数据构建。
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .contracts import Block, Locator
from .evidence import QuoteNotFound, SpanMismatch, resolve_source_ref


class SourceRuleViolation(Exception):
    """来源规则违例基类；code 供调用角色映射为各自的失败策略。"""

    code = "source_rule_violation"

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class BlockNotInScope(SourceRuleViolation):
    """block 不存在或不在允许的材料范围内；人工输入通常 404 block_not_found。"""

    code = "block_not_found"


class MaterialMismatch(SourceRuleViolation):
    """显式提供了 material_id 但 block 不属于该材料；人工输入 400 material_mismatch。"""

    code = "material_mismatch"

    def __init__(self, message: str = "block 不属于该材料", details: list[str] | None = None) -> None:
        super().__init__(message, details)


def line_number_of(locator: Locator) -> int | None:
    """真实行号只对行格式存在；非行来源一律 null，不用 index 冒充行号。"""
    return locator.index if locator.kind == "line" else None


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


@dataclass(frozen=True)
class SourceScope:
    """调用方已加载并允许访问的来源范围；authory 不越过它查库。"""

    allowed_material_ids: frozenset[str]
    blocks: Mapping[str, Block]

    @classmethod
    def from_material(cls, material) -> "SourceScope":
        return cls(
            allowed_material_ids=frozenset({material.id}),
            blocks={block.id: block for block in material.blocks},
        )

    @classmethod
    def from_blocks(
        cls, blocks: Iterable[Block], *, allowed_material_ids: Iterable[str] | None = None
    ) -> "SourceScope":
        block_list = list(blocks)
        allowed = (
            frozenset(allowed_material_ids)
            if allowed_material_ids is not None
            else frozenset(block.document_id for block in block_list)
        )
        return cls(allowed_material_ids=allowed, blocks={block.id: block for block in block_list})

    def get_block(self, block_id: str) -> Block | None:
        block = self.blocks.get(block_id)
        if block is None or block.document_id not in self.allowed_material_ids:
            return None
        return block


@dataclass(frozen=True)
class ResolvedSource:
    """已验证引用：只证明它位于允许的材料中；locator/ordinal 为服务端权威值。"""

    material_id: str
    block_id: str
    start: int
    end: int
    quote: str
    block_ordinal: int
    locator: Locator
    context: str | None = None

    @property
    def line_number(self) -> int | None:
        return line_number_of(self.locator)


class SourceAuthority:
    """在固定 SourceScope 内解析引用；失败抛 SourceRuleViolation / QuoteNotFound / SpanMismatch。"""

    def __init__(self, scope: SourceScope) -> None:
        self._scope = scope

    @property
    def scope(self) -> SourceScope:
        return self._scope

    def resolve(
        self,
        block_id: str,
        quote: str,
        *,
        start: int | None = None,
        end: int | None = None,
        material_id: str | None = None,
        context_radius: int | None = None,
    ) -> ResolvedSource:
        block = self._scope.get_block(block_id)
        if block is None:
            raise BlockNotInScope(
                "block 不在允许的来源范围内",
                [f"block_id={block_id}", f"material_id={material_id or '（未声明）'}"],
            )
        if material_id is not None and material_id != block.document_id:
            raise MaterialMismatch(
                "block 不属于声明的材料",
                [f"block_id={block_id}", f"material_id={material_id}", f"actual={block.document_id}"],
            )
        resolved_start, resolved_end = resolve_source_ref(block.text, quote, start, end)
        context = None
        if context_radius is not None:
            context = block.text[
                max(0, resolved_start - context_radius) : resolved_end + context_radius
            ]
        return ResolvedSource(
            material_id=block.document_id,
            block_id=block.id,
            start=resolved_start,
            end=resolved_end,
            quote=quote,
            block_ordinal=block.ordinal,
            locator=block.locator,
            context=context,
        )

    def verify(
        self,
        block_id: str,
        quote: str,
        *,
        start: int,
        end: int,
        context_radius: int | None = None,
    ) -> ResolvedSource | None:
        """读取路径的软验证：规则违例返回 None，供“跳过不可复验引用”的角色使用。"""
        try:
            return self.resolve(
                block_id, quote, start=start, end=end, context_radius=context_radius
            )
        except (SourceRuleViolation, QuoteNotFound, SpanMismatch):
            return None
