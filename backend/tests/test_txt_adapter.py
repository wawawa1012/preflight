"""TXT 解析器纯函数测试：只用合成 fixtures；不依赖网络、数据库或用户材料。"""
from dataclasses import fields
from pathlib import Path
import subprocess
import sys
import unittest

from app.markdown_preview import build_preview
from app.source_adapters import SourceNode, SourceParseError
from app.txt_adapter import decode_txt, parse_txt, split_lines

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "source_adapters"

SOURCE_NODE_FIELDS = {
    "kind",
    "text",
    "body_ordinal",
    "line_index",
    "paragraph_index",
    "table_index",
    "row_index",
    "cell_index",
    "cell_paragraph_index",
}


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class DecodeTest(unittest.TestCase):
    def test_utf8_bom_is_stripped(self) -> None:
        self.assertEqual(decode_txt("\ufeff标题".encode("utf-8")), "标题")

    def test_invalid_utf8_is_rejected(self) -> None:
        with self.assertRaises(SourceParseError) as caught:
            decode_txt(b"\xff\xfe not utf-8")
        self.assertEqual(caught.exception.code, "invalid_encoding")


class SplitLinesTest(unittest.TestCase):
    def test_lf_and_crlf(self) -> None:
        self.assertEqual(split_lines("a\nb\n"), ["a", "b"])
        self.assertEqual(split_lines("a\r\nb\r\n"), ["a", "b"])

    def test_missing_final_newline(self) -> None:
        self.assertEqual(split_lines("a\nb"), ["a", "b"])

    def test_empty_and_blank_only(self) -> None:
        self.assertEqual(split_lines(""), [])
        self.assertEqual(split_lines("\n"), [""])
        self.assertEqual(split_lines("   \n\t\n"), ["   ", "\t"])


class ParseTxtTest(unittest.TestCase):
    def test_bom_crlf_chinese_blank_line_and_tab_fixture(self) -> None:
        parsed = parse_txt(load_fixture("txt_lines_bom_crlf_cn.txt"))

        self.assertEqual(parsed.format, "txt")
        self.assertEqual(parsed.parser_version, "txt/1")
        self.assertEqual(parsed.line_count, 4)
        self.assertEqual(
            parsed.nodes,
            (
                SourceNode(kind="line", text="标题行", body_ordinal=0, line_index=1),
                SourceNode(kind="line", text="   ", body_ordinal=1, line_index=3),
                SourceNode(kind="line", text="第三行\t带tab", body_ordinal=2, line_index=4),
            ),
        )

    def test_lf_fixture_keeps_trailing_space(self) -> None:
        parsed = parse_txt(load_fixture("txt_lines_lf_plain.txt"))

        self.assertEqual(parsed.line_count, 3)
        self.assertEqual([node.text for node in parsed.nodes], ["alpha", "beta "])
        self.assertEqual([node.line_index for node in parsed.nodes], [1, 3])

    def test_matches_markdown_line_text_and_real_line_numbers(self) -> None:
        payloads = [
            "标题\n\n  缩进行  \r\n最后一行\r\n",
            "甲\n \n乙",
            "\ufeff带BOM\n\n末行",
            "",
            "\n\n",
            "没有末尾换行",
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                data = payload.encode("utf-8")
                preview = build_preview("parity.md", data)
                parsed = parse_txt(data)

                self.assertEqual(parsed.line_count, preview.line_count)
                self.assertEqual(
                    [(node.kind, node.text, node.line_index) for node in parsed.nodes],
                    [("line", block.text, block.locator.index) for block in preview.blocks],
                )

    def test_empty_input_has_zero_lines_and_no_nodes(self) -> None:
        parsed = parse_txt(b"")

        self.assertEqual(parsed.line_count, 0)
        self.assertEqual(parsed.nodes, ())

    def test_whitespace_only_line_produces_node(self) -> None:
        parsed = parse_txt("甲\n \n乙".encode("utf-8"))

        self.assertEqual([node.text for node in parsed.nodes], ["甲", " ", "乙"])
        self.assertEqual([node.line_index for node in parsed.nodes], [1, 2, 3])

    def test_body_ordinal_is_consecutive_zero_based(self) -> None:
        parsed = parse_txt("\n甲\n\n乙\n丙\n".encode("utf-8"))

        self.assertEqual([node.body_ordinal for node in parsed.nodes], [0, 1, 2])
        self.assertEqual([node.line_index for node in parsed.nodes], [2, 4, 5])

    def test_parse_is_pure_and_repeatable(self) -> None:
        data = load_fixture("txt_lines_bom_crlf_cn.txt")
        self.assertEqual(parse_txt(data), parse_txt(data))

    def test_source_node_protocol_fields_are_frozen(self) -> None:
        self.assertEqual({field.name for field in fields(SourceNode)}, SOURCE_NODE_FIELDS)


class NoSideEffectImportTest(unittest.TestCase):
    def test_adapters_import_without_contracts_storage_or_sqlite(self) -> None:
        code = (
            "import sys; "
            "import app.source_adapters, app.txt_adapter, app.docx_adapter; "
            "bad = [m for m in ('app.contracts', 'app.storage', 'app.main', 'sqlite3') if m in sys.modules]; "
            "print('BAD', bad)"
        )
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "BAD []")


if __name__ == "__main__":
    unittest.main()
