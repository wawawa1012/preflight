"""Migration 生命周期：原子边界、失败回滚、重试成功、版本拒绝与外键状态恢复。

定向验证：
- 失败注入（临时表已建/重建中途/foreign_key_check/新库 schema）后：临时表不存在、
  原表/原数据/ID 完整、user_version 未提前更新、外键状态恢复、第二次 retry 成功；
- version > supported → 明确拒绝；
- connection 已有事务 → 拒绝迁移，且不提交/回滚调用方事务。
"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from app import database, migrations, storage

LEGACY_SCHEMA = """
CREATE TABLE materials (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    line_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE blocks (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    UNIQUE (material_id, ordinal)
);
CREATE TABLE recent_material (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    material_id TEXT NOT NULL REFERENCES materials(id)
);
CREATE TABLE evidence_annotations (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    start INTEGER NOT NULL,
    end INTEGER NOT NULL,
    quote TEXT NOT NULL,
    note TEXT,
    proposed_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE material_rubric_bindings (
    material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
    rubric_id TEXT NOT NULL,
    rubric_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE criterion_evidence_links (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    annotation_id TEXT NOT NULL REFERENCES evidence_annotations(id) ON DELETE CASCADE,
    rubric_id TEXT NOT NULL,
    rubric_revision INTEGER NOT NULL,
    criterion_id TEXT NOT NULL,
    rationale TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (annotation_id, criterion_id, rubric_revision)
);
CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    rubric_revision INTEGER NOT NULL CHECK (rubric_revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE review_materials (
    review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (review_id, material_id)
);
CREATE TABLE material_revisions (
    child_material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
    parent_material_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

LEGACY_ANNOTATION_TEXT = "甲乙"


def build_legacy_db(db: Path) -> None:
    """按 v0 表结构造一份带引用/绑定/review/revision 的旧库。"""
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO materials VALUES ('mat_parent', 'old.md', 6, ?, 3, '2026-01-01T00:00:00+00:00')",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO materials VALUES ('mat_child', 'old-v2.md', 6, ?, 2, '2026-01-02T00:00:00+00:00')",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO blocks VALUES ('blk_parent_1', 'mat_parent', 0, 1, ?, 1)", (LEGACY_ANNOTATION_TEXT,)
        )
        connection.execute("INSERT INTO blocks VALUES ('blk_parent_3', 'mat_parent', 1, 3, '丙', 1)")
        connection.execute("INSERT INTO blocks VALUES ('blk_child_1', 'mat_child', 0, 1, '甲乙', 1)")
        connection.execute("INSERT INTO recent_material VALUES (1, 'mat_parent')")
        connection.execute(
            "INSERT INTO evidence_annotations VALUES ('ev_legacy', 'mat_parent', 'blk_parent_1', 0, 1, '甲',"
            " '旧标注', 'human', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO material_rubric_bindings VALUES ('mat_parent', 'rubric_syn', 1, '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO criterion_evidence_links VALUES ('cel_legacy', 'mat_parent', 'ev_legacy', 'rubric_syn', 1,"
            " 'c_syn_1', '旧关联', 'human', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO reviews VALUES ('rev_legacy', '旧评审', 'rubric_syn', 1,"
            " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute("INSERT INTO review_materials VALUES ('rev_legacy', 'mat_parent', 'old.md', 0)")
        connection.execute(
            "INSERT INTO material_revisions VALUES ('mat_child', 'mat_parent', '2026-01-02T00:00:00+00:00')"
        )


class MigrationTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "legacy.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def table_names(self) -> set[str]:
        with closing(database.connect(self.db)) as connection:
            return {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }

    def assert_no_temp_tables(self) -> None:
        names = self.table_names()
        self.assertNotIn("materials_locator_v1", names)
        self.assertNotIn("blocks_locator_v1", names)

    def assert_legacy_intact(self, expected_version: int = 0) -> None:
        """失败后旧 schema/数据/ID 原样，版本未被迁移更新。"""
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], expected_version)
            self.assertIn("line_number", migrations._table_columns(connection, "blocks"))
            self.assertNotIn("format", migrations._table_columns(connection, "materials"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0], 3)
            self.assertEqual(
                connection.execute("SELECT line_number FROM blocks WHERE id = 'blk_parent_3'").fetchone()[0], 3
            )
            self.assertEqual(
                connection.execute("SELECT quote FROM evidence_annotations WHERE id = 'ev_legacy'").fetchone()[0],
                "甲",
            )
        self.assert_no_temp_tables()


class BootstrapAcceptanceTest(MigrationTestBase):
    def test_legacy_migration_backfills_lines_and_keeps_references(self) -> None:
        build_legacy_db(self.db)
        database.init_db(self.db)

        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], migrations.SCHEMA_VERSION)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

        parent = storage.get_material("mat_parent", self.db)
        self.assertEqual(parent.format, "md")
        self.assertIsNone(parent.parser_version)
        self.assertIsNone(storage.get_source_bytes("mat_parent", self.db))
        self.assertEqual(parent.line_count, 3)
        self.assertEqual([block.id for block in parent.blocks], ["blk_parent_1", "blk_parent_3"])
        self.assertEqual([block.text for block in parent.blocks], [LEGACY_ANNOTATION_TEXT, "丙"])
        first, second = (block.locator for block in parent.blocks)
        self.assertEqual((first.kind, first.index, first.end_index, first.block_index), ("line", 1, None, 1))
        self.assertEqual((second.kind, second.index), ("line", 3))
        self.assertEqual((first.row_index, first.cell_index, first.paragraph_index), (None, None, None))

        annotation = storage.get_evidence_annotation("ev_legacy", self.db)
        self.assertEqual((annotation.block_id, annotation.source.start, annotation.source.end), ("blk_parent_1", 0, 1))
        self.assertEqual(annotation.source.quote, "甲")
        self.assertEqual([link.id for link in storage.list_links("mat_parent", self.db)], ["cel_legacy"])
        binding = storage.get_binding("mat_parent", self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))
        revision = storage.get_revision_context("mat_child", self.db)
        self.assertEqual((revision.parent.material_id, revision.parent.parent_available), ("mat_parent", True))
        review = storage.get_review_detail("rev_legacy", self.db)
        self.assertEqual([entry.material_id for entry in review.materials], ["mat_parent"])

    def test_second_migration_is_idempotent(self) -> None:
        build_legacy_db(self.db)
        database.init_db(self.db)
        before = storage.get_material("mat_parent", self.db).model_dump()

        database.init_db(self.db)
        database.init_db(self.db)

        self.assertEqual(storage.get_material("mat_parent", self.db).model_dump(), before)
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertNotIn("line_number", migrations._table_columns(connection, "blocks"))

    def test_fresh_db_gets_current_version(self) -> None:
        database.init_db(self.db)
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], migrations.SCHEMA_VERSION)
        self.assertEqual(storage.list_materials(self.db), [])


