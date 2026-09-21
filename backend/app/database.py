"""SQLite 连接配置与初始化入口；不包含任何业务读写。

运行时配置：
- PREFLIGHT_DB_PATH 环境变量可把数据库指向任意位置（开发/测试/UAT/部署通用）。
- 解析优先级：显式 db_path 参数 > PREFLIGHT_DB_PATH > DEFAULT_DB_PATH；环境变量在调用时读取，
  不在 import 时固化，保证同一进程内可覆盖。
- connect：统一 row_factory 与显式外键开启。
- init_db：进程/测试的初始化入口，委托 migrations.bootstrap 在单一事务内完成
  schema 创建、版本检查与迁移。
业务读取/原子写入留在 storage.py；这里不 import storage、不 import parser。
"""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from . import migrations

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "preflight.db"
DB_PATH_ENV_VAR = "PREFLIGHT_DB_PATH"


def resolve_db_path(explicit_path: Path | str | None = None) -> Path:
    """按 显式参数 > PREFLIGHT_DB_PATH > DEFAULT_DB_PATH 解析数据库路径。"""
    if explicit_path is not None:
        return Path(explicit_path)
    env_path = os.environ.get(DB_PATH_ENV_VAR)
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def _runtime_db_path(db_path: Path | None) -> Path:
    """storage 各函数的默认参数在 import 时固化了 DEFAULT_DB_PATH；该值代表“未显式指定”。"""
    if db_path is None or Path(db_path) == DEFAULT_DB_PATH:
        return resolve_db_path()
    return Path(db_path)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """打开连接并显式启用外键（SQLite 默认不启用）。"""
    path = _runtime_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: Path | None = None) -> None:
    with closing(connect(db_path)) as connection:
        migrations.bootstrap(connection)
