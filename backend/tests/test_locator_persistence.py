"""Locator v1：持久化 round-trip、精确 SourceRef occurrence 与下游 locator 兼容。

定向验证：
- 非行 locator 保存→读取不变；line_number/line_count 不伪造（null）；
- 中文及非 BMP 字符的 code-point span；同块第二次 quote 可精确选择并复验；
- 错材料/越界/quote mismatch 被拒绝；非行材料拒绝 editable-source；
- 显式 format/parser_version 由解析层传入 storage（storage 不依赖 parser 常量）。
迁移生命周期测试在 test_migrations.py。
"""
import asyncio
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from app import database, main, storage
from app.contracts import (
    Block,
    EvidenceAnnotationCreate,
    Locator,
    MarkdownPreview,
    SourcePreview,
)
from app.evidence import QuoteNotFound, SpanMismatch, resolve_source_ref, resolve_span
from app.markdown_preview import build_preview


def paragraph_block(index: int, text: str, ordinal: int) -> Block:
    return Block(
        id=f"preview-block-{ordinal}",
        document_id="preview",
        ordinal=ordinal,
        text=text,
        locator=Locator(kind="paragraph", index=index, end_index=None, block_index=1),
    )


def table_cell_block(ordinal: int, text: str) -> Block:
    return Block(
        id=f"preview-block-{ordinal}",
        document_id="preview",
        ordinal=ordinal,
        text=text,
        locator=Locator(
            kind="table_cell",
            index=1,
            end_index=None,
            block_index=1,
            row_index=2,
            cell_index=3,
            paragraph_index=1,
        ),
    )


class LocatorPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "locator.db"
        database.init_db(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _save_docx(self) -> storage.SavedMaterial:
        preview = SourcePreview(
            document_id="preview",
            filename="report.docx",
            format="docx",
            size_bytes=11,
            sha256="c" * 64,
            line_count=None,
            parser_version="b2-source-nodes-v1",
            blocks=[paragraph_block(7, "正文第七段", 0), table_cell_block(1, "表格单元格文本")],
        )
        return storage.save_material(preview, self.db, source_bytes=b"docx-bytes!")

    def test_non_line_locator_round_trip_and_no_fake_lines(self) -> None:
        saved = self._save_docx()
        loaded = storage.get_material(saved.id, self.db)

        self.assertEqual(loaded.format, "docx")
        self.assertEqual(loaded.parser_version, "b2-source-nodes-v1")
        self.assertIsNone(loaded.line_count)
        self.assertEqual(loaded.model_dump(), saved.model_dump())
        paragraph, cell = loaded.blocks
        self.assertEqual((paragraph.locator.kind, paragraph.locator.index), ("paragraph", 7))
        self.assertEqual(
            (cell.locator.kind, cell.locator.index, cell.locator.row_index, cell.locator.cell_index,
             cell.locator.paragraph_index),
            ("table_cell", 1, 2, 3, 1),
        )
        summary = storage.list_materials(self.db)[0]
        self.assertEqual(summary.format, "docx")
        self.assertEqual(storage.get_source_bytes(saved.id, self.db), b"docx-bytes!")

    def test_non_line_material_rejects_editable_source(self) -> None:
        saved = self._save_docx()
        with self.assertRaises(storage.FormatNotEditable) as caught:
            storage.get_editable_source(saved.id, self.db)
        self.assertEqual(caught.exception.code, "format_not_editable")
        self.assertEqual(storage.get_editable_source("mat_missing", self.db), None)

    def test_line_material_keeps_real_lines_and_legacy_wire_values(self) -> None:
        preview: MarkdownPreview = build_preview("line.md", "甲\n\n乙\n".encode("utf-8"))
        # legacy MarkdownPreview 不带 format/parser_version：由解析层明确传入，storage 不猜 parser 常量。
        saved = storage.save_material(
            preview,
            self.db,
            source_bytes="甲\n\n乙\n".encode("utf-8"),
            fmt="md",
            parser_version="line-v1",
        )
        self.assertEqual(saved.format, "md")
        self.assertEqual(saved.parser_version, "line-v1")
        self.assertEqual(saved.line_count, 3)
        self.assertEqual([block.locator.index for block in saved.blocks], [1, 3])
        self.assertEqual(storage.get_editable_source(saved.id, self.db).text, "甲\n\n乙")
        # 旧 Markdown 入口 wire 值保持不变
        self.assertEqual(preview.line_count, 3)
        self.assertEqual([block.locator.kind for block in preview.blocks], ["line", "line"])


class DownstreamLocatorTest(unittest.TestCase):
    """非行来源通过下游路径时不得展示为行；位置由 locator 承载。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "downstream.db"
        database.init_db(self.db)
        preview = SourcePreview(
            document_id="preview",
            filename="report.docx",
            format="docx",
            size_bytes=8,
            sha256="e" * 64,
            line_count=None,
            parser_version="b2-source-nodes-v1",
            blocks=[
                paragraph_block(1, "准确率达到 95%。", 0),
                paragraph_block(2, "复现实验的准确率达到 90%。", 1),
            ],
        )
        self.material = storage.save_material(preview, self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_statements_citations_and_grill_sources_carry_locator(self) -> None:
        from app import grill, llm
        from app.claim_inspector import inspect_statements
        from app.consistency import find_numeric_findings
        from app.contracts import Criterion

        statements = inspect_statements(self.material.blocks)
        self.assertTrue(statements)
        self.assertEqual([item.line_number for item in statements], [None, None])
        self.assertEqual([item.locator.kind for item in statements], ["paragraph", "paragraph"])

        findings = find_numeric_findings(statements, self.material.blocks)
        self.assertEqual(len(findings), 1)
        citation = findings[0].citations[0]
        self.assertIsNone(citation.line_number)
        self.assertEqual((citation.locator.kind, citation.locator.index), ("paragraph", 1))

        sources = grill.prepare_sources(findings, statements, self.material.blocks)
        self.assertTrue(sources)
        self.assertTrue(all(source.line_number is None for source in sources))
        self.assertTrue(all(source.locator.kind == "paragraph" for source in sources))

        criterion = Criterion(
            id="c_docx",
            title="DOCX 段落依据",
            requirement="requirement",
            required_evidence=["x"],
        )
        user = llm.build_messages(criterion, self.material.blocks)[1]["content"]
        self.assertIn("paragraph 1", user)
        self.assertNotIn("line 1", user)


class SourceRefOccurrenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "source-ref.db"
        database.init_db(self.db)
        self.material = storage.save_material(
            build_preview("repeat.md", "重复片段出现重复片段\n".encode("utf-8")), self.db
        )
        self.block = self.material.blocks[0]
        self.text = self.block.text

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quote_only_keeps_first_occurrence_compat(self) -> None:
        annotation = storage.save_evidence_annotation(self.block.id, "重复片段", db_path=self.db)
        self.assertEqual((annotation.source.start, annotation.source.end), (0, 4))

    def test_explicit_span_can_select_second_occurrence(self) -> None:
        annotation = storage.save_evidence_annotation(
            self.block.id, "重复片段", db_path=self.db, start=6, end=10
        )
        self.assertEqual((annotation.source.start, annotation.source.end), (6, 10))
        self.assertEqual(self.text[annotation.source.start:annotation.source.end], "重复片段")
        loaded = storage.get_evidence_annotation(annotation.id, self.db)
        self.assertEqual((loaded.source.start, loaded.source.end), (6, 10))

    def test_explicit_span_mismatch_is_rejected_not_fell_back(self) -> None:
        with self.assertRaises(SpanMismatch):
            storage.save_evidence_annotation(self.block.id, "重复片段", db_path=self.db, start=1, end=5)
        with self.assertRaises(SpanMismatch):
            storage.save_evidence_annotation(self.block.id, "出现", db_path=self.db, start=0, end=4)
        with self.assertRaises(SpanMismatch):
            storage.save_evidence_annotation(self.block.id, "重复片段", db_path=self.db, start=0, end=999)
        with self.assertRaises(SpanMismatch):
            storage.save_evidence_annotation(self.block.id, "重复片段", db_path=self.db, start=6)
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence_annotations").fetchone()[0], 0)

    def test_non_bmp_and_chinese_code_point_spans(self) -> None:
        material = storage.save_material(
            build_preview("emoji.md", "🧪🧪准确率 95% 🚀\n".encode("utf-8")), self.db
        )
        block = material.blocks[0]
        # 每个 emoji 是一个 code point；start/end 不是 UTF-16 索引。
        annotation = storage.save_evidence_annotation(block.id, "准确率 95%", db_path=self.db, start=2, end=9)
        self.assertEqual(block.text[2:9], "准确率 95%")
        self.assertEqual((annotation.source.start, annotation.source.end), (2, 9))
        emoji = storage.save_evidence_annotation(block.id, "🚀", db_path=self.db, start=10, end=11)
        self.assertEqual(block.text[10:11], "🚀")

    def test_explicit_material_ownership_is_enforced(self) -> None:
        other = storage.save_material(build_preview("other.md", "别的材料\n".encode("utf-8")), self.db)
        # 不声明 material_id：服务端从 block 派生，永远指向真实归属。
        annotation = storage.save_evidence_annotation(other.blocks[0].id, "别的材料", db_path=self.db)
        self.assertEqual(annotation.material_id, other.id)
        # 显式声明错误材料：拒绝，不落行。
        with self.assertRaises(storage.MaterialMismatch) as caught:
            storage.save_evidence_annotation(
                self.block.id, "重复片段", db_path=self.db, material_id="mat_other"
            )
        self.assertEqual(caught.exception.code, "material_mismatch")
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence_annotations").fetchone()[0], 1)
        self.assertIsNone(storage.save_evidence_annotation("blk_missing", "任意", db_path=self.db))

    def test_unified_resolver_contract(self) -> None:
        self.assertEqual(resolve_span(self.text, "重复片段"), (0, 4))
        self.assertEqual(resolve_source_ref(self.text, "重复片段", 6, 10), (6, 10))
        with self.assertRaises(QuoteNotFound):
            resolve_source_ref(self.text, "不存在")
        with self.assertRaises(SpanMismatch):
            resolve_source_ref(self.text, "重复片段", 6, 9)


class LocatorApiTest(unittest.TestCase):
    """API 直调层：patch database.connect 到 temp DB。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "locator-api.db"
        self._original_connect = database.connect
        database.connect = lambda db_path=database.DEFAULT_DB_PATH: self._original_connect(self.db)
        database.init_db()
        self.parent = storage.save_material(
            build_preview("repeat.md", "重复片段出现重复片段\n".encode("utf-8"))
        )
        self.block = self.parent.blocks[0]

    def tearDown(self) -> None:
        database.connect = self._original_connect
        self._tmp.cleanup()

    def test_api_explicit_span_round_trip_and_mismatch(self) -> None:
        annotation = main.create_evidence_annotation(
            EvidenceAnnotationCreate(block_id=self.block.id, quote="重复片段", start=6, end=10)
        )
        self.assertEqual((annotation.source.start, annotation.source.end), (6, 10))
        with self.assertRaises(storage.SpanMismatch):
            main.create_evidence_annotation(
                EvidenceAnnotationCreate(block_id=self.block.id, quote="重复片段", start=0, end=3)
            )

    def test_api_incomplete_span_pair_is_validation_error(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceAnnotationCreate(block_id=self.block.id, quote="重复片段", start=6)

    def test_api_explicit_material_mismatch_is_rejected(self) -> None:
        annotation = main.create_evidence_annotation(
            EvidenceAnnotationCreate(
                block_id=self.block.id, quote="重复片段", material_id=self.parent.id
            )
        )
        self.assertEqual(annotation.material_id, self.parent.id)
        with self.assertRaises(storage.MaterialMismatch):
            main.create_evidence_annotation(
                EvidenceAnnotationCreate(
                    block_id=self.block.id, quote="重复片段", material_id="mat_other"
                )
            )

    def test_api_docx_editable_source_and_revision_are_rejected(self) -> None:
        preview = SourcePreview(
            document_id="preview",
            filename="report.docx",
            format="docx",
            size_bytes=4,
            sha256="d" * 64,
            line_count=None,
            parser_version="b2-source-nodes-v1",
            blocks=[paragraph_block(1, "DOCX 正文", 0)],
        )
        docx_material = storage.save_material(preview, source_bytes=b"docx")
        with self.assertRaises(storage.FormatNotEditable):
            main.material_editable_source(docx_material.id)
        with self.assertRaises(storage.FormatNotEditable):
            main.create_material_revision(
                docx_material.id, main.MaterialRevisionCreate(text="新文本", filename="new.md")
            )

    def test_api_txt_preview_and_save_are_line_based(self) -> None:
        raw = "第一行\n\n第三行\n".encode("utf-8")
        uploaded = mock.Mock()
        uploaded.filename = "notes.txt"
        uploaded.read = mock.AsyncMock(return_value=raw)

        async def close() -> None:
            return None

        uploaded.close = mock.AsyncMock(side_effect=close)
        preview = asyncio.run(main.preview_source(uploaded))
        self.assertEqual(preview.format, "txt")
        self.assertEqual(preview.line_count, 3)
        self.assertEqual([block.locator.index for block in preview.blocks], [1, 3])
        self.assertEqual([block.locator.kind for block in preview.blocks], ["line", "line"])


if __name__ == "__main__":
    unittest.main()
