"""SQLite 持久化：Material 1 → N Blocks，原子保存；不用 ORM、不做迁移、不写业务外键以外的表。

表结构只服务当前 iteration：
- materials：材料身份与文件元信息，主键持久稳定。
- blocks：Block 文本与 line locator；material_id 外键指向 materials。
- recent_material：单行指针，指向最后一次成功保存的材料。
- evidence_annotations：引用真实 Block 的一段原文；material_id/block_id 双外键（CASCADE）。
- material_rubric_bindings：材料 ↔ 只读评分标准绑定，每份材料最多一条。
- criterion_evidence_links：人工判断“引用与某项评分要求相关”（adjudication 层）；双外键 CASCADE。
- agent_proposals / proposal_candidates：单 criterion AI 预检及其候选；候选须过验证门，accept 原子物化。
- reviews / review_materials：一次评审绑定一个评分标准版本，成员引用已保存材料（不复制内容）。
"""
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contracts import (
    AgentProposal,
    Block,
    CriterionEvidenceLink,
    EditableSource,
    EvidenceAnnotation,
    Locator,
    MarkdownPreview,
    MaterialRevision,
    MaterialSummary,
    ProposalAcceptance,
    ProposalCandidate,
    Review,
    ReviewDetail,
    ReviewMaterialEntry,
    RevisionChild,
    RevisionContext,
    RevisionParent,
    RubricBinding,
    SavedMaterial,
    Span,
)
from .evidence import QuoteNotFound, resolve_span

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


class InvalidCandidate(Exception):
    """候选未通过验证门，不能 accept（400 invalid_candidate）。"""

    def __init__(self, message: str = "候选未通过验证，不能接受") -> None:
        self.message = message
        super().__init__(message)


class CandidateAlreadyReviewed(StorageConflict):
    code = "candidate_already_reviewed"


class ParentNotInReview(StorageConflict):
    """Revision 带 review_id 时，父材料必须先在该 Review 中。"""

    code = "parent_not_in_review"


class RevisionReviewMissing(StorageConflict):
    """事务内复查发现 Review 已不存在（极小竞态）。"""

    code = "review_not_found"


class RevisionParentConflict(StorageConflict):
    """child 最多一个 parent；relation 创建后不可修改。"""

    code = "revision_parent_conflict"


