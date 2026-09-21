"""Code owns scope, anchors, validation and aggregation. No I/O or model arithmetic."""
import hashlib
import json
from decimal import Decimal, localcontext

from .contracts import (
    AssessorProposal, AssessmentAggregation, AssessmentComparison, AssessmentCriterionChange,
    AssessmentResult, AssessmentScore, AssessmentSnapshot, Criterion, EvaluationScope, Rubric,
)
from .source_authority import SourceAuthority, SourceScope

METHOD_VERSION = "assessment-v1"
SOURCE_POLICY_VERSION = "accepted-links-v1"
PROMPT_VERSION = "criterion-assessor-v1"


class AssessmentInvalid(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def scoring_hash(rubric: Rubric) -> str:
    # Include requirements as well as numeric definitions; changing semantics invalidates comparison.
    return canonical_hash(rubric.model_dump(mode="json"))


def criterion_for(scope: EvaluationScope, criterion_id: str) -> Criterion:
    matches = [c for c in scope.rubric.criteria if c.id == criterion_id and c.id in scope.criterion_ids]
    if len(matches) != 1:
        raise AssessmentInvalid("invalid_criterion")
    return matches[0]


def source_pool(scope: EvaluationScope, criterion_id: str):
    return [s for s in scope.sources if s.link.criterion_id == criterion_id]


def verify_sources(scope: EvaluationScope, criterion_id: str) -> None:
    authority = SourceAuthority(SourceScope.from_blocks(
        scope.blocks, allowed_material_ids=[m.material_id for m in scope.materials]))
    seen = set()
    for item in source_pool(scope, criterion_id):
        link, annotation, ref = item.link, item.annotation, item.source
        if (link.id in seen or link.annotation_id != annotation.id
                or link.material_id != annotation.material_id or ref.material_id != link.material_id
                or link.rubric_id != scope.rubric.id or link.rubric_revision != scope.rubric.revision
                or ref.block_id != annotation.block_id or ref.block_id != annotation.source.block_id
                or ref.start != annotation.source.start or ref.end != annotation.source.end
                or ref.quote != annotation.source.quote):
            raise AssessmentInvalid("invalid_source")
        seen.add(link.id)
        try:
            authority.resolve(ref.block_id, ref.quote, start=ref.start, end=ref.end, material_id=ref.material_id)
        except Exception as exc:
            raise AssessmentInvalid("invalid_source") from exc


def anchor_score(criterion: Criterion, anchor_id: str) -> AssessmentScore:
    if criterion.scoring_definition_version is None:
        raise AssessmentInvalid("not_scorable")
    anchors = [a for a in criterion.rubric_levels or [] if a.anchor_id == anchor_id]
    if len(anchors) != 1:
        raise AssessmentInvalid("unknown_anchor")
    anchor = anchors[0]
    if anchor.score is not None:
        return AssessmentScore(kind="exact", minimum=anchor.score, maximum=anchor.score)
    return AssessmentScore(kind="range", minimum=anchor.min_score, maximum=anchor.max_score)


def validate_proposal(scope: EvaluationScope, criterion_id: str, proposal: AssessorProposal) -> AssessmentResult:
    criterion = criterion_for(scope, criterion_id)
    if proposal.criterion_id != criterion_id:
        raise AssessmentInvalid("invalid_criterion")
    verify_sources(scope, criterion_id)
    pool_ids = {s.link.id for s in source_pool(scope, criterion_id)}
    if len(set(proposal.source_ids)) != len(proposal.source_ids) or not set(proposal.source_ids) <= pool_ids:
        raise AssessmentInvalid("unknown_source")
    score = None
    if criterion.scoring_definition_version is None:
        if proposal.status != "not_scorable":
            raise AssessmentInvalid("not_scorable")
    elif proposal.status == "not_scorable":
        raise AssessmentInvalid("invalid_status")
    if proposal.status == "assessed":
        if not proposal.source_ids:
            raise AssessmentInvalid("evidence_required")
        score = anchor_score(criterion, proposal.selected_anchor_id)
    elif proposal.selected_anchor_id is not None:
        raise AssessmentInvalid("unexpected_anchor")
    if not proposal.rationale.strip():
        raise AssessmentInvalid("empty_rationale")
    return AssessmentResult(**proposal.model_dump(), score=score)


def validate_scope(scope: EvaluationScope) -> None:
    # Reparse, including nested validators, even if an internal caller used model_copy(update=...).
    Rubric.model_validate(scope.rubric.model_dump())
    ids = [c.id for c in scope.rubric.criteria]
    if ids != scope.criterion_ids or len(set(ids)) != len(ids):
        raise AssessmentInvalid("invalid_criterion_scope")
    if scope.scoring_definition_hash != scoring_hash(scope.rubric):
        raise AssessmentInvalid("scoring_hash_mismatch")
    mids = [m.material_id for m in scope.materials]
    bids = [b.id for b in scope.blocks]
    sids = [s.link.id for s in scope.sources]
    if len(set(mids)) != len(mids) or len(set(bids)) != len(bids) or len(set(sids)) != len(sids):
        raise AssessmentInvalid("duplicate_scope_identity")
    if any(b.document_id not in mids for b in scope.blocks):
        raise AssessmentInvalid("invalid_block_scope")
    if any(s.link.criterion_id not in ids for s in scope.sources):
        raise AssessmentInvalid("invalid_source_scope")
    for material in scope.materials:
        if material.material_id in material.ancestor_ids or len(set(material.ancestor_ids)) != len(material.ancestor_ids):
            raise AssessmentInvalid("invalid_lineage")


def aggregate(scope: EvaluationScope, results: list[AssessmentResult]) -> AssessmentAggregation:
    """Revalidate all numeric results before deterministic aggregation; missing never means zero."""
    validate_scope(scope)
    if [r.criterion_id for r in results] != scope.criterion_ids:
        raise AssessmentInvalid("invalid_result_scope")
    for result in results:
        AssessmentResult.model_validate(result.model_dump())
        if result.status != "execution_failed":
            proposal = AssessorProposal(**result.model_dump(exclude={"score", "error_code"}))
            validated = validate_proposal(scope, result.criterion_id, proposal)
            if validated.score != result.score:
                raise AssessmentInvalid("score_mapping_mismatch")
        elif result.source_ids:
            raise AssessmentInvalid("failure_cannot_cite_sources")
    missing = [r.criterion_id for r in results if r.status != "assessed"]
    reasons = []
    if not results:
        reasons.append("empty_criterion_scope")
    if scope.rubric.scoring_aggregation != "sum_points_v1":
        reasons.append("aggregation_rule_unavailable")
    if any(c.weight not in (None, 1) for c in scope.rubric.criteria):
        reasons.append("unsupported_weights")
    if any(c.scoring_definition_version is None for c in scope.rubric.criteria):
        reasons.append("unscorable_criteria")
    if missing:
        reasons.append("incomplete_assessment")
    score = None
    if not reasons:
        # Decimal avoids float accumulation artifacts; no averaging, rounding or normalization.
        with localcontext() as context:
            context.prec = 340
            low = sum((Decimal(str(r.score.minimum)) for r in results), Decimal(0))
            high = sum((Decimal(str(r.score.maximum)) for r in results), Decimal(0))
        try:
            score = AssessmentScore(kind="exact" if all(r.score.kind == "exact" for r in results) else "range",
                                    minimum=float(low), maximum=float(high))
        except ValueError:
            reasons.append("numeric_overflow")
    return AssessmentAggregation(status="available" if score else "unavailable", score=score,
        reason_codes=reasons, assessed_criterion_count=sum(r.status == "assessed" for r in results),
        scorable_criterion_count=sum(c.scoring_definition_version is not None for c in scope.rubric.criteria),
        total_criterion_count=len(results), missing_criterion_ids=missing)


def validate_snapshot(snapshot: AssessmentSnapshot) -> None:
    if snapshot.aggregation != aggregate(snapshot.scope, snapshot.results):
        raise AssessmentInvalid("aggregation_mismatch")


def _compatible_materials(before: EvaluationScope, after: EvaluationScope) -> bool:
    old = {m.material_id: m for m in before.materials}
    new = {m.material_id: m for m in after.materials}
    if len(old) != len(new):
        return False
    common = old.keys() & new.keys()
    if any(old[mid].sha256 != new[mid].sha256 or old[mid].ancestor_ids != new[mid].ancestor_ids for mid in common):
        return False
    remaining_old = old.keys() - common
    remaining_new = new.keys() - common
    mapping = {mid: [nid for nid in remaining_new if mid in new[nid].ancestor_ids] for mid in remaining_old}
    return (all(len(candidates) == 1 for candidates in mapping.values())
            and len({c[0] for c in mapping.values()}) == len(remaining_new))


def _reason_fingerprint(result: AssessmentResult) -> tuple:
    # 关键 reason 的等价比较：机器可读 code、缺口、注意事项与解释文本；不含 status/anchor/score。
    return (result.error_code, tuple(result.missing_conditions), tuple(result.caveats), result.rationale)


def _observation(before: AssessmentResult, after: AssessmentResult) -> str:
    if before.status != after.status:
        if after.status == "insufficient_evidence":
            return "became_insufficient"
        if after.status == "assessed":
            return "newly_assessable"
        return "status_changed"
    if before.score != after.score:
        if before.score is None or after.score is None:
            return "status_changed"
        if after.score.minimum > before.score.maximum:
            return "range_shifted_upward"
        if after.score.maximum < before.score.minimum:
            return "range_shifted_downward"
        return "range_overlaps"
    if before.selected_anchor_id != after.selected_anchor_id:
        return "anchor_changed"
    if _reason_fingerprint(before) != _reason_fingerprint(after):
        return "reason_changed"
    return "identical"


def compare_assessment_snapshots(before: AssessmentSnapshot, after: AssessmentSnapshot) -> AssessmentComparison:
    # Only persisted, code-validated snapshots reach the API, never client-authored manifests.
    a, b = before.scope, after.scope
    reasons = []
    checks = (
        (a.review_id == b.review_id, "review_mismatch"),
        ((a.rubric.id, a.rubric.revision) == (b.rubric.id, b.rubric.revision), "rubric_mismatch"),
        (a.assessment_method_version == b.assessment_method_version, "method_mismatch"),
        # 评估器身份独立于方法与材料：prompt_version 或 model_identifier 不同即不可比。
        # V1 不做跨模型等价判断（provider family / benchmark 例外留待实证）。
        (before.prompt_version == after.prompt_version, "prompt_version_mismatch"),
        (before.model_identifier == after.model_identifier, "model_identifier_mismatch"),
        (a.scoring_definition_hash == b.scoring_definition_hash, "scoring_definition_mismatch"),
        (a.source_policy_version == b.source_policy_version, "source_policy_mismatch"),
        (a.criterion_ids == b.criterion_ids, "criterion_scope_mismatch"),
        (_compatible_materials(a, b), "material_scope_mismatch"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    if not reasons:
        try:
            validate_snapshot(before)
            validate_snapshot(after)
        except ValueError:
            reasons.append("invalid_snapshot")
    changes = []
    if not reasons:
        for old, new in zip(before.results, after.results, strict=True):
            changes.append(AssessmentCriterionChange(criterion_id=old.criterion_id, before=old, after=new,
                observation=_observation(old, new),
                score_changed=old.score != new.score,
                anchor_changed=old.selected_anchor_id != new.selected_anchor_id,
                reason_changed=_reason_fingerprint(old) != _reason_fingerprint(new)))
    return AssessmentComparison(before_id=before.id, after_id=after.id,
        status="not_comparable" if reasons else "comparable", reason_codes=reasons,
        evidence_scope_changed=canonical_hash([s.model_dump() for s in a.sources]) != canonical_hash([s.model_dump() for s in b.sources]),
        criteria=changes, aggregation_before=before.aggregation, aggregation_after=after.aggregation)
