"""SQLite 持久化：Material 1 → N Blocks，原子保存；不用 ORM、不做迁移、不写业务外键以外的表。

表结构只服务当前 2B：
- materials：材料身份与文件元信息，主键持久稳定。
- blocks：Block 文本与 line locator；material_id 外键指向 materials。
- recent_material：单行指针，指向最后一次成功保存的材料。
"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .contracts import Block, Locator, MarkdownPreview, SavedMaterial

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "preflight.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    line_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocks (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    UNIQUE (material_id, ordinal)
);
CREATE TABLE IF NOT EXISTS recent_material (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    material_id TEXT NOT NULL REFERENCES materials(id)
);
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """打开连接并显式启用外键（SQLite 默认不启用）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(db_path)) as connection, connection:
        connection.executescript(_SCHEMA)


def _material_from_rows(material: sqlite3.Row, blocks: list[sqlite3.Row]) -> SavedMaterial:
    return SavedMaterial(
        id=material["id"],
        filename=material["filename"],
        size_bytes=material["size_bytes"],
        sha256=material["sha256"],
        line_count=material["line_count"],
        created_at=material["created_at"],
        blocks=[
            Block(
                id=row["id"],
                document_id=material["id"],
                ordinal=row["ordinal"],
                text=row["text"],
                locator=Locator(kind="line", index=row["line_number"], end_index=None, block_index=row["block_index"]),
            )
            for row in blocks
        ],
    )


def save_material(preview: MarkdownPreview, db_path: Path = DEFAULT_DB_PATH) -> SavedMaterial:
    """把一次重新解析过的预览原子保存为新材料；失败不留下任何行。"""
    material_id = f"mat_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    block_ids = [f"{material_id}-blk-{block.ordinal}" for block in preview.blocks]
    saved_blocks = [
        Block(id=block_id, document_id=material_id, ordinal=block.ordinal, text=block.text, locator=block.locator)
        for block, block_id in zip(preview.blocks, block_ids)
    ]

    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO materials (id, filename, size_bytes, sha256, line_count, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (material_id, preview.filename, preview.size_bytes, preview.sha256, preview.line_count, created_at),
        )
        for block, block_id in zip(preview.blocks, block_ids):
            connection.execute(
                "INSERT INTO blocks (id, material_id, ordinal, line_number, text, block_index)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (block_id, material_id, block.ordinal, block.locator.index, block.text, block.locator.block_index),
            )
        updated = connection.execute(
            "UPDATE recent_material SET material_id = ? WHERE singleton = 1", (material_id,)
        )
        if updated.rowcount == 0:
            connection.execute("INSERT INTO recent_material (singleton, material_id) VALUES (1, ?)", (material_id,))

    return SavedMaterial(
        id=material_id,
        filename=preview.filename,
        size_bytes=preview.size_bytes,
        sha256=preview.sha256,
        line_count=preview.line_count,
        created_at=created_at,
        blocks=saved_blocks,
    )


def get_material(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> SavedMaterial | None:
    with closing(connect(db_path)) as connection:
        material = connection.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if material is None:
            return None
        blocks = connection.execute(
            "SELECT * FROM blocks WHERE material_id = ? ORDER BY ordinal ASC", (material_id,)
        ).fetchall()
    return _material_from_rows(material, blocks)


def get_recent_material(db_path: Path = DEFAULT_DB_PATH) -> SavedMaterial | None:
    with closing(connect(db_path)) as connection:
        pointer = connection.execute("SELECT material_id FROM recent_material WHERE singleton = 1").fetchone()
    if pointer is None:
        return None
    return get_material(pointer["material_id"], db_path)
