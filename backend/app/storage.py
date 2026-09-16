"""SQLite 持久化：Material 1 → N Blocks，原子保存；不用 ORM、不做迁移、不写业务外键以外的表。

表结构只服务当前 iteration：
- materials：材料身份与文件元信息，主键持久稳定。
- blocks：Block 文本与 line locator；material_id 外键指向 materials。
- recent_material：单行指针，指向最后一次成功保存的材料。
- evidence_annotations：引用真实 Block 的一段原文；material_id/block_id 双外键（CASCADE）。
"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .contracts import Block, EvidenceAnnotation, Locator, MarkdownPreview, MaterialSummary, SavedMaterial, Span
from .evidence import resolve_span

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
CREATE TABLE IF NOT EXISTS evidence_annotations (
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


def list_materials(db_path: Path = DEFAULT_DB_PATH) -> list[MaterialSummary]:
    """列表摘要：不返回 blocks；按保存时间倒序（同秒用 rowid 兜底）。"""
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT m.id, m.filename, m.created_at, COUNT(b.id) AS block_count"
            " FROM materials m LEFT JOIN blocks b ON b.material_id = m.id"
            " GROUP BY m.id"
            " ORDER BY m.created_at DESC, m.rowid DESC"
        ).fetchall()
    return [
        MaterialSummary(
            id=row["id"], filename=row["filename"], created_at=row["created_at"], block_count=row["block_count"]
        )
        for row in rows
    ]


def material_exists(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT 1 FROM materials WHERE id = ?", (material_id,)).fetchone()
    return row is not None


def _annotation_from_row(row: sqlite3.Row) -> EvidenceAnnotation:
    return EvidenceAnnotation(
        id=row["id"],
        material_id=row["material_id"],
        block_id=row["block_id"],
        source=Span(block_id=row["block_id"], start=row["start"], end=row["end"], quote=row["quote"]),
        note=row["note"],
        proposed_by=row["proposed_by"],
        created_at=row["created_at"],
    )


def save_evidence_annotation(
    block_id: str,
    quote: str,
    note: str | None = None,
    proposed_by: str = "human",
    db_path: Path = DEFAULT_DB_PATH,
) -> EvidenceAnnotation | None:
    """服务端解析 quote 并派生 material_id；Block 不存在返回 None，quote 未命中抛 QuoteNotFound。

    quote 校验与写入在同一连接内完成：未命中时异常回滚，库中不会留下无效引用。
    """
    with closing(connect(db_path)) as connection, connection:
        block = connection.execute("SELECT id, material_id, text FROM blocks WHERE id = ?", (block_id,)).fetchone()
        if block is None:
            return None
        start, end = resolve_span(block["text"], quote)
        annotation_id = f"ev_{uuid.uuid4().hex}"
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        connection.execute(
            "INSERT INTO evidence_annotations"
            " (id, material_id, block_id, start, end, quote, note, proposed_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (annotation_id, block["material_id"], block_id, start, end, quote, note, proposed_by, created_at),
        )
    return EvidenceAnnotation(
        id=annotation_id,
        material_id=block["material_id"],
        block_id=block_id,
        source=Span(block_id=block_id, start=start, end=end, quote=quote),
        note=note,
        proposed_by=proposed_by,
        created_at=created_at,
    )


def get_evidence_annotation(annotation_id: str, db_path: Path = DEFAULT_DB_PATH) -> EvidenceAnnotation | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM evidence_annotations WHERE id = ?", (annotation_id,)).fetchone()
    return _annotation_from_row(row) if row is not None else None


def list_evidence_annotations(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> list[EvidenceAnnotation]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM evidence_annotations WHERE material_id = ? ORDER BY rowid ASC", (material_id,)
        ).fetchall()
    return [_annotation_from_row(row) for row in rows]
