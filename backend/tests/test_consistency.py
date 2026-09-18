"""I8 同材料数值一致性：从 I7 关键陈述派生「待核对问题」。

TDD：本文件先写、先红，再实现 app/consistency.py。
判定纪律（宁漏勿错）：同一度量词 + 同一单位 + 不同数值才标 numeric_inconsistency；
度量缺失或单位不一致降级为 needs_review；其余不报。
"""
import tempfile
import unittest
from pathlib import Path

from app import main, storage
from app.claim_inspector import inspect_statements
from app.consistency import find_numeric_findings
from app.contracts import DetectedStatement
from app.markdown_preview import build_preview


def blocks_of(text: str):
    preview = build_preview("ev.md", text.encode("utf-8"))
    blocks = list(preview.blocks)
    # 预览 Block id 与持久化无关；一致性检测只要求 block_id 能在 blocks 里找到。
    return [
        block.model_copy(update={"id": f"blk_{index}"}) for index, block in enumerate(blocks)
    ]


def statements_of(text: str):
    blocks = blocks_of(text)
    return blocks, inspect_statements(blocks)


class FindNumericFindingsTest(unittest.TestCase):
    """纯函数层：零 IO、零数据库。"""

    def test_same_measure_different_values_is_numeric_inconsistency(self) -> None:
        blocks, statements = statements_of("本文系统准确率达到 95%。\n\n复现实验的准确率达到 90%。\n")
        findings = find_numeric_findings(statements, blocks)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.kind, "numeric_inconsistency")
        self.assertEqual(finding.measure, "准确率")
        self.assertEqual(finding.values, ["95%", "90%"])
        self.assertEqual(len(finding.citations), 2)
        self.assertEqual([item.line_number for item in finding.citations], [1, 3])
        self.assertEqual([item.quote for item in finding.citations], ["95%", "90%"])
        self.assertEqual(finding.searched_block_count, 2)
        self.assertEqual(finding.searched_statement_count, len(statements))
        self.assertIn("准确率", finding.explanation)
        self.assertIn("95%", finding.explanation)

    def test_same_measure_same_value_is_not_reported(self) -> None:
        blocks, statements = statements_of("准确率达到 95%。\n\n准确率为 95%。\n")
        self.assertEqual(find_numeric_findings(statements, blocks), [])

    def test_different_measures_are_not_paired(self) -> None:
        blocks, statements = statements_of("准确率达到 95%。\n\n召回率达到 90%。\n")
        self.assertEqual(find_numeric_findings(statements, blocks), [])

    def test_single_statement_is_not_reported(self) -> None:
        blocks, statements = statements_of("准确率达到 95%。\n")
        self.assertEqual(find_numeric_findings(statements, blocks), [])

    def test_measureless_same_unit_downgrades_to_needs_review(self) -> None:
        blocks, statements = statements_of("达到 95%。\n\n达到 90%。\n")
        findings = find_numeric_findings(statements, blocks)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "needs_review")
        self.assertEqual(findings[0].measure, "")
        self.assertEqual(findings[0].values, ["95%", "90%"])
        self.assertIn("人工判断", findings[0].explanation)

    def test_measureless_different_units_are_not_reported(self) -> None:
        blocks, statements = statements_of("达到 95%。\n\n达到 90 毫秒。\n")
        self.assertEqual(find_numeric_findings(statements, blocks), [])

    def test_same_measure_different_units_downgrades_to_needs_review(self) -> None:
        blocks, statements = statements_of("准确率达到 95%。\n\n准确率为 0.95。\n")
        findings = find_numeric_findings(statements, blocks)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "needs_review")
        self.assertEqual(findings[0].measure, "准确率")
        self.assertIn("单位", findings[0].explanation)

    def test_absolute_statement_without_number_is_ignored(self) -> None:
        blocks, statements = statements_of("本方案首创该方法。\n\n本方案唯一可行。\n")
        self.assertEqual(find_numeric_findings(statements, blocks), [])

    def test_statement_span_is_reverified_against_block_text(self) -> None:
        blocks, statements = statements_of("准确率达到 95%。\n\n准确率达到 90%。\n")
        tampered = [
            DetectedStatement(
                block_id=statements[0].block_id,
                line_number=statements[0].line_number,
                quote="准确率达到 95%",
                start=statements[0].start,
                end=statements[0].end,
                signal=statements[0].signal,
            ),
            *statements[1:],
        ]
        # 篡改的 quote 与原文区间不符：宁漏勿错，直接跳过，不产生任何 Finding。
        self.assertEqual(find_numeric_findings(tampered, blocks), [])

    def test_findings_are_ordered_by_first_occurrence(self) -> None:
        text = "准确率达到 95%。\n\n吞吐量达到 10 次。\n\n准确率降低到 90%。\n\n吞吐量达到 20 次。\n"
        blocks, statements = statements_of(text)
        findings = find_numeric_findings(statements, blocks)
        self.assertEqual([item.measure for item in findings], ["准确率", "吞吐量"])
        self.assertEqual([item.citations[0].line_number for item in findings], [1, 3])

    def test_duplicate_occurrences_keep_every_citation(self) -> None:
        blocks, statements = statements_of("准确率达到 95%。\n\n准确率达到 90%。\n\n准确率达到 90%。\n")
        findings = find_numeric_findings(statements, blocks)
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(findings[0].citations), 3)
        self.assertEqual(findings[0].values, ["95%", "90%"])

    def test_no_statements_no_findings(self) -> None:
        blocks, _statements = statements_of("只有一段没有任何数字的普通文字。\n")
        self.assertEqual(find_numeric_findings([], blocks), [])


class ConsistencyApiTest(unittest.TestCase):
    """API 直调 + patch storage.connect 到 temp DB，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "api.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()

    def tearDown(self) -> None:
        storage.connect = self._original_connect
        self._tmp.cleanup()

    def test_unknown_material_maps_to_404(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.material_consistency_findings("mat_missing")
        self.assertEqual(caught.exception.code, "material_not_found")

    def test_material_without_inconsistency_returns_empty_list(self) -> None:
        storage.save_material(build_preview("clean.md", "准确率达到 95%。\n".encode("utf-8")))
        self.assertEqual(main.material_consistency_findings(storage.list_materials()[0].id), [])

    def test_material_with_inconsistency_returns_finding(self) -> None:
        saved = storage.save_material(
            build_preview("ev.md", "准确率达到 95%。\n\n准确率达到 90%。\n".encode("utf-8"))
        )
        findings = main.material_consistency_findings(saved.id)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].material_id, saved.id)
        self.assertEqual(findings[0].kind, "numeric_inconsistency")
        self.assertEqual(findings[0].citations[0].block_id, saved.blocks[0].id)


if __name__ == "__main__":
    unittest.main()
