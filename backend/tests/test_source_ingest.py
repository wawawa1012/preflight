"""通用来源解析边界：消费 B2 txt/docx parser 的集成测试。

定向验证：
- TXT/DOCX preview 均走 B2 parser 并转换成公共 Block/Locator；
- body_ordinal 零基连续直接成为 Block.ordinal，结构坐标原样保留；
- 非行来源 line_count=null（TXT 给真实行数）；`/preview/markdown` 与 md 行语义不变；
- parser 拒绝（合并单元格/嵌套表格/内容控件/文本框/坏 ZIP/坏 XML）原码透出为 400；
- DOCX 保存 → 读取 → Evidence annotation/link 全链在同一材料上可用；
- TXT revision loop 保留空行、原文件字节入库。
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import main, storage
from app.contracts import MaterialRevisionCreate, SourcePreview
from app.markdown_preview import PreviewRejected, build_preview
from app.source_adapters import SourceNode
from app.source_ingest import (
    PARSER_VERSION_LINE,
    blocks_from_nodes,
    build_source_preview,
    detect_format,
    locator_from_node,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "source_adapters"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class GenericPreviewTest(unittest.TestCase):
    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            detect_format("a.pdf")
        self.assertEqual(caught.exception.code, "invalid_extension")

    def test_markdown_generic_preview_matches_legacy_entry(self) -> None:
        raw = "甲\n\n乙\n".encode("utf-8")
        legacy = build_preview("m.md", raw)
        generic = build_source_preview("m.md", raw)
        self.assertEqual(generic.format, "md")
        self.assertEqual(generic.parser_version, PARSER_VERSION_LINE)
        self.assertEqual(generic.line_count, legacy.line_count)
        self.assertEqual(
            [block.model_dump() for block in generic.blocks],
            [block.model_dump() for block in legacy.blocks],
        )

    def test_txt_preview_uses_b2_parser_with_real_lines(self) -> None:
        raw = fixture("txt_lines_bom_crlf_cn.txt")
        preview = build_source_preview("notes.txt", raw)
        self.assertEqual(preview.format, "txt")
        self.assertEqual(preview.parser_version, "txt/1")
        self.assertEqual(preview.line_count, 4)  # 空行计入行数
        self.assertEqual([block.text for block in preview.blocks], ["标题行", "   ", "第三行\t带tab"])
        self.assertEqual([block.locator.kind for block in preview.blocks], ["line", "line", "line"])
        self.assertEqual([block.locator.index for block in preview.blocks], [1, 3, 4])
        self.assertEqual([block.ordinal for block in preview.blocks], [0, 1, 2])
        self.assertEqual(preview.sha256, hashlib.sha256(raw).hexdigest())

    def test_txt_via_boundary_keeps_markdown_line_semantics(self) -> None:
        payloads = ["标题\n\n  缩进行  \r\n最后一行\r\n", "甲\n \n乙", "", "\n\n", "没有末尾换行"]
        for payload in payloads:
            with self.subTest(payload=payload):
                data = payload.encode("utf-8")
                generic = build_source_preview("x.txt", data)
                legacy = build_preview("x.md", data)
                self.assertEqual(generic.line_count, legacy.line_count)
                self.assertEqual(
                    [(block.text, block.locator.index) for block in generic.blocks],
                    [(block.text, block.locator.index) for block in legacy.blocks],
                )

    def test_non_bmp_span_indices_stay_code_points(self) -> None:
        preview = build_source_preview("emoji.txt", "🧪🧪准确率 95% 🚀\n".encode("utf-8"))
        block = preview.blocks[0]
        self.assertEqual(block.text[2:9], "准确率 95%")
        self.assertEqual(block.locator.index, 1)


class SourceNodeConversionTest(unittest.TestCase):
    def test_paragraph_and_table_cell_become_public_locators(self) -> None:
        blocks = blocks_from_nodes(
            [
                SourceNode(kind="paragraph", text="正文一", body_ordinal=0, paragraph_index=1),
                SourceNode(
                    kind="table_cell",
                    text="单元格",
                    body_ordinal=1,
                    table_index=2,
                    row_index=3,
                    cell_index=4,
                    cell_paragraph_index=5,
                ),
            ]
        )
        self.assertEqual([block.ordinal for block in blocks], [0, 1])
        paragraph, cell = blocks
        self.assertEqual((paragraph.locator.kind, paragraph.locator.index), ("paragraph", 1))
        self.assertEqual(
            (cell.locator.kind, cell.locator.index, cell.locator.row_index, cell.locator.cell_index,
             cell.locator.paragraph_index, cell.locator.block_index),
            ("table_cell", 2, 3, 4, 5, 1),
        )

    def test_body_ordinal_must_be_consecutive_and_zero_based(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            blocks_from_nodes(
                [
                    SourceNode(kind="paragraph", text="一", body_ordinal=0, paragraph_index=1),
                    SourceNode(kind="paragraph", text="二", body_ordinal=2, paragraph_index=2),
                ]
            )
        self.assertEqual(caught.exception.code, "invalid_source_node")

    def test_empty_text_node_is_rejected_not_silently_skipped(self) -> None:
        with self.assertRaises(PreviewRejected):
            blocks_from_nodes([SourceNode(kind="paragraph", text="", body_ordinal=0, paragraph_index=1)])

    def test_kind_specific_coordinates_are_required(self) -> None:
        with self.assertRaises(PreviewRejected):
            locator_from_node(SourceNode(kind="line", text="x", body_ordinal=0))
        with self.assertRaises(PreviewRejected):
            locator_from_node(SourceNode(kind="paragraph", text="x", body_ordinal=0))
        with self.assertRaises(PreviewRejected):
            locator_from_node(
                SourceNode(kind="table_cell", text="x", body_ordinal=0, table_index=1, row_index=1)
            )
        with self.assertRaises(PreviewRejected):
            locator_from_node(SourceNode(kind="sentence", text="x", body_ordinal=0))  # type: ignore[arg-type]


class DocxPipelineTest(unittest.TestCase):
    def test_docx_preview_keeps_parser_positions(self) -> None:
        preview = build_source_preview("report.docx", fixture("docx_body_table_body.docx"))
        self.assertEqual(preview.format, "docx")
        self.assertEqual(preview.parser_version, "docx/1")
        self.assertIsNone(preview.line_count)
        self.assertEqual([block.ordinal for block in preview.blocks], [0, 1, 2, 3, 4])
        self.assertEqual(
            [(block.text, block.locator.kind) for block in preview.blocks],
            [
                ("正文第一段", "paragraph"),
                ("甲组数据", "table_cell"),
                ("重复项", "table_cell"),
                ("乙组数据", "table_cell"),
                ("结语段落", "paragraph"),
            ],
        )
        first, cell, _, _, last = preview.blocks
        self.assertEqual((first.locator.kind, first.locator.index), ("paragraph", 1))
        self.assertEqual(
            (cell.locator.index, cell.locator.row_index, cell.locator.cell_index, cell.locator.paragraph_index),
            (1, 1, 1, 1),
        )
        self.assertEqual((last.locator.kind, last.locator.index), ("paragraph", 2))

    def test_docx_rejections_keep_parser_error_codes(self) -> None:
        cases = {
            "reject_merged_cells.docx": "unsupported_structure",
            "reject_nested_table.docx": "unsupported_structure",
            "reject_content_control.docx": "unsupported_structure",
            "reject_text_box.docx": "unsupported_structure",
            "reject_broken_zip.docx": "invalid_zip",
            "reject_bad_xml.docx": "invalid_xml",
            "reject_missing_document.docx": "invalid_docx",
        }
        for name, code in cases.items():
            with self.subTest(fixture=name):
                with self.assertRaises(PreviewRejected) as caught:
                    build_source_preview("bad.docx", fixture(name))
                self.assertEqual(caught.exception.code, code)


class DocxEvidencePlumbingTest(unittest.TestCase):
    """DOCX 保存 → 读取 → annotation → link：Evidence source 全链都在同一材料上。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "docx-plumbing.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()
        self.preview = build_source_preview("report.docx", fixture("docx_body_table_body.docx"))
        self.material = storage.save_material(
            self.preview, source_bytes=fixture("docx_body_table_body.docx")
        )

    def tearDown(self) -> None:
        storage.connect = self._original_connect
        self._tmp.cleanup()

    def test_save_round_trip_and_source_bytes(self) -> None:
        loaded = storage.get_material(self.material.id)
        self.assertEqual(loaded.model_dump(), self.material.model_dump())
        self.assertEqual(loaded.format, "docx")
        self.assertEqual(loaded.parser_version, "docx/1")
        self.assertIsNone(loaded.line_count)
        self.assertEqual(
            storage.get_source_bytes(self.material.id), fixture("docx_body_table_body.docx")
        )

    def test_docx_evidence_annotation_and_link(self) -> None:
        cell_block = next(block for block in self.material.blocks if block.locator.kind == "table_cell")
        annotation = storage.save_evidence_annotation(
            cell_block.id, "甲组数据", db_path=self.db, material_id=self.material.id
        )
        self.assertEqual(annotation.material_id, self.material.id)
        self.assertEqual(annotation.block_id, cell_block.id)
        self.assertEqual((annotation.source.start, annotation.source.end), (0, 4))

        storage.bind_material_rubric(self.material.id, "rubric_syn", 1, self.db)
        link = storage.create_link(
            self.material.id, annotation.id, "c_syn_1", "DOCX 表格单元格作为依据", db_path=self.db
        )
        self.assertEqual(link.annotation_id, annotation.id)

    def test_second_occurrence_span_inside_docx_block(self) -> None:
        # 单元格 fixture 的每块只含一次文本；显式 span 仍必须逐字命中。
        cell_block = next(block for block in self.material.blocks if block.locator.kind == "table_cell")
        with self.assertRaises(storage.SpanMismatch):
            storage.save_evidence_annotation(
                cell_block.id, "甲组数据", db_path=self.db, start=1, end=5
            )

    def test_docx_editable_source_and_revision_are_rejected(self) -> None:
        with self.assertRaises(storage.FormatNotEditable):
            main.material_editable_source(self.material.id)
        with self.assertRaises(storage.FormatNotEditable):
            main.create_material_revision(
                self.material.id, MaterialRevisionCreate(text="新文本", filename="new.md")
            )


class TxtRevisionLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "txt-revision.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()
        parent_bytes = "第一行\n\n第三行\n".encode("utf-8")
        self.parent = storage.save_material(
            build_source_preview("draft.txt", parent_bytes), source_bytes=parent_bytes
        )

    def tearDown(self) -> None:
        storage.connect = self._original_connect
        self._tmp.cleanup()

    def test_txt_revision_preserves_blank_lines_and_format(self) -> None:
        child_text = "第一行\n\n第三行（改）\n\n\n第六行"
        created = main.create_material_revision(
            self.parent.id,
            MaterialRevisionCreate(text=child_text, filename="draft-v2.txt"),
        )
        self.assertEqual(created.material.format, "txt")
        self.assertEqual(created.material.parser_version, "txt/1")
        self.assertEqual(created.material.line_count, 6)
        self.assertEqual([block.locator.index for block in created.material.blocks], [1, 3, 6])
        source = main.material_editable_source(created.material.id)
        self.assertEqual(source.format, "txt")
        self.assertEqual(source.text, child_text)
        self.assertEqual(storage.get_source_bytes(created.material.id), child_text.encode("utf-8"))
        self.assertEqual(main.material_editable_source(self.parent.id).text, "第一行\n\n第三行")

    def test_docx_extension_revision_is_rejected(self) -> None:
        with self.assertRaises(storage.FormatNotEditable):
            main.create_material_revision(
                self.parent.id, MaterialRevisionCreate(text="内容", filename="draft.docx")
            )

    def test_txt_save_keeps_preview_and_source_bytes_consistent(self) -> None:
        self.assertEqual(self.parent.sha256, hashlib.sha256("第一行\n\n第三行\n".encode("utf-8")).hexdigest())
        self.assertEqual(self.parent.parser_version, "txt/1")
        self.assertEqual(self.parent.line_count, 3)


if __name__ == "__main__":
    unittest.main()
