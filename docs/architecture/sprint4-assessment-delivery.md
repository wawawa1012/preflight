# Sprint 4 Explainable Assessment — backend handoff

Branch: `wave4/assessment-core`, based on main `8c6bd43207bdfae27df545b5941562c2a9aef8da`. Worktree: `F:/project/Preflight-backend`. Old branch refs retained; do not merge main in this task. Implementer is Codex (the session cannot switch to DeepSeek). Independent read-only Codex contract checkpoint review passed; see [checkpoint](sprint4-assessment-checkpoint.md). The post-implementation Assessment contract review returned APPROVE_WITH_CHANGES; both required-before-public-wire fixes (evaluator identity in comparability, precise observations) are applied in this branch before any frontend consumption.

## Files and responsibility

| File | Responsibility |
| --- | --- |
| backend/app/contracts.py | Scoring metadata increments; AssessmentCreate/AssessorProposal/AssessmentResult/EvaluationScope/Snapshot/Summary/Comparison; legacy CriterionAssessment unchanged |
| backend/app/assessment.py | Code-owned anchor mapping, scope/source validation, deterministic sum and comparison |
| backend/app/assessment_runner.py | Per-criterion bounded prompt, strict parser, isolated errors, snapshot use case |
| backend/app/assessment_store.py | One SQLite read transaction freezes inputs; insert-only persistence and historical reads |
| backend/app/migrations.py | Atomic v1→v2 addition, update prevention trigger, one review/time index |
| backend/app/main.py | Four HTTP endpoints and error adaptation |
| backend/app/criteria_builder.py, rubric_store.py, scoring_provenance.py | Structured/manual execution opt-in, publishing and numeric bound provenance |
| backend/tests/test_assessment.py | Offline acceptance matrix, integration, hostile inputs, migration rollback |
| backend/tests/test_contract_export.py, scripts/check_contracts.py | Export and fixed fixture validation |
| contracts/schema.json, frontend/src/types/contracts.ts | Generated public contracts |
| contracts/fixtures/assessment.json | Synthetic before/after and injection/invalid-output fixtures; never a real standard |

## Scoring definition and assessor contract

Reuse existing `Criterion.max_score`, `weight`, `rubric_levels` and each level's `label`, `description`, `score`. Execution requires explicit `scoring_definition_version: "anchors-v1"`. Every level then needs a unique `anchor_id`, nonblank description and either finite nonnegative `score` or `min_score` + `max_score`, bounded by the criterion maximum. Unknown versions fail validation. A numeric exact anchor retains the source standard's precision. Range anchors remain ranges, including when the selected endpoints happen to be equal.

The existing `scoring_anchors: string[]` remains descriptive only. No percentage, rubric band, weight, maximum or execution definition is inferred from prose. Manual/rubric_json publishing can explicitly opt in. Text/Markdown draft LLM output cannot set executable switches; text/Markdown publish with execution switches is rejected. The standard author must verify those rules against the actual standard. Existing standard files are untouched and are not automatically scorable.

LLM receives requirement, allowed anchor IDs/conditions, and current criterion's accepted source IDs/excerpts. It returns only `criterion_id`, `status`, `selected_anchor_id`, `source_ids`, `rationale`, `missing_conditions`, `caveats`. Strict JSON rejects duplicate keys, malformed JSON, NaN, unknown fields (including total_score/score/SourceRef/locator/version), invalid criterion, cross-criterion source borrowing and unknown anchors. All criterion/anchor/excerpt text uses the existing escaped UNTRUSTED_DATA_JSON boundary. This is a contract/injection containment test, not evidence that a live model always obeys instructions.

## Source policy and status model

`accepted-links-v1`: persisted CriterionEvidenceLink → EvidenceAnnotation, within frozen Review membership and rubric revision. Manual links and explicitly accepted agent links qualify; proposals and unattached annotations do not. No whole-document search or fallback evidence acceptance. SourceAuthority rechecks ownership and exact spans before the model call and on result validation. It proves quotation location, not evidence sufficiency or external truth.

| Status | Score/anchor | Frontend meaning |
| --- | --- | --- |
| assessed | Code-mapped exact or range, citation IDs required | Model selected an allowed anchor using the supplied accepted evidence; explanation is reviewable |
| insufficient_evidence | null | No accepted links, or assessor reports insufficient evidence; never zero |
| abstain | null | Assessor declines judgment; never a low score |
| execution_failed | null; safe error_code | Source validation, response, provider or execution failure; sibling results retained |
| not_scorable | null | No executable anchor definition; deterministic explanation; accepted sources remain in scope for inspection; no LLM required |