class MigrationFailureRetryTest(MigrationTestBase):
    """CASE 1/2/3：任何一步失败都必须整体回滚，且 patch 移除后 retry 成功。"""

    def test_case1_failure_after_temp_table_create(self) -> None:
        build_legacy_db(self.db)
        original = migrations._rebuild_materials_legacy

        def failing(connection: sqlite3.Connection) -> None:
            original(connection)  # materials_locator_v1 已建并 copy 完
            raise RuntimeError("case1: failure after temp table create")

        with mock.patch.object(migrations, "_rebuild_materials_legacy", failing):
            with self.assertRaises(RuntimeError):
                database.init_db(self.db)

        self.assert_legacy_intact()
        database.init_db(self.db)  # retry 成功
        self.assertEqual(storage.get_material("mat_parent", self.db).format, "md")

    def test_case2_failure_mid_blocks_rebuild(self) -> None:
        build_legacy_db(self.db)

        def failing(connection: sqlite3.Connection) -> None:
            connection.execute("CREATE TABLE blocks_locator_v1 (id TEXT)")  # 只完成第一步
            raise RuntimeError("case2: failure mid blocks rebuild")

        with mock.patch.object(migrations, "_rebuild_blocks_legacy", failing):
            with self.assertRaises(RuntimeError):
                database.init_db(self.db)

        self.assert_legacy_intact()
        database.init_db(self.db)
        self.assertEqual([block.id for block in storage.get_material("mat_parent", self.db).blocks],
                         ["blk_parent_1", "blk_parent_3"])

    def test_case3_foreign_key_check_failure(self) -> None:
        build_legacy_db(self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            # legacy 库允许 FK 关闭时写入；孤儿 block 让迁移后的 foreign_key_check 失败。
            connection.execute("INSERT INTO blocks VALUES ('blk_orphan', 'mat_missing', 9, 9, '孤儿', 1)")

        with self.assertRaises(migrations.MigrationError) as caught:
            database.init_db(self.db)
        self.assertIn("外键完整性", caught.exception.args[0] if caught.exception.args else "")
        self.assert_no_temp_tables()
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertIn("line_number", migrations._table_columns(connection, "blocks"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0], 4)

        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM blocks WHERE id = 'blk_orphan'")
        database.init_db(self.db)  # retry 成功
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_case4_fresh_schema_bootstrap_failure(self) -> None:
        original_statements = migrations._SCHEMA_STATEMENTS

        def failing_create(connection: sqlite3.Connection) -> None:
            connection.execute(original_statements[0])  # 已建 materials
            connection.execute(original_statements[1])  # 已建 blocks
            raise RuntimeError("case4: fresh schema failure")

        with mock.patch.object(migrations, "_create_schema", failing_create):
            with self.assertRaises(RuntimeError):
                database.init_db(self.db)

        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(
                connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall(), []
            )
        database.init_db(self.db)  # retry 成功
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], migrations.SCHEMA_VERSION)
            self.assertTrue(migrations._table_exists(connection, "blocks"))
            self.assertTrue(migrations._table_exists(connection, "recent_material"))


