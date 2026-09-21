"""通用来源解析边界：md/txt 行语义、B2 SourceNode 转换、DOCX 未集成拒绝与 mock 接入。

定向验证：
- TXT 真实逐行定位，空行计入 line_count 但不生成 Block；
- 旧 Markdown 预览入口与通用预览对 md 给出一致的 Block/line locator；
- 无 B2 adapter 时 DOCX 明确 parser_unavailable，不伪造 Block；
- 注入 B2 纯 SourceNode（paragraph/table_cell）后转换出正确公共 Locator 与 0 起连续 ordinal；
- TXT revision loop 保留空行、原文件字节入库；
- SourceNode 位置形式不合法时拒绝整份解析。
"""
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app import main, storage
from app.contracts import MaterialRevisionCreate
from app.markdown_preview import build_preview
from app.source_ingest import (
    PARSER_VERSION_LINE,
    ParserUnavailable,
    SourceNode,
    blocks_from_nodes,
    build_source_preview,
    detect_format,
    line_nodes,
    locator_from_node,
)
from app.markdown_preview import PreviewRejected


class LineNodeTest(unittest.TestCase):
    def test_txt_lines_are_real_and_blank_lines_counted(self) -> None:
        nodes = line_nodes("第一行\n\n第三行\n")
        self.assertEqual([(node.line, node.text) for node in nodes], [(1, "第一行"), (3, "第三行")])
        self.assertEqual([node.body_ordinal for node in nodes], [0, 1])

    def test_space_only_line_is_not_blank(self) -> None:
        nodes = line_nodes("甲\n   \n乙")
        self.assertEqual([node.line for node in nodes], [1, 2, 3])

    def test_txt_preview_has_no_fake_lines_and_real_line_count(self) -> None:
        preview = build_source_preview("notes.txt", "甲\n\n乙\n".encode("utf-8"))
        self.assertEqual(preview.format, "txt")
        self.assertEqual(preview.line_count, 3)
        self.assertEqual(preview.sha256, hashlib.sha256("甲\n\n乙\n".encode("utf-8")).hexdigest())
        self.assertEqual([block.locator.index for block in preview.blocks], [1, 3])
        self.assertEqual([block.locator.kind for block in preview.blocks], ["line", "line"])
        self.assertEqual([block.ordinal for block in preview.blocks], [0, 1])

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

    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            detect_format("a.pdf")
        self.assertEqual(caught.exception.code, "invalid_extension")


class SourceNodeConversionTest(unittest.TestCase):
    def test_paragraph_and_table_cell_become_public_locators(self) -> None:
        nodes = [
            SourceNode(text="正文一", body_ordinal=0, paragraph=1),
            SourceNode(text="单元格", body_ordinal=1, table=2, row=3, cell=4, cell_paragraph=5),
        ]
        blocks = blocks_from_nodes(nodes)
        self.assertEqual([block.ordinal for block in blocks], [0, 1])
        paragraph, cell = blocks
        self.assertEqual((paragraph.locator.kind, paragraph.locator.index), ("paragraph", 1))
        self.assertEqual(
            (cell.locator.kind, cell.locator.index, cell.locator.row_index, cell.locator.cell_index,
             cell.locator.paragraph_index, cell.locator.block_index),
            ("table_cell", 2, 3, 4, 5, 1),
        )

    def test_nodes_are_ordered_by_body_ordinal_and_ordinal_is_contiguous(self) -> None:
        nodes = [
            SourceNode(text="后", body_ordinal=9, paragraph=2),
            SourceNode(text="前", body_ordinal=4, paragraph=1),
        ]
        blocks = blocks_from_nodes(nodes)
        self.assertEqual([block.text for block in blocks], ["前", "后"])
        self.assertEqual([block.ordinal for block in blocks], [0, 1])

    def test_empty_text_nodes_are_skipped_like_markdown_blank_lines(self) -> None:
        blocks = blocks_from_nodes(
            [SourceNode(text="", body_ordinal=0, paragraph=1), SourceNode(text="有", body_ordinal=1, paragraph=2)]
        )
        self.assertEqual([block.text for block in blocks], ["有"])
        self.assertEqual([block.locator.index for block in blocks], [2])

    def test_ambiguous_or_missing_position_is_rejected(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            locator_from_node(SourceNode(text="x", body_ordinal=0, line=1, paragraph=1))
        self.assertEqual(caught.exception.code, "invalid_source_node")
        with self.assertRaises(PreviewRejected):
            locator_from_node(SourceNode(text="x", body_ordinal=0, table=1, row=1))  # 缺 cell/paragraph
        with self.assertRaises(PreviewRejected):
            locator_from_node(SourceNode(text="x", body_ordinal=0))
        with self.assertRaises(PreviewRejected):
            blocks_from_nodes(
                [SourceNode(text="a", body_ordinal=0, paragraph=1), SourceNode(text="b", body_ordinal=0, paragraph=2)]
            )


class DocxAdapterBoundaryTest(unittest.TestCase):
    def test_docx_without_b2_adapter_is_explicitly_unavailable(self) -> None:
        with self.assertRaises(ParserUnavailable) as caught:
            build_source_preview("report.docx", b"fake-docx")
        self.assertEqual(caught.exception.code, "parser_unavailable")

    def test_docx_uses_b2_source_nodes_when_present(self) -> None:
        module = types.ModuleType("app.source_adapters")

        def read_source_nodes(filename: str, data: bytes):
            self.assertEqual(filename, "report.docx")
            self.assertEqual(data, b"fake-docx")
            return [
                SourceNode(text="正文一", body_ordinal=0, paragraph=1),
                SourceNode(text="表格内文字", body_ordinal=1, table=1, row=1, cell=2, cell_paragraph=1),
            ]

        module.read_source_nodes = read_source_nodes
        module.PARSER_VERSION = "b2-test-v9"
        with mock.patch.dict(sys.modules, {"app.source_adapters": module}):
            preview = build_source_preview("report.docx", b"fake-docx")
        self.assertEqual(preview.format, "docx")
        self.assertIsNone(preview.line_count)
        self.assertEqual(preview.parser_version, "b2-test-v9")
        kinds = [block.locator.kind for block in preview.blocks]
        self.assertEqual(kinds, ["paragraph", "table_cell"])

    def test_docx_adapter_without_interface_is_rejected(self) -> None:
        module = types.ModuleType("app.source_adapters")
        with mock.patch.dict(sys.modules, {"app.source_adapters": module}):
            with self.assertRaises(ParserUnavailable):
                build_source_preview("report.docx", b"fake-docx")


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
        self.assertEqual(created.material.line_count, 6)
        self.assertEqual([block.locator.index for block in created.material.blocks], [1, 3, 6])
        source = main.material_editable_source(created.material.id)
        self.assertEqual(source.format, "txt")
        self.assertEqual(source.text, child_text)
        self.assertEqual(
            storage.get_source_bytes(created.material.id), child_text.encode("utf-8")
        )
        # 父材料不可变
        self.assertEqual(main.material_editable_source(self.parent.id).text, "第一行\n\n第三行")

    def test_docx_extension_revision_is_rejected(self) -> None:
        with self.assertRaises(storage.FormatNotEditable):
            main.create_material_revision(
                self.parent.id, MaterialRevisionCreate(text="内容", filename="draft.docx")
            )


if __name__ == "__main__":
    unittest.main()
