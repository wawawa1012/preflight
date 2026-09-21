"""Single-transaction input capture and insert-only historical snapshots."""
from contextlib import closing
from pathlib import Path

from . import database, rubric_store, storage
from .assessment import METHOD_VERSION, SOURCE_POLICY_VERSION, AssessmentInvalid, scoring_hash, validate_scope, validate_snapshot
from .contracts import (AssessmentMaterial, AssessmentSnapshot, AssessmentSource, AssessmentSummary,
                        EvaluationScope, Rubric, SourceRef)


class AssessmentNotFound(LookupError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def capture_scope(review_id: str, db_path: Path | None = None) -> EvaluationScope:
    with closing(database.connect(db_path)) as connection:
        connection.execute("BEGIN")
        review = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if review is None:
            raise AssessmentNotFound("review_not_found")
        existing = rubric_store.get_rubric(review["rubric_id"], review["rubric_revision"])
        if existing is None:
            raise AssessmentNotFound("rubric_not_found")
        rubric = Rubric.model_validate(existing.model_dump())
        members = connection.execute(
            "SELECT rm.*, m.sha256 FROM review_materials rm JOIN materials m ON m.id=rm.material_id "
            "WHERE rm.review_id=? ORDER BY rm.position, rm.material_id", (review_id,)).fetchall()
        materials, sources, blocks = [], [], {}
        for member in members:
            mid = member["material_id"]
            binding = connection.execute("SELECT * FROM material_rubric_bindings WHERE material_id=?", (mid,)).fetchone()
            if binding is None or (binding["rubric_id"], binding["rubric_revision"]) != (rubric.id, rubric.revision):
                raise AssessmentInvalid("material_binding_mismatch")
            ancestors, current = [], mid
            while True:
                row = connection.execute("SELECT parent_material_id FROM material_revisions WHERE child_material_id=?",
                                         (current,)).fetchone()
                if row is None:
                    break
                current = row["parent_material_id"]
                if current == mid or current in ancestors:
                    raise AssessmentInvalid("invalid_lineage")
                ancestors.append(current)
            materials.append(AssessmentMaterial(material_id=mid, sha256=member["sha256"],
                label=member["label"], position=member["position"], ancestor_ids=ancestors))
            links = connection.execute(
                "SELECT * FROM criterion_evidence_links WHERE material_id=? AND rubric_id=? AND rubric_revision=? ORDER BY id",
                (mid, rubric.id, rubric.revision)).fetchall()
            for row in links:
                if row["criterion_id"] not in {c.id for c in rubric.criteria}:
                    continue
                link = storage._link_from_row(row)
                annotation_row = connection.execute("SELECT * FROM evidence_annotations WHERE id=?", (link.annotation_id,)).fetchone()
                if annotation_row is None:
                    raise AssessmentInvalid("annotation_missing")
                annotation = storage._annotation_from_row(annotation_row)
                ref = SourceRef(material_id=annotation.material_id, **annotation.source.model_dump())
                sources.append(AssessmentSource(link=link, annotation=annotation, source=ref))
                block_row = connection.execute("SELECT * FROM blocks WHERE id=?", (ref.block_id,)).fetchone()
                if block_row is not None:
                    blocks[ref.block_id] = storage._block_from_row(block_row)
        scope = EvaluationScope(review_id=review_id, rubric=rubric, scoring_definition_hash=scoring_hash(rubric),
            criterion_ids=[c.id for c in rubric.criteria], materials=materials, sources=sources,
            blocks=sorted(blocks.values(), key=lambda b: b.id), source_policy_version=SOURCE_POLICY_VERSION,
            assessment_method_version=METHOD_VERSION)
        validate_scope(scope)
        return scope


def insert_snapshot(snapshot: AssessmentSnapshot, db_path: Path | None = None) -> None:
    validate_snapshot(snapshot)
    with closing(database.connect(db_path)) as connection, connection:
        connection.execute("INSERT INTO assessment_snapshots(id, review_id, created_at, payload) VALUES (?,?,?,?)",
            (snapshot.id, snapshot.scope.review_id, snapshot.created_at, snapshot.model_dump_json()))


def get_snapshot(snapshot_id: str, db_path: Path | None = None) -> AssessmentSnapshot:
    with closing(database.connect(db_path)) as connection:
        row = connection.execute("SELECT payload FROM assessment_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if row is None:
        raise AssessmentNotFound("assessment_not_found")
    return AssessmentSnapshot.model_validate_json(row["payload"])


def list_snapshots(review_id: str, db_path: Path | None = None) -> list[AssessmentSummary]:
    # Historical Review IDs remain queryable after Review deletion.
    with closing(database.connect(db_path)) as connection:
        rows = connection.execute("SELECT payload FROM assessment_snapshots WHERE review_id=? ORDER BY created_at DESC, id DESC",
                                  (review_id,)).fetchall()
    snapshots = [AssessmentSnapshot.model_validate_json(row["payload"]) for row in rows]
    return [AssessmentSummary(id=s.id, review_id=s.scope.review_id, created_at=s.created_at,
            aggregation=s.aggregation, assessment_method_version=s.scope.assessment_method_version) for s in snapshots]