@dataclass(frozen=True)
class CandidateInput:
    """写入前的候选输入（来自 LLM 解析层）；验证由 save_agent_proposal 完成。"""

    block_id: str
    quote: str
    rationale: str
    risk_note: str | None = None

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
CREATE TABLE IF NOT EXISTS agent_proposals (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    criterion_id TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    rubric_revision INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    raw_response TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposal_candidates (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES agent_proposals(id) ON DELETE CASCADE,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    block_id TEXT NOT NULL,
    quote TEXT NOT NULL,
    rationale TEXT NOT NULL,
    risk_note TEXT,
    validation_status TEXT NOT NULL,
    validation_code TEXT,
    review_status TEXT NOT NULL,
    reject_reason TEXT,
    created_annotation_id TEXT,
    created_link_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (proposal_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_proposal_candidates_material ON proposal_candidates(material_id);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    rubric_revision INTEGER NOT NULL CHECK (rubric_revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_materials (
    review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (review_id, material_id)
);
CREATE INDEX IF NOT EXISTS idx_review_materials_material ON review_materials(material_id);
CREATE TABLE IF NOT EXISTS material_revisions (
    child_material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
    parent_material_id TEXT NOT NULL,
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


def _insert_material_with_blocks(
    connection: sqlite3.Connection, preview: MarkdownPreview, material_id: str, created_at: str
) -> list[Block]:
    """connection-aware：material + blocks + recent 指针；调用方负责事务与提交。"""
    block_ids = [f"{material_id}-blk-{block.ordinal}" for block in preview.blocks]
    saved_blocks = [
        Block(id=block_id, document_id=material_id, ordinal=block.ordinal, text=block.text, locator=block.locator)
        for block, block_id in zip(preview.blocks, block_ids)
    ]
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
    return saved_blocks


def _set_binding(
    connection: sqlite3.Connection, material_id: str, rubric_id: str, rubric_revision: int, created_at: str
) -> None:
    """connection-aware：单条绑定插入；冲突与兼容性检查由调用方负责。"""
    connection.execute(
        "INSERT INTO material_rubric_bindings (material_id, rubric_id, rubric_revision, created_at)"
        " VALUES (?, ?, ?, ?)",
        (material_id, rubric_id, rubric_revision, created_at),
    )


def _add_review_member(
    connection: sqlite3.Connection, review_id: str, material_id: str, label: str
) -> ReviewMaterialEntry:
    """connection-aware：成员追加到末尾并刷新 Review.updated_at（保留微秒）。"""
    position = connection.execute(
        "SELECT COALESCE(MAX(position) + 1, 0) FROM review_materials WHERE review_id = ?", (review_id,)
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO review_materials (review_id, material_id, label, position) VALUES (?, ?, ?, ?)",
        (review_id, material_id, label, position),
    )
    connection.execute("UPDATE reviews SET updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), review_id))
    return ReviewMaterialEntry(material_id=material_id, label=label, position=position)


def _insert_revision_relation(
    connection: sqlite3.Connection, child_material_id: str, parent_material_id: str, created_at: str
) -> MaterialRevision:
    """connection-aware：child 最多一个 parent；重复即冲突（relation 创建后不可修改）。"""
    existing = connection.execute(
        "SELECT parent_material_id FROM material_revisions WHERE child_material_id = ?", (child_material_id,)
    ).fetchone()
    if existing is not None:
        raise RevisionParentConflict(
            "该材料已有 parent，不能再建立第二个 parent",
            [f"child={child_material_id}", f"existing_parent={existing['parent_material_id']}"],
        )
    connection.execute(
        "INSERT INTO material_revisions (child_material_id, parent_material_id, created_at) VALUES (?, ?, ?)",
        (child_material_id, parent_material_id, created_at),
    )
    return MaterialRevision(
        child_material_id=child_material_id, parent_material_id=parent_material_id, created_at=created_at
    )


def save_material(preview: MarkdownPreview, db_path: Path = DEFAULT_DB_PATH) -> SavedMaterial:
    """把一次重新解析过的预览原子保存为新材料；失败不留下任何行。"""
    material_id = f"mat_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    with closing(connect(db_path)) as connection, connection:
        saved_blocks = _insert_material_with_blocks(connection, preview, material_id, created_at)

    return SavedMaterial(
        id=material_id,
        filename=preview.filename,
        size_bytes=preview.size_bytes,
        sha256=preview.sha256,
        line_count=preview.line_count,
        created_at=created_at,
        blocks=saved_blocks,
    )


def create_material_revision(
    parent_material_id: str,
    preview: MarkdownPreview,
    review_id: str | None = None,
    label: str | None = None,
    inherit_binding: tuple[str, int] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[SavedMaterial, MaterialRevision] | None:
    """从已保存父材料派生一份全新 Material（旧材料不可变，不复制/重定向旧引用）。

    单事务：校验 parent/Review 成员 → 新 material + blocks → revision relation →
    可选 binding → 可选 Review membership + updated_at → recent 指针。
    Review 路径的 binding 取事务内读到的 Review 精确 rubric；无 Review 时由 inherit_binding 传入父绑定。
    父材料不存在返回 None；Review/成员校验失败抛 StorageConflict，整体 rollback。
    """
    material_id = f"mat_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    with closing(connect(db_path)) as connection, connection:
        parent = connection.execute("SELECT 1 FROM materials WHERE id = ?", (parent_material_id,)).fetchone()
        if parent is None:
            return None
        binding = inherit_binding
        member_label: str | None = None
        if review_id is not None:
            review = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if review is None:
                raise RevisionReviewMissing("找不到该 Review", [f"id={review_id}"])
            member = connection.execute(
                "SELECT 1 FROM review_materials WHERE review_id = ? AND material_id = ?",
                (review_id, parent_material_id),
            ).fetchone()
            if member is None:
                raise ParentNotInReview(
                    "父材料不在该 Review 中",
                    [f"review_id={review_id}", f"material_id={parent_material_id}"],
                )
            binding = (review["rubric_id"], review["rubric_revision"])
            member_label = label if label is not None else preview.filename
        saved_blocks = _insert_material_with_blocks(connection, preview, material_id, created_at)
        revision = _insert_revision_relation(connection, material_id, parent_material_id, created_at)
        if binding is not None:
            _set_binding(connection, material_id, binding[0], binding[1], created_at)
        if review_id is not None and member_label is not None:
            _add_review_member(connection, review_id, material_id, member_label)

    return (
        SavedMaterial(
            id=material_id,
            filename=preview.filename,
            size_bytes=preview.size_bytes,
            sha256=preview.sha256,
            line_count=preview.line_count,
            created_at=created_at,
            blocks=saved_blocks,
        ),
        revision,
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


def delete_material(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """删除材料本体；blocks/annotations/links/proposals 由 FK CASCADE 清理。

    recent_material 指针没有 CASCADE：同一事务内先改指到仍然存在的最近材料（没有就清空），
    再删材料；否则 FK 约束会挡住删除，指针也不会指向已删除的行。
    材料不存在返回 False（调用方转 404）。
    """
    with closing(connect(db_path)) as connection, connection:
        # 先记下该材料参与的 Review；删材料后由 FK CASCADE 清成员，再刷新受影响 Review 的 updated_at。
        affected_reviews = [
            row["review_id"]
            for row in connection.execute(
                "SELECT review_id FROM review_materials WHERE material_id = ?", (material_id,)
            ).fetchall()
        ]
        cleared = connection.execute(
            "DELETE FROM recent_material WHERE singleton = 1 AND material_id = ?",
            (material_id,),
        ).rowcount
        deleted = connection.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        if deleted.rowcount == 0:
            return False
        if affected_reviews:
            # updated_at 必须可观测地变化，故保留微秒。
            now = datetime.now(timezone.utc).isoformat()
            connection.executemany(
                "UPDATE reviews SET updated_at = ? WHERE id = ?",
                [(now, review_id) for review_id in affected_reviews],
            )
        if cleared:
            successor = connection.execute(
                "SELECT id FROM materials ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            if successor is not None:
                connection.execute(
                    "INSERT INTO recent_material (singleton, material_id) VALUES (1, ?)", (successor["id"],)
                )
    return True


def get_revision_context(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> RevisionContext | None:
    """只读直接 parent/children；材料不存在返回 None。parent 删除后 parent_available=false。"""
    with closing(connect(db_path)) as connection:
        material = connection.execute("SELECT 1 FROM materials WHERE id = ?", (material_id,)).fetchone()
        if material is None:
            return None
        relation = connection.execute(
            "SELECT r.parent_material_id, (m.id IS NOT NULL) AS parent_available"
            " FROM material_revisions r LEFT JOIN materials m ON m.id = r.parent_material_id"
            " WHERE r.child_material_id = ?",
            (material_id,),
        ).fetchone()
        parent = None
        if relation is not None:
            parent = RevisionParent(
                material_id=relation["parent_material_id"],
                parent_available=bool(relation["parent_available"]),
            )
        children_rows = connection.execute(
            "SELECT r.child_material_id, r.created_at, (m.id IS NOT NULL) AS available"
            " FROM material_revisions r LEFT JOIN materials m ON m.id = r.child_material_id"
            " WHERE r.parent_material_id = ?"
            " ORDER BY r.created_at ASC, r.child_material_id ASC",
            (material_id,),
        ).fetchall()
    return RevisionContext(
        material_id=material_id,
        parent=parent,
        children=[
            RevisionChild(
                material_id=row["child_material_id"],
                available=bool(row["available"]),
                created_at=row["created_at"],
            )
            for row in children_rows
        ],
    )


def get_editable_source(material_id: str, db_path: Path = DEFAULT_DB_PATH) -> EditableSource | None:
    """按真实 line_number/line_count 重建 Markdown（LF、补空行）；不承诺 BOM/CRLF/末尾换行。"""
    material = get_material(material_id, db_path=db_path)
    if material is None:
        return None
    size = max([material.line_count] + [block.locator.index for block in material.blocks])
    lines = [""] * size
    for block in material.blocks:
        lines[block.locator.index - 1] = block.text
    return EditableSource(
        material_id=material.id,
        format="md",
        text="\n".join(lines),
        normalization="lf",
    )


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


def _ensure_binding_compatible_with_memberships(
    connection: sqlite3.Connection, material_id: str, rubric_id: str, rubric_revision: int
) -> None:
    """connection-aware 单一 invariant：材料所属 Review 的标准版本必须与将绑定的版本一致。

    历史数据可能留下「已在 Review A、却未绑定」的材料；auto first-binding 与显式
    bind 都调用本 guard，冲突即抛 BindingConflict，由调用方事务整体回滚。
    """
    conflicts = connection.execute(
        "SELECT r.id AS review_id, r.rubric_id, r.rubric_revision FROM review_materials rm"
        " JOIN reviews r ON r.id = rm.review_id WHERE rm.material_id = ?"
        " AND (r.rubric_id != ? OR r.rubric_revision != ?)",
        (material_id, rubric_id, rubric_revision),
    ).fetchall()
    if conflicts:
        raise BindingConflict(
            "该材料已加入使用其他评分标准版本的 Review，须先移除不兼容的 Review membership 后再绑定",
            [f"review_id={row['review_id']} 使用 {row['rubric_id']} rev{row['rubric_revision']}" for row in conflicts],
        )


def bind_material_rubric(
    material_id: str, rubric_id: str, rubric_revision: int, db_path: Path = DEFAULT_DB_PATH
) -> tuple[RubricBinding, bool] | None:
    """返回 (binding, created)；同版本重复绑定幂等返回已有，换绑抛 BindingConflict；材料不存在返回 None。

    首次绑定前反向检查该材料所属全部 Review（与 auto first-binding 共用同一 guard）：
    任一 Review 标准与本次绑定不同即抛 BindingConflict（保持未绑定，不动 membership）。
    检查与写入在同一连接事务内完成。
    """
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
        _ensure_binding_compatible_with_memberships(connection, material_id, rubric_id, rubric_revision)
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


def _candidate_from_row(row: sqlite3.Row) -> ProposalCandidate:
    return ProposalCandidate(
        id=row["id"],
        proposal_id=row["proposal_id"],
        ordinal=row["ordinal"],
        block_id=row["block_id"],
        quote=row["quote"],
        rationale=row["rationale"],
        risk_note=row["risk_note"],
        validation_status=row["validation_status"],
        validation_code=row["validation_code"],
        review_status=row["review_status"],
        reject_reason=row["reject_reason"],
        created_annotation_id=row["created_annotation_id"],
        created_link_id=row["created_link_id"],
        created_at=row["created_at"],
    )


def _proposal_from_rows(proposal: sqlite3.Row, candidates: list[sqlite3.Row]) -> AgentProposal:
    return AgentProposal(
        id=proposal["id"],
        material_id=proposal["material_id"],
        criterion_id=proposal["criterion_id"],
        rubric_id=proposal["rubric_id"],
        rubric_revision=proposal["rubric_revision"],
        provider=proposal["provider"],
        model=proposal["model"],
        prompt_version=proposal["prompt_version"],
        status=proposal["status"],
        error=proposal["error"],
        created_at=proposal["created_at"],
        candidates=[_candidate_from_row(row) for row in candidates],
    )


def save_agent_proposal(
    material: SavedMaterial,
    criterion_id: str,
    rubric_id: str,
    rubric_revision: int,
    provider: str,
    model: str,
    prompt_version: str,
    status: str,
    error: str | None,
    raw_response: str | None,
    candidates: list[CandidateInput],
    db_path: Path = DEFAULT_DB_PATH,
) -> AgentProposal:
    """验证每个候选（block 属于材料 + quote 经 resolve_span）后，单事务写入两张表。"""
    blocks = {block.id: block for block in material.blocks}
    proposal_id = f"ap_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prepared: list[tuple[str, int, CandidateInput, str, str | None]] = []
    for ordinal, candidate in enumerate(candidates):
        block = blocks.get(candidate.block_id)
        if block is None:
            validation_status, validation_code = "invalid", "block_not_found"
        else:
            try:
                resolve_span(block.text, candidate.quote)
            except QuoteNotFound:
                validation_status, validation_code = "invalid", "quote_not_found"
            else:
                validation_status, validation_code = "passed", None
        prepared.append((f"apc_{uuid.uuid4().hex}", ordinal, candidate, validation_status, validation_code))

    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO agent_proposals"
            " (id, material_id, criterion_id, rubric_id, rubric_revision, provider, model, prompt_version,"
            "  status, error, raw_response, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (proposal_id, material.id, criterion_id, rubric_id, rubric_revision, provider, model,
             prompt_version, status, error, raw_response, created_at),
        )
        for candidate_id, ordinal, candidate, validation_status, validation_code in prepared:
            connection.execute(
                "INSERT INTO proposal_candidates"
                " (id, proposal_id, material_id, ordinal, block_id, quote, rationale, risk_note,"
                "  validation_status, validation_code, review_status, reject_reason,"
                "  created_annotation_id, created_link_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unreviewed', NULL, NULL, NULL, ?)",
                (candidate_id, proposal_id, material.id, ordinal, candidate.block_id, candidate.quote,
                 candidate.rationale, candidate.risk_note, validation_status, validation_code, created_at),
            )

    stored = get_agent_proposal(proposal_id, db_path)
    if stored is None:
        raise RuntimeError("proposal 写入后无法读回")
    return stored


def get_agent_proposal(proposal_id: str, db_path: Path = DEFAULT_DB_PATH) -> AgentProposal | None:
    with closing(connect(db_path)) as connection:
        proposal = connection.execute("SELECT * FROM agent_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if proposal is None:
            return None
        candidates = connection.execute(
            "SELECT * FROM proposal_candidates WHERE proposal_id = ? ORDER BY ordinal ASC", (proposal_id,)
        ).fetchall()
    return _proposal_from_rows(proposal, candidates)


def list_agent_proposals(
    material_id: str, criterion_id: str | None = None, db_path: Path = DEFAULT_DB_PATH
) -> list[AgentProposal]:
    query = "SELECT * FROM agent_proposals WHERE material_id = ?"
    params: list[str] = [material_id]
    if criterion_id:
        query += " AND criterion_id = ?"
        params.append(criterion_id)
    query += " ORDER BY rowid DESC"
    with closing(connect(db_path)) as connection:
        proposals = connection.execute(query, params).fetchall()
        result: list[AgentProposal] = []
        for proposal in proposals:
            candidates = connection.execute(
                "SELECT * FROM proposal_candidates WHERE proposal_id = ? ORDER BY ordinal ASC", (proposal["id"],)
            ).fetchall()
            result.append(_proposal_from_rows(proposal, candidates))
    return result


def accept_candidate(
    material_id: str, candidate_id: str, db_path: Path = DEFAULT_DB_PATH
) -> ProposalAcceptance | None:
    """单事务：校验候选 → 语义查重 → span 复算 → 物化 annotation + link（agent）→ 回写候选。

    任一步失败全部回滚；候选不存在/跨材料返回 None。
    """
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            "SELECT c.*, p.criterion_id AS proposal_criterion_id, p.rubric_id AS proposal_rubric_id,"
            " p.rubric_revision AS proposal_rubric_revision, b.text AS block_text"
            " FROM proposal_candidates c"
            " JOIN agent_proposals p ON p.id = c.proposal_id"
            " LEFT JOIN blocks b ON b.id = c.block_id"
            " WHERE c.id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None or row["material_id"] != material_id:
            return None
        if row["validation_status"] != "passed":
            raise InvalidCandidate("候选未通过验证门，不能接受")
        if row["review_status"] != "unreviewed":
            raise CandidateAlreadyReviewed("候选已被裁决")
        block_text = row["block_text"]
        if block_text is None:
            raise SpanMismatch("候选引用的 Block 已不存在")
        try:
            start, end = resolve_span(block_text, row["quote"])
        except QuoteNotFound as exc:
            raise SpanMismatch(str(exc)) from exc
        duplicate = connection.execute(
            "SELECT 1 FROM criterion_evidence_links l"
            " JOIN evidence_annotations a ON a.id = l.annotation_id"
            " WHERE l.material_id = ? AND l.criterion_id = ? AND a.block_id = ? AND a.quote = ?",
            (material_id, row["proposal_criterion_id"], row["block_id"], row["quote"]),
        ).fetchone()
        if duplicate is not None:
            raise DuplicateLink("该原文已关联此评分要求")

        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        annotation_id = f"ev_{uuid.uuid4().hex}"
        link_id = f"cel_{uuid.uuid4().hex}"
        connection.execute(
            "INSERT INTO evidence_annotations"
            " (id, material_id, block_id, start, end, quote, note, proposed_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, 'agent', ?)",
            (annotation_id, material_id, row["block_id"], start, end, row["quote"], created_at),
        )
        connection.execute(
            "INSERT INTO criterion_evidence_links"
            " (id, material_id, annotation_id, rubric_id, rubric_revision, criterion_id, rationale,"
            "  proposed_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'agent', ?)",
            (link_id, material_id, annotation_id, row["proposal_rubric_id"], row["proposal_rubric_revision"],
             row["proposal_criterion_id"], row["rationale"], created_at),
        )
        connection.execute(
            "UPDATE proposal_candidates"
            " SET review_status = 'accepted', created_annotation_id = ?, created_link_id = ? WHERE id = ?",
            (annotation_id, link_id, candidate_id),
        )

    return ProposalAcceptance(
        annotation=EvidenceAnnotation(
            id=annotation_id,
            material_id=material_id,
            block_id=row["block_id"],
            source=Span(block_id=row["block_id"], start=start, end=end, quote=row["quote"]),
            note=None,
            proposed_by="agent",
            created_at=created_at,
        ),
        link=CriterionEvidenceLink(
            id=link_id,
            material_id=material_id,
            annotation_id=annotation_id,
            rubric_id=row["proposal_rubric_id"],
            rubric_revision=row["proposal_rubric_revision"],
            criterion_id=row["proposal_criterion_id"],
            rationale=row["rationale"],
            proposed_by="agent",
            created_at=created_at,
        ),
    )


def reject_candidate(
    material_id: str, candidate_id: str, reason: str | None = None, db_path: Path = DEFAULT_DB_PATH
) -> ProposalCandidate | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            "SELECT * FROM proposal_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None or row["material_id"] != material_id:
            return None
        if row["review_status"] != "unreviewed":
            raise CandidateAlreadyReviewed("候选已被裁决")
        connection.execute(
            "UPDATE proposal_candidates SET review_status = 'rejected', reject_reason = ? WHERE id = ?",
            (reason, candidate_id),
        )
        updated = connection.execute(
            "SELECT * FROM proposal_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    return _candidate_from_row(updated)


def _review_from_row(row: sqlite3.Row) -> Review:
    return Review(
        id=row["id"],
        title=row["title"],
        rubric_id=row["rubric_id"],
        rubric_revision=row["rubric_revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _review_material_from_row(row: sqlite3.Row) -> ReviewMaterialEntry:
    return ReviewMaterialEntry(material_id=row["material_id"], label=row["label"], position=row["position"])


def create_review(
    title: str, rubric_id: str, rubric_revision: int, db_path: Path = DEFAULT_DB_PATH
) -> Review:
    """新建 Review；rubric 存在性由 API 层用 rubric_store 校验。"""
    review_id = f"rev_{uuid.uuid4().hex}"
    # updated_at 必须可观测地变化，故保留微秒。
    now = datetime.now(timezone.utc).isoformat()
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO reviews (id, title, rubric_id, rubric_revision, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, title, rubric_id, rubric_revision, now, now),
        )
    return Review(
        id=review_id,
        title=title,
        rubric_id=rubric_id,
        rubric_revision=rubric_revision,
        created_at=now,
        updated_at=now,
    )


def list_reviews(db_path: Path = DEFAULT_DB_PATH) -> list[Review]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute("SELECT * FROM reviews ORDER BY created_at DESC, rowid DESC").fetchall()
    return [_review_from_row(row) for row in rows]


def get_review_detail(review_id: str, db_path: Path = DEFAULT_DB_PATH) -> ReviewDetail | None:
    with closing(connect(db_path)) as connection:
        review = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if review is None:
            return None
        materials = connection.execute(
            "SELECT * FROM review_materials WHERE review_id = ? ORDER BY position ASC, material_id ASC",
            (review_id,),
        ).fetchall()
    return ReviewDetail(
        **_review_from_row(review).model_dump(),
        materials=[_review_material_from_row(row) for row in materials],
    )


def rename_review(review_id: str, title: str, db_path: Path = DEFAULT_DB_PATH) -> Review | None:
    """只改 title；不存在返回 None。rubric 绑定不可通过本函数变更。"""
    # updated_at 必须可观测地变化，故保留微秒。
    now = datetime.now(timezone.utc).isoformat()
    with closing(connect(db_path)) as connection, connection:
        updated = connection.execute(
            "UPDATE reviews SET title = ?, updated_at = ? WHERE id = ?", (title, now, review_id)
        )
        if updated.rowcount == 0:
            return None
        row = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    return _review_from_row(row)


def delete_review(review_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """删除 Review 本体；review_materials 由 FK CASCADE 清理，绝不动 materials。"""
    with closing(connect(db_path)) as connection, connection:
        deleted = connection.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    return deleted.rowcount > 0


def upsert_review_material(
    review_id: str,
    material_id: str,
    label: str | None,
    position: int | None,
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[ReviewMaterialEntry, bool] | None:
    """单事务 upsert 成员：返回 (entry, created)；review/material 不存在返回 None。

    首次 binding（普通用户不理解 binding，由 Wizard 的「材料 + 标准」确认触发）：
    材料未绑定 → 在同一事务内绑定本 Review 的标准版本；已绑定相同版本 → 保留原绑定；
    已绑定其他版本 → BindingConflict（409），绝不自动改绑定、不覆盖历史绑定。
    label 缺省取 filename，position 缺省追加到末尾；更新时缺省保持原值。
    """
    with closing(connect(db_path)) as connection, connection:
        review = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if review is None:
            return None
        material = connection.execute(
            "SELECT filename FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
        if material is None:
            return None
        binding = connection.execute(
            "SELECT rubric_id, rubric_revision FROM material_rubric_bindings WHERE material_id = ?",
            (material_id,),
        ).fetchone()
        if binding is not None and (
            binding["rubric_id"] != review["rubric_id"]
            or binding["rubric_revision"] != review["rubric_revision"]
        ):
            raise BindingConflict(
                "该材料已绑定其他评分标准版本，不允许在 Review 中暗中换绑",
                [f"已绑定 {binding['rubric_id']} rev{binding['rubric_revision']}"],
            )
        if binding is None:
            # Legacy 数据可能已有「已属于其他 Review、却未绑定」的材料；先过共享 guard，
            # 冲突时整事务回滚：材料保持未绑定、旧 membership 不变、新 membership 不创建。
            _ensure_binding_compatible_with_memberships(
                connection, material_id, review["rubric_id"], review["rubric_revision"]
            )
            _set_binding(
                connection,
                material_id,
                review["rubric_id"],
                review["rubric_revision"],
                datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
        existing = connection.execute(
            "SELECT * FROM review_materials WHERE review_id = ? AND material_id = ?",
            (review_id, material_id),
        ).fetchone()
        # updated_at 必须可观测地变化，故保留微秒。
        now = datetime.now(timezone.utc).isoformat()
        if existing is None:
            final_label = label if label is not None else material["filename"]
            if position is None:
                position = connection.execute(
                    "SELECT COALESCE(MAX(position) + 1, 0) FROM review_materials WHERE review_id = ?",
                    (review_id,),
                ).fetchone()[0]
            connection.execute(
                "INSERT INTO review_materials (review_id, material_id, label, position) VALUES (?, ?, ?, ?)",
                (review_id, material_id, final_label, position),
            )
            final_position = position
            created = True
        else:
            final_label = label if label is not None else existing["label"]
            final_position = position if position is not None else existing["position"]
            connection.execute(
                "UPDATE review_materials SET label = ?, position = ? WHERE review_id = ? AND material_id = ?",
                (final_label, final_position, review_id, material_id),
            )
            created = False
        connection.execute("UPDATE reviews SET updated_at = ? WHERE id = ?", (now, review_id))
    return ReviewMaterialEntry(material_id=material_id, label=final_label, position=final_position), created


def remove_review_material(review_id: str, material_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """移除成员关系并刷新 Review.updated_at；不存在返回 False。绝不动 materials。"""
    # updated_at 必须可观测地变化，故保留微秒。
    now = datetime.now(timezone.utc).isoformat()
    with closing(connect(db_path)) as connection, connection:
        deleted = connection.execute(
            "DELETE FROM review_materials WHERE review_id = ? AND material_id = ?", (review_id, material_id)
        )
        if deleted.rowcount == 0:
            return False
        connection.execute("UPDATE reviews SET updated_at = ? WHERE id = ?", (now, review_id))
    return True