No NOT_APPLICABLE, confidence percentage, ranking or quality verdict. Non-assessed statuses must not be rendered as 0. Do not equate `assessed` or accepted link counts with risk resolution. No-reference precedence: a criterion lacking executable rules is not_scorable; an executable criterion with no accepted links is insufficient_evidence. Invalid sources are execution_failed, not silently omitted.

## Deterministic aggregator

Rubric must explicitly declare `scoring_aggregation: "sum_points_v1"`. Legacy free-text aggregation_rule is preserved but never executed. The aggregator revalidates results and mapping, then sums lower/upper bounds with Decimal arithmetic. Exact aggregation requires every selected anchor to be exact. No midpoint, inferred weighting, missing-as-zero or rescaling.

Any unscorable/non-assessed criterion blocks the total. No explicit rule, empty criteria, unsupported non-unit weight or numeric overflow also returns unavailable. `reason_codes`, `missing_criterion_ids`, and assessed/scorable/total counts let the frontend explain why. V1 deliberately does not implement weighted totals; non-unit weights remain metadata and prevent an overall number. Per-criterion permitted numbers remain available.

## Evaluation scope and snapshot persistence

Scope freezes Review ID, full rubric/revision, canonical SHA-256 of that rubric (including requirements and scoring semantics), ordered criterion IDs, material identities/content hashes/labels/positions and recorded ancestors, accepted link and annotation manifests, SourceRefs, referenced Blocks/Locators, source policy and method version. Only referenced Blocks are retained; the model sees accepted excerpts, not full Blocks. The read transaction completes before model calls; no long-lived DB lock during inference. Historical snapshots describe that captured instant even if links/materials change during execution.

Snapshot contains that scope, validated results, aggregation, server timestamp, prompt version and optional model identifier. `assessment-v1` is the method identity; it is independent of model choice. No raw provider errors, API keys, configuration, or raw LLM responses are persisted. Rerun inserts a new UUID; no update/upsert API. SQL rejects UPDATE. The payload remains self-contained after live source deletion. These are retained historical source copies, so deleting a live material does not purge its historical snapshot excerpts; a future retention/purge policy would be separate explicit work.

Schema version 2 adds `assessment_snapshots` plus index `(review_id, created_at)`. Historical Review/material/link identities intentionally have no live FK, preserving existing source deletion behavior. Formal migrations retain one transaction across DDL, FK check and version assignment; failure rolls back and is retryable. Future versions are rejected. No existing table/endpoint semantics changed.

## Comparability and before/after

Require same Review, rubric identity/revision, full scoring hash, method version, source policy, evaluator identity and ordered criterion scope. Evaluator identity is the pair `prompt_version` + `model_identifier`; either differing makes the pair not comparable, and V1 deliberately has no cross-model equivalence, provider-family compatibility or benchmark exception. These fields stay distinct from `assessment_method_version`: the method names the code path, prompt and model name the evaluator. Material sets must match one-to-one by exact ID or forward immutable descendant replacement. Exact identities match first; ambiguous mappings, reverse ancestry, changed content under an identical ID, unrelated same-title materials or material-count changes are rejected. Labels/positions are recorded for display, not proof of lineage. Deleted intermediate ancestry may make later comparisons unavailable; v1 refuses to invent history.

Accepted evidence can change: `evidence_scope_changed` exposes it. Return before/after results, status transitions and dimension-scoped observations: `identical` (status, anchor, mapped score and key reason all equal), `anchor_changed`, `reason_changed`, `status_changed`, `newly_assessable`, `became_insufficient`, `range_overlaps`, `range_shifted_upward/downward`. Key reason means error code, missing conditions, caveats and rationale. `score_changed`/`anchor_changed`/`reason_changed` booleans expose all changed dimensions at once, so a same-range different-anchor pair is never reported as an unchanged assessment and a same-status different-reason pair is never reported as identical. Up/down means disjoint bounds, never a claim that material quality improved. Aggregation before/after stays visible, even when comparison is unavailable; no automatic numeric delta across incompatible snapshots.

## Frontend API

| Endpoint | Response |
| --- | --- |
| POST /api/v1/reviews/{review_id}/assessments | 201 AssessmentSnapshot; body omitted/null/{}; extra keys rejected |
| GET /api/v1/reviews/{review_id}/assessments | Newest-first AssessmentSummary[]; historical review ID allowed; unknown/no history gives [] |
| GET /api/v1/assessments/{snapshot_id} | AssessmentSnapshot; unknown 404 |
| GET /api/v1/assessments/{before_id}/compare/{after_id} | AssessmentComparison; unknown snapshot 404 |

