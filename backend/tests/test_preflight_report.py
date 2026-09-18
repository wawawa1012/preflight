"""Iteration 6：只读装配预审矩阵。不写库、不产生 supported/coverage。"""
import tempfile
import unittest
from pathlib import Path

from app import rubric_store, storage
from app.markdown_preview import build_preview
from app.preflight_report import assemble_report, assemble_summaries
from app.storage import RubricNotBound

TEXT = "中文语料：准确率达到 95%，整体稳定。"
QUOTE = "准确率达到 95%"


def synthetic_rubric():
    from app.contracts import Criterion, Rubric
    return Rubric(
        id="rubric_syn",
        revision=1,
        title="Synthetic rubric (test-only)",
        source_note="test-only",
        criteria=[
            Criterion(id="c_syn_1", title="Criterion A", requirement="requirement A", required_evidence=["x"]),
            Criterion(id="c_syn_2", title="Criterion B", requirement="requirement B", required_evidence=["y"]),
        ],
    )


class AssemblePreflightReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        storage.init_db(self.db)
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric()})
        self.material = storage.save_material(build_preview("ev.md", TEXT.encode("utf-8")), self.db)
        self.block = self.material.blocks[0]
        self.annotation = storage.save_evidence_annotation(self.block.id, QUOTE, db_path=self.db)

    def tearDown(self) -> None:
        rubric_store.reset_index()
        self._tmp.cleanup()

    def test_unbound_raises_rubric_not_bound(self) -> None:
        with self.assertRaises(RubricNotBound):
            assemble_report(self.material.id, db_path=self.db)

    def test_zero_links_is_scope_sentence_not_supported(self) -> None:
        storage.bind_material_rubric(self.material.id, "rubric_syn", 1, self.db)
        report = assemble_report(self.material.id, db_path=self.db)
        self.assertEqual(report.block_count, 1)
        dump = report.model_dump()
        self.assertNotIn("supported", str(dump))
        self.assertNotIn("rubric_coverage", dump)
        for row in report.criteria:
            self.assertEqual(row.status, "no_verified_citations_in_scope")
            self.assertEqual(row.verified_citation_count, 0)
            self.assertIsNotNone(row.missing)
            self.assertEqual(row.missing.searched_block_count, 1)
            self.assertEqual(row.missing.searched_filename, "ev.md")
            self.assertIn("当前范围尚未发现引用", row.missing.explanation)
            self.assertIn("ev.md", row.missing.explanation)
            self.assertIn("1 个 Block", row.missing.explanation)

    def test_link_counts_per_criterion(self) -> None:
        storage.bind_material_rubric(self.material.id, "rubric_syn", 1, self.db)
        storage.create_link(
            material_id=self.material.id,
            annotation_id=self.annotation.id,
            criterion_id="c_syn_1",
            rationale="人工判断相关",
            db_path=self.db,
        )
        report = assemble_report(self.material.id, db_path=self.db)
        by_id = {row.criterion_id: row for row in report.criteria}
        self.assertEqual(by_id["c_syn_1"].status, "has_verified_citations")
        self.assertEqual(by_id["c_syn_1"].verified_citation_count, 1)
        self.assertIsNone(by_id["c_syn_1"].missing)
        self.assertEqual(by_id["c_syn_1"].citations[0].quote, QUOTE)
        self.assertEqual(by_id["c_syn_1"].citations[0].line_number, self.block.locator.index)
        self.assertEqual(by_id["c_syn_1"].citations[0].proposed_by, "human")
        self.assertEqual(by_id["c_syn_2"].status, "no_verified_citations_in_scope")
        self.assertEqual(len(report.blocks), 1)

    def test_summaries_include_unbound(self) -> None:
        rows = assemble_summaries(db_path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].bound)
        self.assertIsNone(rows[0].criteria_total)
        self.assertEqual(rows[0].verified_citation_count, 0)
