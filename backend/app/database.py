"""SQLite 连接配置与初始化入口；不包含任何业务读写。

- connect：统一 row_factory 与显式外键开启。
- init_db：进程/测试的初始化入口，委托 migrations.bootstrap 在单一事务内完成
  schema 创建、版本检查与迁移。
业务读取/原子写入留在 storage.py；这里不 import storage、不 import parser。
"""
import sqlite3
from contextlib import closing
from pathlib import Path

from . import migrations

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "preflight.db"


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """打开连接并显式启用外键（SQLite 默认不启用）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(db_path)) as connection:
        migrations.bootstrap(connection)
