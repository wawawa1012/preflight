"""Iteration 2B：SQLite 持久化的真实读写、身份稳定与原子性测试。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import storage
from app.contracts import MarkdownPreview
from app.markdown_preview import build_preview


def make_preview(text: str = "甲\n\n乙\n", filename: str = "m.md") -> MarkdownPreview:
    return build_preview(filename, text.encode("utf-8"))


class StorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        storage.init_db(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_and_read_by_id(self) -> None:
        preview = make_preview()
        saved = storage.save_material(preview, self.db)

        self.assertTrue(saved.id.startswith("mat_"))
        self.assertEqual(saved.filename, "m.md")
        self.assertEqual(saved.sha256, preview.sha256)
        self.assertEqual([block.text for block in saved.blocks], ["甲", "乙"])
        self.assertEqual([block.locator.index for block in saved.blocks], [1, 3])
        self.assertEqual([block.document_id for block in saved.blocks], [saved.id, saved.id])
        # 持久化 ID 不能沿用临时预览 ID。
        self.assertNotEqual(saved.blocks[0].id, preview.blocks[0].id)

        # 每次读取都新建连接，等价于进程重启后读取。
        loaded = storage.get_material(saved.id, self.db)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.model_dump(), saved.model_dump())

    def test_recent_follows_last_successful_save_and_keeps_old_material(self) -> None:
        first = storage.save_material(make_preview("A\n", "a.md"), self.db)
        self.assertEqual(storage.get_recent_material(self.db).id, first.id)

        second = storage.save_material(make_preview("B\n", "b.md"), self.db)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(storage.get_recent_material(self.db).id, second.id)

        old = storage.get_material(first.id, self.db)
        self.assertIsNotNone(old)
        self.assertEqual(old.filename, "a.md")
        self.assertEqual([block.text for block in old.blocks], ["A"])

    def test_unknown_id_and_empty_recent(self) -> None:
        self.assertIsNone(storage.get_material("mat_missing", self.db))
        self.assertIsNone(storage.get_recent_material(self.db))

    def test_failed_save_leaves_no_partial_rows_and_keeps_pointer(self) -> None:
        first = storage.save_material(make_preview("A\nB\n", "a.md"), self.db)

        # 损坏输入：两份 Block 使用同一 ordinal，触发写入中途的 UNIQUE/主键约束。
        payload = make_preview("C\nD\n", "c.md").model_dump()
        payload["blocks"] = [payload["blocks"][0], payload["blocks"][0]]
        broken = MarkdownPreview.model_validate(payload)

        with self.assertRaises(sqlite3.IntegrityError):
            storage.save_material(broken, self.db)

        with closing(storage.connect(self.db)) as connection:
            materials = connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
            blocks = connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        self.assertEqual(materials, 1)
        self.assertEqual(blocks, 2)
        self.assertEqual(storage.get_recent_material(self.db).id, first.id)

    def test_foreign_key_is_enforced(self) -> None:
        with closing(storage.connect(self.db)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO blocks"
                    " (id, material_id, ordinal, kind, locator_index, end_index, row_index, cell_index, paragraph_index, text, block_index)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("blk_orphan", "mat_missing", 0, "line", 1, None, None, None, None, "x", 1),
                )

    def test_same_input_saved_twice_gets_distinct_identities(self) -> None:
        data = "同一内容\n\n第二行\n".encode("utf-8")
        first = storage.save_material(build_preview("same.md", data), self.db)
        second = storage.save_material(build_preview("same.md", data), self.db)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.sha256, second.sha256)
        self.assertTrue({block.id for block in first.blocks}.isdisjoint(block.id for block in second.blocks))
        self.assertEqual(storage.get_material(first.id, self.db).model_dump(), first.model_dump())
        self.assertEqual(storage.get_material(second.id, self.db).model_dump(), second.model_dump())
        self.assertEqual(storage.get_recent_material(self.db).id, second.id)

    def test_failure_during_recent_pointer_update_rolls_back_second_material(self) -> None:
        first = storage.save_material(make_preview("A\nA2\n", "a.md"), self.db)

        # 用真实 SQLite trigger 在 recent 指针 UPDATE 阶段注入失败。
        with closing(storage.connect(self.db)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER reject_recent_update BEFORE UPDATE ON recent_material"
                " BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            storage.save_material(make_preview("B\nB2\nB3\n", "b.md"), self.db)

        with closing(storage.connect(self.db)) as connection:
            materials = connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
            blocks = connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        self.assertEqual(materials, 1)  # B 的 Material 0 残留
        self.assertEqual(blocks, 2)  # B 的 Blocks 0 残留；A 的 2 行完整
        self.assertEqual(storage.get_material(first.id, self.db).model_dump(), first.model_dump())
        self.assertEqual(storage.get_recent_material(self.db).id, first.id)

    def test_init_db_is_idempotent_on_populated_database(self) -> None:
        saved = storage.save_material(make_preview("甲\n\n乙\n", "idem.md"), self.db)
        with closing(storage.connect(self.db)) as connection:
            before = (
                connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0],
                tuple(row[0] for row in connection.execute("SELECT id FROM materials ORDER BY id")),
                tuple(row[0] for row in connection.execute("SELECT id FROM blocks ORDER BY id")),
            )

        storage.init_db(self.db)  # 重复初始化：必须保留已有数据与 stable IDs

        with closing(storage.connect(self.db)) as connection:
            after = (
                connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0],
                tuple(row[0] for row in connection.execute("SELECT id FROM materials ORDER BY id")),
                tuple(row[0] for row in connection.execute("SELECT id FROM blocks ORDER BY id")),
            )
        self.assertEqual(before, after)
        self.assertEqual(storage.get_material(saved.id, self.db).model_dump(), saved.model_dump())
        self.assertEqual(storage.get_recent_material(self.db).id, saved.id)

    def test_list_materials_is_newest_first_with_block_counts(self) -> None:
        self.assertEqual(storage.list_materials(self.db), [])

        first = storage.save_material(make_preview("A\nA2\n", "a.md"), self.db)
        second = storage.save_material(make_preview("B\n", "b.md"), self.db)

        listed = storage.list_materials(self.db)
        self.assertEqual([item.id for item in listed], [second.id, first.id])  # 最新在前
        self.assertEqual([item.block_count for item in listed], [1, 2])
        self.assertEqual([item.filename for item in listed], ["b.md", "a.md"])


if __name__ == "__main__":
    unittest.main()
