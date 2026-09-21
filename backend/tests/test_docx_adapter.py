"""DOCX 解析器纯函数测试：fixtures 全部为合成 WordprocessingML，不含用户材料。"""
import io
from pathlib import Path
import unittest
import warnings
import zipfile
from unittest import mock

from app import docx_adapter
from app.docx_adapter import parse_docx
from app.source_adapters import SourceNode, SourceParseError

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "source_adapters"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def document(*body_children: str) -> str:
    return (
        f'<w:document xmlns:w="{W_NS}" xmlns:wp="{WP_NS}" xmlns:a="{A_NS}">'
        "<w:body>" + "".join(body_children) + "<w:sectPr/></w:body></w:document>"
    )


def paragraph(*runs: str, style: str | None = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}{''.join(runs)}</w:p>"


def run(*items: str) -> str:
    return "<w:r>" + "".join(items) + "</w:r>"


def text(value: str) -> str:
    return f'<w:t xml:space="preserve">{value}</w:t>'


def cell(*blocks: str, properties: str = "") -> str:
    return f"<w:tc>{properties}" + "".join(blocks) + "</w:tc>"


def row(*cells: str) -> str:
    return "<w:tr>" + "".join(cells) + "</w:tr>"


def table(*rows: str) -> str:
    return "<w:tbl>" + "".join(rows) + "</w:tbl>"


