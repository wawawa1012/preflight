"""运行时数据库路径配置：显式参数 > PREFLIGHT_DB_PATH > DEFAULT_DB_PATH。

对应 CASE 1–5：
- CASE 1 默认：未设置环境变量时仍解析到 DEFAULT_DB_PATH（不触碰开发库）。
- CASE 2 环境覆盖：init_db() 只创建/初始化环境变量指定的库，并自动创建父目录。
- CASE 3 显式优先：显式 db_path 胜过环境变量。
- CASE 4 隔离：写 db_a 后 db_b 不存在该记录。
- CASE 5 迁移：覆盖路径上 migration 正常，未来 schema 版本仍被拒绝。
"""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import database, migrations, storage


def dev_db_state() -> tuple[bool, int, int]:
    """开发库的文件状态（存在性/mtime/大小），用于证明测试未读写它。"""
    if not database.DEFAULT_DB_PATH.exists():
        return (False, 0, 0)
    stat = database.DEFAULT_DB_PATH.stat()
    return (True, stat.st_mtime_ns, stat.st_size)


class RuntimeDbPathTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._original_env = os.environ.get(database.DB_PATH_ENV_VAR)
        os.environ.pop(database.DB_PATH_ENV_VAR, None)

    def tearDown(self) -> None:
        if self._original_env is None:
            os.environ.pop(database.DB_PATH_ENV_VAR, None)
        else:
            os.environ[database.DB_PATH_ENV_VAR] = self._original_env
        self._tmp.cleanup()

    def temp_path(self, name: str) -> Path:
        return Path(self._tmp.name) / name


class DefaultPathTest(RuntimeDbPathTestBase):
    def test_default_resolution_unchanged(self) -> None:
        self.assertIsNone(os.environ.get(database.DB_PATH_ENV_VAR))
        self.assertEqual(database.resolve_db_path(), database.DEFAULT_DB_PATH)
        self.assertEqual(database.resolve_db_path(None), database.DEFAULT_DB_PATH)


class EnvOverrideTest(RuntimeDbPathTestBase):
    def test_env_is_read_at_call_time(self) -> None:
        first = self.temp_path("first.db")
        second = self.temp_path("second.db")
        os.environ[database.DB_PATH_ENV_VAR] = str(first)
        self.assertEqual(database.resolve_db_path(), first)
        os.environ[database.DB_PATH_ENV_VAR] = str(second)
        self.assertEqual(database.resolve_db_path(), second)

    def test_env_override_initializes_only_that_db(self) -> None:
        env_db = self.temp_path("nested") / "uat.db"
        before = dev_db_state()
        os.environ[database.DB_PATH_ENV_VAR] = str(env_db)

        database.init_db()

        self.assertTrue(env_db.exists())
        self.assertEqual(database.resolve_db_path(), env_db)
        with closing(database.connect()) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], migrations.SCHEMA_VERSION
            )
        # 默认参数经 storage 也必须落在覆盖路径上。
        self.assertEqual(storage.list_materials(), [])
        self.assertEqual(dev_db_state(), before)


class ExplicitPriorityTest(RuntimeDbPathTestBase):
    def test_explicit_path_beats_env(self) -> None:
        env_db = self.temp_path("env.db")
        explicit_db = self.temp_path("explicit.db")
        os.environ[database.DB_PATH_ENV_VAR] = str(env_db)

        self.assertEqual(database.resolve_db_path(explicit_db), explicit_db)

        database.init_db(explicit_db)
        with closing(database.connect(explicit_db)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], migrations.SCHEMA_VERSION
            )
        self.assertTrue(explicit_db.exists())
        self.assertFalse(env_db.exists())


class IsolationTest(RuntimeDbPathTestBase):
    def test_env_selected_dbs_stay_isolated(self) -> None:
        db_a = self.temp_path("a.db")
        db_b = self.temp_path("b.db")

        os.environ[database.DB_PATH_ENV_VAR] = str(db_a)
        database.init_db()
        review_a = storage.create_review("review-a", "rubric_demo", 1)

        os.environ[database.DB_PATH_ENV_VAR] = str(db_b)
        database.init_db()
        review_b = storage.create_review("review-b", "rubric_demo", 1)

        self.assertEqual([review.title for review in storage.list_reviews(db_a)], ["review-a"])
        self.assertEqual([review.title for review in storage.list_reviews(db_b)], ["review-b"])
        self.assertEqual([review.title for review in storage.list_reviews()], ["review-b"])
        self.assertIsNone(storage.get_review_detail(review_a.id, db_b))
        self.assertIsNone(storage.get_review_detail(review_b.id, db_a))


class MigrationOnOverridePathTest(RuntimeDbPathTestBase):
    def test_migration_initializes_override_path_and_rejects_future_version(self) -> None:
        env_db = self.temp_path("migrations") / "uat.db"
        os.environ[database.DB_PATH_ENV_VAR] = str(env_db)

        database.init_db()
        database.init_db()  # 幂等：已有当前版本再启动不改写

        with closing(database.connect()) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], migrations.SCHEMA_VERSION
            )

        with closing(sqlite3.connect(env_db)) as connection, connection:
            connection.execute(f"PRAGMA user_version = {migrations.SCHEMA_VERSION + 1}")

        with self.assertRaises(migrations.UnsupportedSchemaVersion):
            database.init_db()

        with closing(sqlite3.connect(env_db)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                migrations.SCHEMA_VERSION + 1,
            )


if __name__ == "__main__":
    unittest.main()
