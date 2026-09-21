"""SQLite schema bootstrap、版本检查与迁移；独占 migration 事务与外键生命周期。

规则：
- `PRAGMA user_version` 是唯一版本号。version == supported → no-op；
  version > supported → 明确拒绝（不猜测未来 schema，不静默继续）。
- 一次 bootstrap 是单一原子边界：schema 创建 + legacy 重建 + foreign_key_check + 版本号写入
  全部在同一个显式 `BEGIN IMMEDIATE` 事务里；失败整体回滚，不留下临时表或半初始化库。
- 不隐式提交/回滚调用方事务：connection.in_transaction 为真时直接拒绝。
- 外键：进入前记录原状态（on/off），结束（无论成败）恢复原状态并显式复验；重建期间 FK OFF
  （该 pragma 在事务内会被静默忽略，故必须在 BEGIN 之前设置）。
"""
import sqlite3

SCHEMA_VERSION = 2

# 每条语句单独执行：executescript 会先隐式 COMMIT，破坏 bootstrap 的原子边界。
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS materials (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        format TEXT NOT NULL DEFAULT 'md',
        parser_version TEXT,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        line_count INTEGER,
        source_bytes BLOB,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blocks (
        id TEXT PRIMARY KEY,
        material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        kind TEXT NOT NULL,
        locator_index INTEGER NOT NULL,
        end_index INTEGER,
        row_index INTEGER,
        cell_index INTEGER,
        paragraph_index INTEGER,
        text TEXT NOT NULL,
        block_index INTEGER NOT NULL,
        UNIQUE (material_id, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recent_material (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        material_id TEXT NOT NULL REFERENCES materials(id)
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS material_rubric_bindings (
        material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
        rubric_id TEXT NOT NULL,
        rubric_revision INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_criterion_evidence_links_material ON criterion_evidence_links(material_id)",
    """
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
    )
    """,
    """
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_proposal_candidates_material ON proposal_candidates(material_id)",
    """
    CREATE TABLE IF NOT EXISTS reviews (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        rubric_id TEXT NOT NULL,
        rubric_revision INTEGER NOT NULL CHECK (rubric_revision >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_materials (
        review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
        material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        position INTEGER NOT NULL CHECK (position >= 0),
        PRIMARY KEY (review_id, material_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_review_materials_material ON review_materials(material_id)",
    """
    CREATE TABLE IF NOT EXISTS material_revisions (
        child_material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
        parent_material_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)


class MigrationError(Exception):
    """迁移环境或生命周期错误：拒绝执行，不碰调用方事务。"""


class UnsupportedSchemaVersion(MigrationError):
    """数据库 schema 版本高于本程序支持的版本：明确拒绝启动。"""


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _foreign_keys(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA foreign_keys").fetchone()[0])


def _set_foreign_keys(connection: sqlite3.Connection, enabled: bool) -> None:
    connection.execute(f"PRAGMA foreign_keys = {'ON' if enabled else 'OFF'}")


def _create_schema(connection: sqlite3.Connection) -> None:
    """按当前 schema 建缺失的表/索引（IF NOT EXISTS，legacy 表原样保留给迁移重建）。"""
    for statement in _SCHEMA_STATEMENTS:
        connection.execute(statement)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _rebuild_materials_legacy(connection: sqlite3.Connection) -> None:
    """legacy materials → 新列（format='md'，parser_version/source_bytes=NULL，line_count 保留）。"""
    connection.execute(
        """
        CREATE TABLE materials_locator_v1 (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            format TEXT NOT NULL DEFAULT 'md',
            parser_version TEXT,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            line_count INTEGER,
            source_bytes BLOB,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO materials_locator_v1"
        " (id, filename, format, parser_version, size_bytes, sha256, line_count, source_bytes, created_at)"
        " SELECT id, filename, 'md', NULL, size_bytes, sha256, line_count, NULL, created_at FROM materials"
    )
    connection.execute("DROP TABLE materials")
    connection.execute("ALTER TABLE materials_locator_v1 RENAME TO materials")


def _rebuild_blocks_legacy(connection: sqlite3.Connection) -> None:
    """legacy blocks.line_number → kind='line' + locator_index；Block ID 原样保留。"""
    connection.execute(
        """
        CREATE TABLE blocks_locator_v1 (
            id TEXT PRIMARY KEY,
            material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            kind TEXT NOT NULL,
            locator_index INTEGER NOT NULL,
            end_index INTEGER,
            row_index INTEGER,
            cell_index INTEGER,
            paragraph_index INTEGER,
            text TEXT NOT NULL,
            block_index INTEGER NOT NULL,
            UNIQUE (material_id, ordinal)
        )
        """
    )
    connection.execute(
        "INSERT INTO blocks_locator_v1"
        " (id, material_id, ordinal, kind, locator_index, end_index, row_index, cell_index, paragraph_index, text, block_index)"
        " SELECT id, material_id, ordinal, 'line', line_number, NULL, NULL, NULL, NULL, text, block_index FROM blocks"
    )
    connection.execute("DROP TABLE blocks")
    connection.execute("ALTER TABLE blocks_locator_v1 RENAME TO blocks")


def _migrate_to_v1(connection: sqlite3.Connection) -> None:
    if _table_exists(connection, "materials") and "format" not in _table_columns(connection, "materials"):
        _rebuild_materials_legacy(connection)
    if _table_exists(connection, "blocks") and "kind" not in _table_columns(connection, "blocks"):
        _rebuild_blocks_legacy(connection)


def _migrate_to_v2(connection: sqlite3.Connection) -> None:
    # Historical identities intentionally have no live FK; snapshots survive source deletion.
    connection.execute("CREATE TABLE assessment_snapshots ("
                       "id TEXT PRIMARY KEY, review_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
    connection.execute("CREATE INDEX idx_assessment_review ON assessment_snapshots(review_id, created_at)")
    connection.execute("CREATE TRIGGER assessment_no_update BEFORE UPDATE ON assessment_snapshots "
                       "BEGIN SELECT RAISE(ABORT, 'assessment snapshot is immutable'); END")


def _check_foreign_keys(connection: sqlite3.Connection) -> None:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(f"迁移后外键完整性检查失败：{len(violations)} 处")


def bootstrap(connection: sqlite3.Connection) -> None:
    """初始化入口：检查版本，单一事务内建 schema/迁移/校验/写版本；失败全部回滚。"""
    if connection.in_transaction:
        raise MigrationError("连接存在未提交事务，拒绝迁移（不会提交或回滚调用方事务）")
    version = _user_version(connection)
    if version > SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"数据库 schema 版本 {version} 高于本程序支持的 {SCHEMA_VERSION}，拒绝启动"
        )
    if version == SCHEMA_VERSION:
        return

    original_fk = _foreign_keys(connection)
    try:
        _set_foreign_keys(connection, False)
        connection.execute("BEGIN IMMEDIATE")
        try:
            if version < 1:
                _create_schema(connection)
                _migrate_to_v1(connection)
            if version < 2:
                _migrate_to_v2(connection)
            _check_foreign_keys(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
    finally:
        _set_foreign_keys(connection, bool(original_fk))
        if _foreign_keys(connection) != original_fk:
            raise MigrationError(
                f"外键状态未恢复：期望 {original_fk}，实际 {_foreign_keys(connection)}"
            )