class VersionAndTransactionGuardTest(MigrationTestBase):
    def test_future_user_version_is_rejected(self) -> None:
        build_legacy_db(self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(f"PRAGMA user_version = {migrations.SCHEMA_VERSION + 1}")

        with self.assertRaises(migrations.UnsupportedSchemaVersion):
            database.init_db(self.db)

        self.assert_legacy_intact(expected_version=migrations.SCHEMA_VERSION + 1)
        with closing(database.connect(self.db)) as connection:
            self.assertIn("line_number", migrations._table_columns(connection, "blocks"))

    def test_fresh_db_with_future_version_is_rejected_without_schema(self) -> None:
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(f"PRAGMA user_version = {migrations.SCHEMA_VERSION + 1}")
        with self.assertRaises(migrations.UnsupportedSchemaVersion):
            database.init_db(self.db)
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(
                connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall(), []
            )

    def test_open_caller_transaction_is_refused_and_untouched(self) -> None:
        build_legacy_db(self.db)
        with closing(database.connect(self.db)) as connection:
            connection.execute(
                "INSERT INTO materials VALUES ('mat_tx', 'tx.md', 1, ?, 1, '2026-01-03T00:00:00+00:00')",
                ("c" * 64,),
            )
            self.assertTrue(connection.in_transaction)

            with self.assertRaises(migrations.MigrationError):
                migrations.bootstrap(connection)

            # 调用方事务未被提交或回滚：数据仍在、事务仍打开。
            self.assertTrue(connection.in_transaction)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM materials WHERE id = 'mat_tx'").fetchone()[0], 1
            )
            connection.rollback()

        self.assert_legacy_intact()
        with closing(database.connect(self.db)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM materials WHERE id = 'mat_tx'").fetchone()[0], 0
            )


class ForeignKeyLifecycleTest(MigrationTestBase):
    def test_fk_state_restored_after_success_and_failure(self) -> None:
        for failing in (False, True):
            for initial in (1, 0):
                with self.subTest(failing=failing, initial=initial):
                    case = Path(self._tmp.name) / f"fk-{failing}-{initial}.db"
                    build_legacy_db(case)
                    connection = database.connect(case)
                    try:
                        connection.execute(f"PRAGMA foreign_keys = {'ON' if initial else 'OFF'}")
                        if failing:
                            with mock.patch.object(
                                migrations,
                                "_rebuild_blocks_legacy",
                                side_effect=RuntimeError("injected"),
                            ):
                                with self.assertRaises(RuntimeError):
                                    migrations.bootstrap(connection)
                            expected_version = 0
                        else:
                            migrations.bootstrap(connection)
                            expected_version = migrations.SCHEMA_VERSION
                        self.assertEqual(
                            connection.execute("PRAGMA foreign_keys").fetchone()[0], initial
                        )
                        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], expected_version)
                    finally:
                        connection.close()


if __name__ == "__main__":
    unittest.main()