def build_docx(document_xml: str, extra_parts: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        for name, payload in (extra_parts or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def force_encryption_flag(zip_bytes: bytes) -> bytes:
    """zipfile 会清掉写入端的加密位；手动置位以构造“加密 DOCX”拒绝用例。"""
    data = bytearray(zip_bytes)
    data[6:8] = (int.from_bytes(data[6:8], "little") | 0x1).to_bytes(2, "little")
    central = data.find(b"PK\x01\x02")
    data[central + 8 : central + 10] = (
        int.from_bytes(data[central + 8 : central + 10], "little") | 0x1
    ).to_bytes(2, "little")
    return bytes(data)


class BodyOrderTest(unittest.TestCase):
    def test_body_table_body_fixture_keeps_interleaved_order(self) -> None:
        parsed = parse_docx(load_fixture("docx_body_table_body.docx"))

        self.assertEqual(parsed.format, "docx")
        self.assertEqual(parsed.parser_version, "docx/1")
        self.assertIsNone(parsed.line_count)
        self.assertEqual(
            parsed.nodes,
            (
                SourceNode(kind="paragraph", text="正文第一段", body_ordinal=0, paragraph_index=1),
                SourceNode(
                    kind="table_cell", text="甲组数据", body_ordinal=1,
                    table_index=1, row_index=1, cell_index=1, cell_paragraph_index=1,
                ),
                SourceNode(
                    kind="table_cell", text="重复项", body_ordinal=2,
                    table_index=1, row_index=1, cell_index=2, cell_paragraph_index=1,
                ),
                SourceNode(
                    kind="table_cell", text="乙组数据", body_ordinal=3,
                    table_index=1, row_index=2, cell_index=1, cell_paragraph_index=1,
                ),
                SourceNode(kind="paragraph", text="结语段落", body_ordinal=4, paragraph_index=2),
            ),
        )

    def test_two_tables_do_not_disturb_paragraph_indexes(self) -> None:
        data = build_docx(
            document(
                paragraph(run(text("一"))),
                table(row(cell(paragraph(run(text("表1")))))),
                paragraph(run(text("二"))),
                table(row(cell(paragraph(run(text("表2")))))),
                paragraph(run(text("三"))),
            )
        )
        parsed = parse_docx(data)

        self.assertEqual(
            [(node.kind, node.text) for node in parsed.nodes],
            [
                ("paragraph", "一"),
                ("table_cell", "表1"),
                ("paragraph", "二"),
                ("table_cell", "表2"),
                ("paragraph", "三"),
            ],
        )
        self.assertEqual(
            [node.paragraph_index for node in parsed.nodes if node.kind == "paragraph"],
            [1, 2, 3],
        )
        self.assertEqual(
            [node.table_index for node in parsed.nodes if node.kind == "table_cell"],
            [1, 2],
        )


class ParagraphTest(unittest.TestCase):
    def test_headings_are_paragraphs(self) -> None:
        parsed = parse_docx(load_fixture("docx_headings_chinese.docx"))

        self.assertEqual(
            [(node.kind, node.text, node.paragraph_index) for node in parsed.nodes],
            [
                ("paragraph", "第一章 项目概况", 1),
                ("paragraph", "普通正文。", 2),
                ("paragraph", "1.1 目标", 3),
            ],
        )

    def test_empty_paragraphs_do_not_shift_following_indexes(self) -> None:
        data = build_docx(document(paragraph(run(text("甲"))), paragraph(), paragraph(run(text("乙")))))
        parsed = parse_docx(data)

        self.assertEqual([node.paragraph_index for node in parsed.nodes], [1, 3])
        self.assertEqual([node.body_ordinal for node in parsed.nodes], [0, 1])

    def test_runs_are_merged_and_tab_break_are_real(self) -> None:
        parsed = parse_docx(load_fixture("docx_tab_break_runs.docx"))

        self.assertEqual([node.text for node in parsed.nodes], ["制表\t后\n换行后中文", " "])

    def test_tracked_deletion_is_not_part_of_text(self) -> None:
        deletion = "<w:del>" + run("<w:delText>删除</w:delText>") + "</w:del>"
        insertion = "<w:ins>" + run(text("新增")) + "</w:ins>"
        data = build_docx(
            document(paragraph(run(text("保留")), deletion, insertion, run(text("尾部"))))
        )
        parsed = parse_docx(data)

        self.assertEqual(parsed.nodes[0].text, "保留新增尾部")

    def test_picture_only_paragraph_yields_no_node(self) -> None:
        drawing = '<w:r><w:drawing><wp:inline><a:graphic><a:graphicData/></a:graphic></wp:inline></w:drawing></w:r>'
        data = build_docx(document(f"<w:p>{drawing}</w:p>"))
        parsed = parse_docx(data)

        self.assertEqual(parsed.nodes, ())

    def test_empty_body_fixture_has_no_nodes(self) -> None:
        parsed = parse_docx(load_fixture("docx_empty_body.docx"))

        self.assertEqual(parsed.nodes, ())
        self.assertIsNone(parsed.line_count)

    def test_header_text_is_not_part_of_body(self) -> None:
        parsed = parse_docx(load_fixture("docx_header_ignored.docx"))

        self.assertEqual([node.text for node in parsed.nodes], ["正文唯一段落"])

    def test_body_markers_are_ignored(self) -> None:
        data = build_docx(
            document(
                "<w:bookmarkStart w:id=\"1\" w:name=\"mark\"/>",
                paragraph(run(text("正文"))),
                '<w:bookmarkEnd w:id="1"/>',
            )
        )
        parsed = parse_docx(data)

        self.assertEqual([node.text for node in parsed.nodes], ["正文"])


class TableCellTest(unittest.TestCase):
    def test_cell_multi_paragraph_positions_and_empty_cells(self) -> None:
        parsed = parse_docx(load_fixture("docx_cell_multi_paragraph.docx"))

        self.assertEqual(
            parsed.nodes,
            (
                SourceNode(
                    kind="table_cell", text="单元格第一段", body_ordinal=0,
                    table_index=1, row_index=1, cell_index=1, cell_paragraph_index=1,
                ),
                SourceNode(
                    kind="table_cell", text="单元格第三段", body_ordinal=1,
                    table_index=1, row_index=1, cell_index=1, cell_paragraph_index=3,
                ),
                SourceNode(
                    kind="table_cell", text="重复项", body_ordinal=2,
                    table_index=1, row_index=1, cell_index=3, cell_paragraph_index=1,
                ),
                SourceNode(
                    kind="table_cell", text="重复项", body_ordinal=3,
                    table_index=1, row_index=1, cell_index=3, cell_paragraph_index=2,
                ),
            ),
        )

    def test_repeated_text_keeps_distinct_positions(self) -> None:
        parsed = parse_docx(load_fixture("docx_repeated_text.docx"))

        self.assertEqual([node.text for node in parsed.nodes], ["同一句文本"] * 3)
        self.assertEqual(
            [
                (node.kind, node.paragraph_index, node.table_index, node.row_index, node.cell_index, node.cell_paragraph_index)
                for node in parsed.nodes
            ],
            [
                ("paragraph", 1, None, None, None, None),
                ("paragraph", 2, None, None, None, None),
                ("table_cell", None, 1, 1, 1, 1),
            ],
        )

    def test_emptied_cell_between_cells_does_not_shift_cell_indexes(self) -> None:
        data = build_docx(
            document(table(row(cell(), cell(paragraph(run(text("乙"))))))),
        )
        parsed = parse_docx(data)

        self.assertEqual(
            [(node.cell_index, node.text) for node in parsed.nodes],
            [(2, "乙")],
        )

    def test_repeat_parse_is_identical(self) -> None:
        data = load_fixture("docx_body_table_body.docx")
        self.assertEqual(parse_docx(data), parse_docx(data))


class RejectionTest(unittest.TestCase):
    def assert_rejected(self, data: bytes, code: str) -> SourceParseError:
        with self.assertRaises(SourceParseError) as caught:
            parse_docx(data)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_broken_zip_is_rejected(self) -> None:
        self.assert_rejected(load_fixture("reject_broken_zip.docx"), "invalid_zip")

    def test_bad_xml_is_rejected(self) -> None:
        self.assert_rejected(load_fixture("reject_bad_xml.docx"), "invalid_xml")

    def test_missing_document_xml_is_rejected(self) -> None:
        self.assert_rejected(load_fixture("reject_missing_document.docx"), "invalid_docx")

    def test_wrong_root_element_is_rejected(self) -> None:
        data = build_docx(f'<foo xmlns:w="{W_NS}"><w:body/></foo>')
        self.assert_rejected(data, "invalid_docx")

    def test_merged_cells_fixture_is_rejected(self) -> None:
        error = self.assert_rejected(load_fixture("reject_merged_cells.docx"), "unsupported_structure")
        self.assertIn("合并单元格", error.message)

    def test_vmerge_and_hmerge_cells_are_rejected(self) -> None:
        vmerge = table(row(cell(paragraph(run(text("合并"))), properties='<w:tcPr><w:vMerge w:val="restart"/></w:tcPr>')))
        hmerge = table(row(cell(paragraph(run(text("合并"))), properties='<w:tcPr><w:hMerge w:val="continue"/></w:tcPr>')))
        self.assert_rejected(build_docx(document(vmerge)), "unsupported_structure")
        self.assert_rejected(build_docx(document(hmerge)), "unsupported_structure")

    def test_nested_table_is_rejected(self) -> None:
        self.assert_rejected(load_fixture("reject_nested_table.docx"), "unsupported_structure")

    def test_content_control_is_rejected(self) -> None:
        self.assert_rejected(load_fixture("reject_content_control.docx"), "unsupported_structure")

    def test_text_box_is_rejected(self) -> None:
        error = self.assert_rejected(load_fixture("reject_text_box.docx"), "unsupported_structure")
        self.assertIn("文本框", error.message)

    def test_duplicate_document_entry_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("word/document.xml", document(paragraph(run(text("一")))))
                archive.writestr("word/document.xml", document(paragraph(run(text("二")))))
        self.assert_rejected(buffer.getvalue(), "invalid_zip")

    def test_encrypted_archive_is_rejected(self) -> None:
        data = build_docx(document(paragraph(run(text("一")))))
        self.assert_rejected(force_encryption_flag(data), "invalid_zip")

    def test_total_uncompressed_limit(self) -> None:
        data = build_docx(document(paragraph(run(text("一")))))
        with mock.patch.object(docx_adapter, "MAX_DOCX_TOTAL_BYTES", 32):
            self.assert_rejected(data, "archive_too_large")

    def test_single_entry_uncompressed_limit(self) -> None:
        data = build_docx(document(paragraph(run(text("一")))))
        with mock.patch.object(docx_adapter, "MAX_DOCX_ENTRY_BYTES", 32):
            self.assert_rejected(data, "archive_too_large")

    def test_unsupported_table_child_is_rejected(self) -> None:
        data = build_docx(document(f"<w:tbl><w:sdt/></w:tbl>"))
        self.assert_rejected(data, "unsupported_structure")


if __name__ == "__main__":
    unittest.main()
