# Sprint 4 Assessment contract checkpoint

Base: main `8c6bd43207bdfae27df545b5941562c2a9aef8da`. Implementer: Codex, worktree Preflight-backend, branch wave4/assessment-core. Old refs retained. No merge to main.

## Admission
Review report → explainable assessment and revision comparison (frontend consumer, not implemented here); executable acceptance: 15-case matrix plus API/persistence/migration checks; demo 30 seconds (anchor, cited accepted evidence, honest unavailable total, before/after).

## ASSESSMENT CONTRACT DELTA / SCORING SEMANTICS
Reuse Criterion.max_score/weight/rubric_levels and RubricLevel.label/description/score. Add optional RubricLevel.anchor_id, min_score, max_score; add Criterion.scoring_definition_version. A version explicitly opts into execution: unique nonempty anchor IDs, nonempty descriptions, finite nonnegative exact score OR bounded range, <= Criterion.max_score. No inference from old free-text scoring_anchors or levels. Criterion without execution version is NOT_SCORABLE. Imported text provenance must validate new bounds/descriptions; draft LLM cannot author execution opt-in. Explicit manual/structured standard authoring is supported, never assessment model authoring.

Rubric adds optional scoring_aggregation='sum_points_v1'. Existing free-text aggregation_rule is preserved and never parsed as code. Absent rule, unsupported non-unit weights, empty scope, any unscorable criterion, or any non-assessed criterion => unavailable total with reason and criterion counts/IDs. Sum min/max with decimal arithmetic, no midpoint or rescaling; exact only when every selected anchor is exact. Never infer aggregation from max_score alone.

## STATUS SEMANTICS / ASSESSOR CONTRACT
assessed, insufficient_evidence, abstain, execution_failed, not_scorable. Only assessed has anchor and code-mapped score/range; all others have no number. No NOT_APPLICABLE in v1. No-anchor precedence is not_scorable; executable but empty accepted pool is insufficient_evidence. LLM may propose assessed/insufficient_evidence/abstain (or not_scorable only for explanatory non-executable criteria). Strict extra-forbid JSON, selected criterion and source IDs only; assessed requires cited evidence and valid anchor. Invalid response => isolated execution_failed with safe error code. Never persist raw provider errors/secrets.

## EVALUATION SCOPE / SNAPSHOT SHAPE
Freeze Review ID, full rubric snapshot and revision, scoring hash (canonical rubric scoring definition incl. requirements), ordered criterion IDs, material identities/content hashes/labels/positions and immutable ancestry, accepted link + annotation manifests and SourceRefs, source policy and method versions. Capture in one SQLite read transaction; release before LLM. SourceAuthority resolves all accepted sources against frozen Blocks. Revalidate selected sources before accepting each result against those same immutable inputs. A snapshot includes frozen blocks necessary to reproduce source verification, scope, validated per-criterion outputs, deterministic aggregation, created_at and optional model ID. Link removal after capture does not mutate historical scope. No dependency on current page state.

## SOURCE POLICY
accepted-links-v1: only persisted CriterionEvidenceLink joined to EvidenceAnnotation in the Review's material membership and frozen rubric binding. Include human links and explicitly accepted agent links; proposals never qualify. Invalid reference fails its criterion; no fallback scan. SourceAuthority certifies location, not sufficiency. Model sufficiency remains a proposal, not benchmark-proven truth.

## METHOD VERSION RULE
assessment-v1 represents validation, status and aggregation semantics, independently of provider/model identifier; prompt version separately recorded. Changing semantics requires new method version.

## COMPARABILITY RULES
Same Review, rubric identity/revision, scoring hash, method version, source policy and criterion IDs. Same logical material scope: exact identity or one-to-one forward immutable descendant replacement, validated using frozen ancestry; reject ambiguous/multiple mappings, arbitrary same-title materials and reversals. Do not require mutable labels/positions to equal when identity/ancestry uniquely establishes correspondence. Evidence changes are disclosed separately, not automatically quality improvement. Return per-criterion before/after/status and range overlap/shift/newly assessable/became insufficient; aggregation before/after. No automatic quality verdict.

## MIGRATION PLAN
Formal schema 1→2 in migrations.py inside existing bootstrap transaction. Add assessment_snapshots(id PK, review_id historical identity, created_at, payload JSON) and index(review_id, created_at). Historical identities deliberately have no live FK: deleting a Review/material must not erase or rewrite snapshots or change existing deletion semantics. Payload is self-contained. SQL trigger rejects UPDATE; no update/delete API. INSERT only, no replace/upsert. Existing atomic rollback/retry/future-version/FK rules preserved; migration does not rebuild existing tables.

## API PLAN
POST /api/v1/reviews/{review_id}/assessments (server chooses full scope, no client score/config); GET same path lists snapshot summaries; GET /api/v1/assessments/{snapshot_id}; GET /api/v1/assessments/{before_id}/compare/{after_id}. main.py adapts HTTP only. assessment.py pure validation/aggregation/comparison; assessment_store.py capture/persistence; assessment_runner.py orchestration/LLM. No framework.

Gate: independent read-only Codex review passed before public contracts/migration implementation (2026-09-21). Incorporated: `anchors-v1` whitelist; exact XOR complete range; execution opt-in only manual/rubric_json (including aggregation); legacy CriterionAssessment untouched; criterion-local source allowlist; shared final FK check/version assignment after v1/v2 migration steps. No-anchor criteria get deterministic not_scorable explanation without requiring LLM availability. No live-model quality claim.

## Post-implementation contract review (2026-09-21)

Verdict APPROVE_WITH_CHANGES. Two required-before-public-wire fixes resolved on this branch: (1) comparability now includes evaluator identity — `prompt_version` and `model_identifier` stay separate from `assessment_method_version`, and either differing blocks comparison with no per-criterion observations (no cross-model equivalence in v1); (2) the ambiguous `unchanged` observation is replaced by dimension-scoped `identical`/`anchor_changed`/`reason_changed` plus `score_changed`/`anchor_changed`/`reason_changed` booleans. Details in [the delivery handoff](sprint4-assessment-delivery.md).
