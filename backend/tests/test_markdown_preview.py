"""Iteration 2A：Markdown 预览的纯函数测试；不依赖网络或数据库。"""
import hashlib
import unittest

from app.markdown_preview import (
    MAX_BYTES,
    PreviewRejected,
    build_preview,
    decode_markdown,
    split_lines,
)


class DecodeTest(unittest.TestCase):
    def test_utf8_bom_is_stripped(self) -> None:
        self.assertEqual(decode_markdown(b"\xef\xbb\xbf# title"), "# title")

    def test_invalid_utf8_is_rejected(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            decode_markdown(b"\xff\xfe not utf-8")
        self.assertEqual(caught.exception.code, "invalid_encoding")


class SplitLinesTest(unittest.TestCase):
    def test_lf(self) -> None:
        self.assertEqual(split_lines("a\nb\n"), ["a", "b"])

    def test_crlf(self) -> None:
        self.assertEqual(split_lines("a\r\nb\r\n"), ["a", "b"])

    def test_missing_final_newline(self) -> None:
        self.assertEqual(split_lines("a\nb"), ["a", "b"])

    def test_empty_and_blank_only(self) -> None:
        self.assertEqual(split_lines(""), [])
        self.assertEqual(split_lines("\n"), [""])
        self.assertEqual(split_lines("   \n\t\n"), ["   ", "\t"])


class BuildPreviewTest(unittest.TestCase):
    def test_chinese_blank_lines_spaces_and_crlf(self) -> None:
        data = "标题\n\n  缩进行  \r\n最后一行\r\n".encode("utf-8")
        preview = build_preview("示例.md", data)

        self.assertEqual(preview.filename, "示例.md")
        self.assertEqual(preview.size_bytes, len(data))
        self.assertEqual(preview.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(preview.line_count, 4)
        self.assertEqual([block.ordinal for block in preview.blocks], [0, 1, 2])
        self.assertEqual([block.locator.index for block in preview.blocks], [1, 3, 4])
        self.assertEqual([block.text for block in preview.blocks], ["标题", "  缩进行  ", "最后一行"])
        for block in preview.blocks:
            self.assertEqual(block.locator.kind, "line")
            self.assertIsNone(block.locator.end_index)
            self.assertEqual(block.locator.block_index, 1)
            self.assertEqual(block.document_id, preview.document_id)

    def test_repeat_upload_is_identical(self) -> None:
        data = "# Title\n\nBody line\n".encode("utf-8")
        first = build_preview("repeat.md", data)
        second = build_preview("repeat.md", data)
        self.assertEqual(first.model_dump(), second.model_dump())

    def test_empty_file_has_no_blocks(self) -> None:
        preview = build_preview("empty.md", b"")
        self.assertEqual(preview.line_count, 0)
        self.assertEqual(preview.blocks, [])

    def test_empty_lines_have_no_blocks(self) -> None:
        preview = build_preview("empty-lines.md", "\n\n".encode("utf-8"))
        self.assertEqual(preview.line_count, 2)
        self.assertEqual(preview.blocks, [])

    def test_whitespace_only_lines_generate_blocks(self) -> None:
        # G10 唯一确定预期：只有长度为 0 的行是空行，空格/Tab 行必须生成 Block。
        preview = build_preview("blank.md", "   \n\t\n".encode("utf-8"))
        self.assertEqual(preview.line_count, 2)
        self.assertEqual([block.ordinal for block in preview.blocks], [0, 1])
        self.assertEqual([block.locator.index for block in preview.blocks], [1, 2])
        self.assertEqual([block.text for block in preview.blocks], ["   ", "\t"])

    def test_space_line_between_text_keeps_whitespace(self) -> None:
        preview = build_preview("space-line.md", "甲\n \n乙".encode("utf-8"))
        self.assertEqual(preview.line_count, 3)
        self.assertEqual([block.ordinal for block in preview.blocks], [0, 1, 2])
        self.assertEqual([block.locator.index for block in preview.blocks], [1, 2, 3])
        self.assertEqual([block.text for block in preview.blocks], ["甲", " ", "乙"])

    def test_bom_is_not_part_of_first_block_text(self) -> None:
        preview = build_preview("bom.md", "\ufeff甲\n".encode("utf-8"))
        self.assertEqual(preview.line_count, 1)
        self.assertEqual([block.text for block in preview.blocks], ["甲"])

    def test_wrong_extension_is_rejected(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            build_preview("notes.txt", b"hello")
        self.assertEqual(caught.exception.code, "invalid_extension")

    def test_oversize_is_rejected(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            build_preview("big.md", b"a" * (MAX_BYTES + 1))
        self.assertEqual(caught.exception.code, "file_too_large")


if __name__ == "__main__":
    unittest.main()
