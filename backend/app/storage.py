"""SQLite 持久化：Material 1 → N Blocks，原子保存；不用 ORM、不做迁移、不写业务外键以外的表。

表结构只服务当前 iteration：
- materials：材料身份与文件元信息，主键持久稳定。
- blocks：Block 文本与 line locator；material_id 外键指向 materials。
- recent_material：单行指针，指向最后一次成功保存的材料。
- evidence_annotations：引用真实 Block 的一段原文；material_id/block_id 双外键（CASCADE）。
- material_rubric_bindings：材料 ↔ 只读评分标准绑定，每份材料最多一条。
- criterion_evidence_links：人工判断“引用与某项评分要求相关”（adjudication 层）；双外键 CASCADE。
"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .contracts import (
    Block,
    CriterionEvidenceLink,
    EvidenceAnnotation,
    Locator,
    MarkdownPreview,
    MaterialSummary,
    RubricBinding,
    SavedMaterial,
    Span,
)
from .evidence import resolve_span

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "preflight.db"


class StorageConflict(Exception):
    """状态冲突（409）；code 由 API 层直接返回。"""

    code = "conflict"

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class BindingConflict(StorageConflict):
    code = "binding_conflict"


class RubricNotBound(StorageConflict):
    code = "rubric_not_bound"


class DuplicateLink(StorageConflict):
    code = "duplicate_link"


class SpanMismatch(Exception):
    """annotation 存下的 span 与 Block 原文不再一致（防篡改/失效）。"""

    def __init__(self, message: str = "annotation span 与原文不一致") -> None:
        self.message = message
        super().__init__(message)

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
CREATE TABLE IF NOT EXISTS material_rubric_bindings (
    material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
    rubric_id TEXT NOT NULL,
    rubric_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS criterion_evidence_links (
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
CREATE INDEX IF NOT EXISTS idx_criterion_evidence_links_material ON criterion_evidence_links(material_id);
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


def delete_evidence_annotation(material_id: str, annotation_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """WHERE 同时限定 material，防跨材料探测；关联由 FK CASCADE 清理。"""
    with closing(connect(db_path)) as connection, connection:
        deleted = connection.execute(
            "DELETE FROM evidence_annotations WHERE id = ? AND material_id = ?", (annotation_id, material_id)
        )
    return deleted.rowcount > 0


def _binding_from_row(row: sqlite3.Row) -> RubricBinding:
    return RubricBinding(
        material_id=row["material_id"],
        rubric_id=row["rubric_id"],
        rubric_revision=row["rubric_revision"],
        created_at=row["created_at"],
    )


def get_binding(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> RubricBinding | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM material_rubric_bindings WHERE material_id = ?", (material_id,)
        ).fetchone()
    return _binding_from_row(row) if row is not None else None


def bind_material_rubric(
    material_id: str, rubric_id: str, rubric_revision: int, db_path: Path = DEFAULT_DB_PATH
) -> tuple[RubricBinding, bool] | None:
    """返回 (binding, created)；同版本重复绑定幂等返回已有，换绑抛 BindingConflict；材料不存在返回 None。"""
    with closing(connect(db_path)) as connection, connection:
        material = connection.execute("SELECT 1 FROM materials WHERE id = ?", (material_id,)).fetchone()
        if material is None:
            return None
        existing = connection.execute(
            "SELECT * FROM material_rubric_bindings WHERE material_id = ?", (material_id,)
        ).fetchone()
        if existing is not None:
            if existing["rubric_id"] == rubric_id and existing["rubric_revision"] == rubric_revision:
                return _binding_from_row(existing), False
            raise BindingConflict(
                "该材料已绑定其他评分标准版本",
                [f"已绑定 {existing['rubric_id']} rev{existing['rubric_revision']}"],
            )
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        connection.execute(
            "INSERT INTO material_rubric_bindings (material_id, rubric_id, rubric_revision, created_at)"
            " VALUES (?, ?, ?, ?)",
            (material_id, rubric_id, rubric_revision, created_at),
        )
    return RubricBinding(
        material_id=material_id, rubric_id=rubric_id, rubric_revision=rubric_revision, created_at=created_at
    ), True


def _link_from_row(row: sqlite3.Row) -> CriterionEvidenceLink:
    return CriterionEvidenceLink(
        id=row["id"],
        material_id=row["material_id"],
        annotation_id=row["annotation_id"],
        rubric_id=row["rubric_id"],
        rubric_revision=row["rubric_revision"],
        criterion_id=row["criterion_id"],
        rationale=row["rationale"],
        proposed_by=row["proposed_by"],
        created_at=row["created_at"],
    )


def create_link(
    material_id: str,
    annotation_id: str,
    criterion_id: str,
    rationale: str,
    proposed_by: str = "human",
    db_path: Path = DEFAULT_DB_PATH,
) -> CriterionEvidenceLink | None:
    """单事务：查 annotation（含 block 文本）→ 绑定 → spot-check span → 查重 → 插入。

    annotation 不存在或不属于该材料返回 None；未绑定抛 RubricNotBound；
    span 复验失败抛 SpanMismatch；重复关联抛 DuplicateLink。
    """
    with closing(connect(db_path)) as connection, connection:
        annotation = connection.execute(
            "SELECT a.id, a.material_id, a.block_id, a.start, a.end, a.quote, b.text AS block_text"
            " FROM evidence_annotations a JOIN blocks b ON b.id = a.block_id WHERE a.id = ?",
            (annotation_id,),
        ).fetchone()
        if annotation is None or annotation["material_id"] != material_id:
            return None
        binding = connection.execute(
            "SELECT * FROM material_rubric_bindings WHERE material_id = ?", (material_id,)
        ).fetchone()
        if binding is None:
            raise RubricNotBound("该材料尚未绑定评分标准")
        start, end, quote = annotation["start"], annotation["end"], annotation["quote"]
        block_text = annotation["block_text"]
        if not (0 <= start < end <= len(block_text)) or block_text[start:end] != quote:
            raise SpanMismatch()
        duplicate = connection.execute(
            "SELECT 1 FROM criterion_evidence_links WHERE annotation_id = ? AND criterion_id = ? AND rubric_revision = ?",
            (annotation_id, criterion_id, binding["rubric_revision"]),
        ).fetchone()
        if duplicate is not None:
            raise DuplicateLink("该引用已关联此评分要求")
        link_id = f"cel_{uuid.uuid4().hex}"
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        connection.execute(
            "INSERT INTO criterion_evidence_links"
            " (id, material_id, annotation_id, rubric_id, rubric_revision, criterion_id, rationale, proposed_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                link_id,
                annotation["material_id"],
                annotation_id,
                binding["rubric_id"],
                binding["rubric_revision"],
                criterion_id,
                rationale,
                proposed_by,
                created_at,
            ),
        )
    return CriterionEvidenceLink(
        id=link_id,
        material_id=annotation["material_id"],
        annotation_id=annotation_id,
        rubric_id=binding["rubric_id"],
        rubric_revision=binding["rubric_revision"],
        criterion_id=criterion_id,
        rationale=rationale,
        proposed_by=proposed_by,
        created_at=created_at,
    )


def list_links(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> list[CriterionEvidenceLink]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM criterion_evidence_links WHERE material_id = ? ORDER BY rowid ASC", (material_id,)
        ).fetchall()
    return [_link_from_row(row) for row in rows]


def delete_link(material_id: str, link_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    with closing(connect(db_path)) as connection, connection:
        deleted = connection.execute(
            "DELETE FROM criterion_evidence_links WHERE id = ? AND material_id = ?", (link_id, material_id)
        )
    return deleted.rowcount > 0