POST uses all criteria and all current Review members; client cannot supply a score, source pool, version or custom scope. Missing Review/rubric is 404, invalid frozen scope 409; malformed request follows existing 400 ApiError convention. Provider errors are per-criterion execution_failed in a persisted 201 partial snapshot. There is no all-success boolean: inspect every result and aggregation.status. Snapshot GET carries blocks plus sources so citations can still be displayed without requesting deleted live material.

## Required test matrix

Tests below are in `backend/tests/test_assessment.py` (prefix `test_` omitted).

| # | Requirement | Acceptance evidence |
| --- | --- | --- |
| 1 | Anchor + accepted evidence → assessed | assessed_source_anchor_and_range_roundtrip |
| 2 | No accepted link → insufficient, not zero | no_accepted_evidence_is_not_zero_and_does_not_call_model |
| 3 | No anchors → no number | unscorable_even_with_legacy_levels_and_evidence |
| 4 | Unknown anchor rejected | invalid_anchor_source_criterion_and_model_total_are_rejected |
| 5 | Unknown/other-criterion source rejected | same test + other_criterion_link_cannot_be_borrowed |
| 6 | Model total excluded | invalid_anchor_source_criterion_and_model_total_are_rejected |
| 7 | One failed, siblings retained | failure_isolation_and_no_secret_in_diagnostics |
| 8 | Deterministic range/exact/decimal aggregation | range_and_exact_aggregation + decimal_sum_and_prompt_bound_are_honest |
| 9 | Different method incompatible | comparison_method_rubric_scoring_and_source_policy |
| 10 | Different rubric revision incompatible | same test |
| 11 | Unrelated same title incompatible | lineage_replacement_and_unrelated_same_title |
| 12 | Legal forward child replacement compatible | same test |
| 13 | Invalid SourceRef never assessed | invalid_sourceref_fails_only_its_criterion |
| 14 | Injection fixture cannot expand contract | prompt_injection_fixture_cannot_change_output_contract |
| 15 | Old DB atomic upgrade preserves identity | v1_upgrade_identity_rollback_retry_and_fk; existing test_migrations covers legacy v0, caller transaction, FK restore, future version |

Also tested: abstain, immutable SQL writes, source deletion during inference/after persistence, strict request body, bounded prompt, no secret diagnostics, unsupported weights/rules, mixed unscorable scope, no partial-total expansion, imported execution-switch rejection, schema/TS export, HTTP health/OpenAPI, evaluator-identity mismatch blocking all observations, same-range different-anchor, same-failure-status different-reason, and exact-equivalent `identical` observations.

## Deviations and open architecture decisions

Verification completed: **549 backend tests passed** (524 baseline + 25 Assessment tests), contract export/check including new fixtures passed, `npm.cmd ci`, `npm.cmd run contracts`, `npm.cmd run build` passed, native Windows uvicorn with an isolated temporary database returned health/OpenAPI 200. Existing frontend large-chunk advisory remains; no performance work included. `git diff --check` passed. Main remained clean at the original base; old backend branch ref retained. **READY_FOR_FRONTEND: YES** for API/contract integration only.

Review-fix verification (post-APPROVE_WITH_CHANGES): full backend suite **553 tests OK** (549 original + 4 new in `tests.test_assessment`), `tests.test_contract_export` 4 OK, `scripts/check_contracts.py` PASS with regenerated `contracts/schema.json` + `frontend/src/types/contracts.ts`, and `npm.cmd run build` (vite + vue-tsc) PASS. Migration code was not touched. The positive fixture pair now shares `prompt_version` + `model_identifier`; mismatches produce `not_comparable` with empty criteria.

No weighted aggregation in v1; unsupported weights yield unavailable, not a guessed normalization. Non-executable criteria have a deterministic explanation rather than an extra LLM call. No new frameworks, rebind, composite evidence, persisted Finding, DB optimization, frontend page implementation, or live model benchmark. Full rubric hash intentionally rejects even some harmless metadata changes: strictness is preferable to false comparability.

No blocking architecture decision remains. Future work requires explicit scope: weighted aggregation with sourced executable semantics, retention/purge policy, live assessor quality evaluation. READY_FOR_FRONTEND means the wire/API and fixtures are usable, not that the frontend or live evaluation quality has been accepted.
