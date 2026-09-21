"""Iteration 3：quote 验证门、证据标注持久化与 API 错误码测试。"""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.exceptions import RequestValidationError

from app import main, storage
from app.contracts import EvidenceAnnotationCreate
from app.evidence import QuoteNotFound, resolve_span
from app.markdown_preview import build_preview

CHINESE_TEXT = "中文语料：准确率达到 95%，整体稳定。"
CHINESE_QUOTE = "准确率达到 95%"


def make_material(db: Path, text: str = CHINESE_TEXT, filename: str = "ev.md"):
    return storage.save_material(build_preview(filename, text.encode("utf-8")), db)


class ResolveSpanTest(unittest.TestCase):
    def test_chinese_quote_uses_code_point_offsets(self) -> None:
        self.assertEqual(resolve_span(CHINESE_TEXT, CHINESE_QUOTE), (5, 14))
        self.assertEqual(CHINESE_TEXT[5:14], CHINESE_QUOTE)

    def test_first_and_last_and_whole_block(self) -> None:
        self.assertEqual(resolve_span("重复重复", "重复"), (0, 2))  # 重复取第一次出现
        self.assertEqual(resolve_span("甲乙", "乙"), (1, 2))  # 末字符
        self.assertEqual(resolve_span("甲\n乙", "甲\n乙"), (0, 3))  # 整块（含换行）

    def test_missing_and_empty_are_rejected(self) -> None:
        with self.assertRaises(QuoteNotFound):
            resolve_span("abc", "xyz")
        with self.assertRaises(QuoteNotFound):
            resolve_span("abc", "")


class AnnotationStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        storage.init_db(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _count_annotations(self) -> int:
        with closing(storage.connect(self.db)) as connection:
            return connection.execute("SELECT COUNT(*) FROM evidence_annotations").fetchone()[0]

    def test_save_get_list_with_server_derived_material(self) -> None:
        material = make_material(self.db)
        block = material.blocks[0]

        annotation = storage.save_evidence_annotation(block.id, CHINESE_QUOTE, "高风险引用", db_path=self.db)
        self.assertIsNotNone(annotation)
        self.assertEqual(annotation.material_id, material.id)  # 由 block 行派生，而不是客户端提交
        self.assertEqual(annotation.block_id, block.id)
        self.assertEqual((annotation.source.start, annotation.source.end), (5, 14))
        self.assertEqual(annotation.source.quote, CHINESE_QUOTE)
        self.assertEqual(annotation.proposed_by, "human")

        loaded = storage.get_evidence_annotation(annotation.id, self.db)
        self.assertEqual(loaded.model_dump(), annotation.model_dump())
        self.assertEqual([item.id for item in storage.list_evidence_annotations(material.id, self.db)], [annotation.id])

    def test_unknown_block_returns_none_without_rows(self) -> None:
        make_material(self.db)
        self.assertIsNone(storage.save_evidence_annotation("blk_missing", "任意", db_path=self.db))
        self.assertEqual(self._count_annotations(), 0)

    def test_quote_not_found_leaves_no_partial_rows(self) -> None:
        material = make_material(self.db)
        with self.assertRaises(QuoteNotFound):
            storage.save_evidence_annotation(material.blocks[0].id, "不存在的引用", db_path=self.db)
        self.assertEqual(self._count_annotations(), 0)

    def test_annotations_are_isolated_per_material(self) -> None:
        first = make_material(self.db, "甲\n", "a.md")
        second = make_material(self.db, "乙\n", "b.md")
        first_annotation = storage.save_evidence_annotation(first.blocks[0].id, "甲", db_path=self.db)
        second_annotation = storage.save_evidence_annotation(second.blocks[0].id, "乙", db_path=self.db)

        self.assertEqual([a.id for a in storage.list_evidence_annotations(first.id, self.db)], [first_annotation.id])
        self.assertEqual([a.id for a in storage.list_evidence_annotations(second.id, self.db)], [second_annotation.id])

    def test_cross_connection_persistence(self) -> None:
        material = make_material(self.db)
        annotation = storage.save_evidence_annotation(material.blocks[0].id, CHINESE_QUOTE, db_path=self.db)
        # 每次读取都会新建连接，等价于进程重启后读取。
        self.assertEqual(storage.get_evidence_annotation(annotation.id, self.db).id, annotation.id)

    def test_fk_cascade_deletes_annotations_with_material(self) -> None:
        target = make_material(self.db, "甲\n", "a.md")
        make_material(self.db, "乙\n", "b.md")  # recent 指针指向另一份，删除 target 不受指针外键影响
        annotation = storage.save_evidence_annotation(target.blocks[0].id, "甲", db_path=self.db)
        with closing(storage.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM materials WHERE id = ?", (target.id,))
        self.assertIsNone(storage.get_evidence_annotation(annotation.id, self.db))
        self.assertEqual(self._count_annotations(), 0)


class EvidenceApiErrorTest(unittest.TestCase):
    """API 层错误码映射：用 temp DB 替换 storage 默认路径，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "api.db"
        storage.init_db(self.db)
        self._originals = (
            storage.save_evidence_annotation,
            storage.get_evidence_annotation,
            storage.material_exists,
            storage.list_evidence_annotations,
        )
        original_save, original_get, original_exists, original_list = self._originals
        storage.save_evidence_annotation = (
            lambda block_id, quote, note=None, proposed_by="human", **kwargs: original_save(
                block_id, quote, note, proposed_by, self.db, **kwargs
            )
        )
        storage.get_evidence_annotation = lambda annotation_id: original_get(annotation_id, self.db)
        storage.material_exists = lambda material_id: original_exists(material_id, self.db)
        storage.list_evidence_annotations = lambda material_id: original_list(material_id, self.db)

    def tearDown(self) -> None:
        (
            storage.save_evidence_annotation,
            storage.get_evidence_annotation,
            storage.material_exists,
            storage.list_evidence_annotations,
        ) = self._originals
        self._tmp.cleanup()

    def test_unknown_block_maps_to_block_not_found(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.create_evidence_annotation(EvidenceAnnotationCreate(block_id="blk_missing", quote="任意"))
        self.assertEqual(caught.exception.code, "block_not_found")

    def test_unknown_material_list_maps_to_material_not_found(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.material_evidence_annotations("mat_missing")
        self.assertEqual(caught.exception.code, "material_not_found")

    def test_unknown_annotation_maps_to_annotation_not_found(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.evidence_annotation_by_id("ev_missing")
        self.assertEqual(caught.exception.code, "annotation_not_found")

    def test_quote_not_found_handler_is_400_api_error(self) -> None:
        response = asyncio.run(main.quote_not_found(None, QuoteNotFound("quote 不在该 Block 原文中")))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body)["code"], "quote_not_found")

    def test_validation_handler_is_400_api_error(self) -> None:
        exc = RequestValidationError(
            [{"type": "missing", "loc": ("body", "quote"), "msg": "Field required", "input": None}]
        )
        response = asyncio.run(main.request_invalid(None, exc))
        self.assertEqual(response.status_code, 400)
        body = json.loads(response.body)
        self.assertEqual(body["code"], "invalid_request")
        self.assertTrue(any("body.quote" in item for item in body["details"]))


if __name__ == "__main__":
    unittest.main()
