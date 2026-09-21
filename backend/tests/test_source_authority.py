"""SourceAuthority 公共验证向量（纯函数，零 IO）：所有角色共用的来源规则。"""
import unittest

from app.contracts import Block, Locator
from app.evidence import QuoteNotFound, SpanMismatch
from app.source_authority import (
    BlockNotInScope,
    MaterialMismatch,
    SourceAuthority,
    SourceScope,
    line_number_of,
    locator_label,
)


def block(block_id: str, text: str, *, material_id: str = "mat_a", ordinal: int = 0, locator: Locator | None = None) -> Block:
    return Block(
        id=block_id,
        document_id=material_id,
        ordinal=ordinal,
        text=text,
        locator=locator or Locator(kind="line", index=ordinal + 1, end_index=None, block_index=1),
    )


def authority_for(*blocks: Block, allowed: set[str] | None = None) -> SourceAuthority:
    return SourceAuthority(
        SourceScope(
            allowed_material_ids=frozenset(allowed) if allowed is not None else SourceScope.from_blocks(blocks).allowed_material_ids,
            blocks={item.id: item for item in blocks},
        )
    )


class SourceAuthorityVectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = authority_for(block("blk_1", "重复片段出现重复片段"))

    def test_second_occurrence_via_explicit_span(self) -> None:
        first = self.authority.resolve("blk_1", "重复片段")
        second = self.authority.resolve("blk_1", "重复片段", start=6, end=10)
        self.assertEqual((first.start, first.end), (0, 4))
        self.assertEqual((second.start, second.end), (6, 10))
        self.assertEqual((second.material_id, second.block_id, second.block_ordinal), ("mat_a", "blk_1", 0))
        self.assertEqual(second.locator.kind, "line")
        self.assertEqual(second.line_number, 1)

    def test_wrong_material_is_rejected(self) -> None:
        with self.assertRaises(MaterialMismatch) as caught:
            self.authority.resolve("blk_1", "重复片段", material_id="mat_other")
        self.assertEqual(caught.exception.code, "material_mismatch")

    def test_block_outside_scope_is_rejected(self) -> None:
        with self.assertRaises(BlockNotInScope) as caught:
            self.authority.resolve("blk_missing", "任意")
        self.assertEqual(caught.exception.code, "block_not_found")
        foreign = authority_for(block("blk_f", "别的材料", material_id="mat_b"), allowed={"mat_a"})
        with self.assertRaises(BlockNotInScope):
            foreign.resolve("blk_f", "别的材料")

    def test_out_of_bounds_and_quote_mismatch_are_rejected(self) -> None:
        with self.assertRaises(SpanMismatch):
            self.authority.resolve("blk_1", "重复片段", start=0, end=999)
        with self.assertRaises(SpanMismatch):
            self.authority.resolve("blk_1", "出现", start=0, end=4)
        with self.assertRaises(SpanMismatch):
            self.authority.resolve("blk_1", "重复片段", start=6)
        with self.assertRaises(QuoteNotFound):
            self.authority.resolve("blk_1", "不存在的引用")

    def test_non_bmp_indices_are_code_points(self) -> None:
        authority = authority_for(block("blk_e", "🧪🧪准确率 95% 🚀"))
        resolved = authority.resolve("blk_e", "准确率 95%", start=2, end=9)
        self.assertEqual(resolved.quote, "准确率 95%")
        emoji = authority.resolve("blk_e", "🚀", start=10, end=11)
        self.assertEqual((emoji.start, emoji.end), (10, 11))

    def test_verify_returns_none_instead_of_raising(self) -> None:
        self.assertIsNotNone(
            self.authority.verify("blk_1", "重复片段", start=6, end=10)
        )
        self.assertIsNone(self.authority.verify("blk_1", "出现", start=0, end=4))
        self.assertIsNone(self.authority.verify("blk_missing", "重复片段", start=0, end=4))

    def test_resolved_source_context_is_bounded_and_locator_authoritative(self) -> None:
        locator = Locator(
            kind="table_cell", index=1, end_index=None, block_index=1,
            row_index=1, cell_index=2, paragraph_index=3,
        )
        authority = authority_for(block("blk_c", "前文" * 20 + "目标" + "后文" * 20, locator=locator))
        resolved = authority.resolve("blk_c", "目标", context_radius=2)
        self.assertEqual(resolved.context, "前文目标后文")
        self.assertEqual(resolved.locator, locator)
        self.assertIsNone(resolved.line_number)
        self.assertEqual(locator_label(resolved.locator), "table 1 row 1 cell 2 paragraph 3")
        self.assertIsNone(line_number_of(Locator(kind="paragraph", index=3, end_index=None, block_index=1)))
        self.assertEqual(line_number_of(Locator(kind="line", index=3, end_index=None, block_index=1)), 3)


if __name__ == "__main__":
    unittest.main()
