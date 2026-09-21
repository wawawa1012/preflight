"""Iteration 7：关键陈述扫描（纯函数、零 IO、不判真假、不落库、不调 LLM）。"""
import tempfile
import unittest
from pathlib import Path

from app import database
from app import main, storage
from app.contracts import Block, Locator
from app.markdown_preview import build_preview
from app.claim_inspector import inspect_statements

POS_TEXT = "在自建测试集上，系统对关键句的抽取准确率达到 95%，单份材料的预审装配耗时低于 3 秒。"
TEXT = "中文语料：准确率达到 95%，整体稳定。"


def make_block(block_id: str, text: str, index: int = 1) -> Block:
    return Block(
        id=block_id,
        document_id="mat_x",
        ordinal=index - 1,
        text=text,
        locator=Locator(kind="line", index=index, end_index=None, block_index=1),
    )


class InspectStatementsTest(unittest.TestCase):
    def test_percentage_on_pos_metrics_sentence(self) -> None:
        blocks = [make_block("blk_1", POS_TEXT)]
        found = inspect_statements(blocks)
        percentages = [item for item in found if item.signal == "percentage"]
        self.assertGreaterEqual(len(percentages), 1)
        first = percentages[0]
        self.assertEqual(first.quote, "95%")
        self.assertEqual(POS_TEXT[first.start:first.end], first.quote)
        self.assertEqual(first.line_number, 1)
        self.assertEqual(first.block_id, "blk_1")

    def test_no_digit_practice_sentence_is_silent(self) -> None:
        text = "简述快速排序的基本思想，并分析其平均时间复杂度和最坏时间复杂度。"
        self.assertEqual(inspect_statements([make_block("blk_1", text)]), [])

    def test_comparative_and_absolute_signals(self) -> None:
        comparative = inspect_statements([make_block("blk_1", "本方案优于传统做法，实现更简单。")])
        self.assertTrue(any(item.signal == "comparative" for item in comparative))
        absolute = inspect_statements([make_block("blk_1", "本系统是唯一完全解决该问题的方案。")])
        self.assertTrue(any(item.signal == "absolute" for item in absolute))

    def test_100_percent_prefers_percentage(self) -> None:
        found = inspect_statements([make_block("blk_1", "测试覆盖率 100%，全部通过。")])
        signals = {item.quote: item.signal for item in found}
        self.assertEqual(signals.get("100%"), "percentage")

    def test_number_without_unit_or_context_is_ignored(self) -> None:
        text = "第 3 题：下列关于链表的说法中，正确的是（ ）"
        self.assertEqual(inspect_statements([make_block("blk_1", text)]), [])

    def test_number_with_unit_or_context_is_numeric(self) -> None:
        with_unit = inspect_statements([make_block("blk_1", "平均装配耗时 3 秒，测试集规模为 240 份文档。")])
        self.assertTrue(any(item.signal == "numeric" for item in with_unit))
        with_context = inspect_statements([make_block("blk_1", "系统对关键句的抽取准确率达到 95，单份材料装配很快。")])
        self.assertTrue(any(item.quote == "95" and item.signal == "numeric" for item in with_context))

    def test_cap_20_and_offsets_hold_for_all(self) -> None:
        lines = [f"第 {index} 项指标达到 {index * 10} 秒" for index in range(1, 31)]
        blocks = [make_block(f"blk_{index}", text, index) for index, text in enumerate(lines, start=1)]
        by_id = {item.id: item.text for item in blocks}
        found = inspect_statements(blocks)
        self.assertLessEqual(len(found), 20)
        self.assertTrue(found)
        for item in found:
            text = by_id[item.block_id]
            self.assertEqual(text[item.start:item.end], item.quote)

    def test_code_point_offsets_with_emoji(self) -> None:
        text = "📈 准确率达到 95%，整体稳定。"
        found = inspect_statements([make_block("blk_1", text)])
        self.assertTrue(found)
        for item in found:
            self.assertEqual(text[item.start:item.end], item.quote)


class StatementSignalsApiTest(unittest.TestCase):
    """API 直调 + patch database.connect 到 temp DB，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "signals.db"
        self._original_connect = database.connect
        database.connect = lambda db_path=database.DEFAULT_DB_PATH: self._original_connect(self.db)
        database.init_db()
        self.material = storage.save_material(build_preview("api.md", TEXT.encode("utf-8")))

    def tearDown(self) -> None:
        database.connect = self._original_connect
        self._tmp.cleanup()

    def test_saved_material_returns_signals(self) -> None:
        signals = main.material_statement_signals(self.material.id)
        self.assertTrue(any(item.signal == "percentage" and item.quote == "95%" for item in signals))

    def test_unknown_material_maps_to_404(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.material_statement_signals("mat_missing")
        self.assertEqual(caught.exception.code, "material_not_found")


if __name__ == "__main__":
    unittest.main()
