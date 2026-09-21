"""Offline adversarial and integration checks; these do not claim live assessor quality."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import assessment as core, assessment_runner as runner, assessment_store as store
from app import database, llm, migrations, rubric_store, storage
from app.contracts import Criterion, Rubric, RubricLevel, RubricPublish, RubricDraftRequest
from app.criteria_builder import draft_requirements
from app.main import app
from app.markdown_preview import build_preview


def criterion(cid="c1", exact=False):
    return Criterion(id=cid, title=cid, requirement="Provide measured results", required_evidence=[], max_score=20,
        scoring_definition_version="anchors-v1", rubric_levels=[RubricLevel(anchor_id="A", label="A",
            description="Measurements with verifiable references", **({"score": 20} if exact else {"min_score": 16, "max_score": 20})),
            RubricLevel(anchor_id="B", label="B", description="Some measured evidence", min_score=8, max_score=12)])


def rubric(criteria=None):
    return Rubric(id="rubric_test", revision=1, title="Synthetic test standard", source_note="test-only",
                  source_type="manual", criteria=criteria or [criterion()], scoring_aggregation="sum_points_v1")


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "db.sqlite"
        database.init_db(self.db)
        self.rubric = rubric()
        self.install(self.rubric)
        self.review = storage.create_review("review", self.rubric.id, 1, self.db)
        self.material = storage.save_material(build_preview("source.md", b"Measured result: 42 samples."), self.db)
        storage.upsert_review_material(self.review.id, self.material.id, None, None, self.db)
        self.settings = patch.object(llm, "load_settings", return_value=llm.LlmSettings(
            base_url="https://test.invalid/v1", api_key="test-secret", model="offline-stub", timeout_s=1))
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        rubric_store.reset_index()
        self.tmp.cleanup()

    def install(self, standard):
        self.rubric = standard
        rubric_store.set_index({(standard.id, standard.revision): standard})

    def link(self, cid="c1", material=None):
        material = material or self.material
        block = material.blocks[0]
        annotation = storage.save_evidence_annotation(block.id, block.text, db_path=self.db)
        return storage.create_link(material.id, annotation.id, cid, "accepted relevance", db_path=self.db)

    def answer(self, messages, **updates):
        # llm.untrusted_data serializes a single JSON envelope surrounded by clear delimiters.
        content = messages[1]["content"]
        data = json.loads(content[content.index("{"):content.rindex("}") + 1])
        result = dict(criterion_id=data["criterion_id"], status="assessed", selected_anchor_id="A",
                      source_ids=[data["sources"][0]["source_id"]], rationale="Measured evidence is cited.",
                      missing_conditions=[], caveats=[])
        result.update(updates)
        return json.dumps(result)

    def run_snapshot(self, updates=None):
        with patch.object(llm, "complete", side_effect=lambda settings, messages: self.answer(messages, **(updates or {}))):
            return runner.run_assessment(self.review.id, self.db)

    def test_assessed_source_anchor_and_range_roundtrip(self):
        link = self.link()
        snapshot = self.run_snapshot()
        self.assertEqual(snapshot.results[0].status, "assessed")
        self.assertEqual(snapshot.results[0].source_ids, [link.id])
        self.assertEqual((snapshot.aggregation.score.minimum, snapshot.aggregation.score.maximum), (16, 20))
        self.assertEqual(store.get_snapshot(snapshot.id, self.db), snapshot)
        self.assertEqual(len(store.list_snapshots(self.review.id, self.db)), 1)

    def test_no_accepted_evidence_is_not_zero_and_does_not_call_model(self):
        # Annotation without accepted CriterionEvidenceLink is outside the source policy.
        storage.save_evidence_annotation(self.material.blocks[0].id, self.material.blocks[0].text, db_path=self.db)
        with patch.object(llm, "complete") as model:
            snapshot = runner.run_assessment(self.review.id, self.db)
        model.assert_not_called()
        self.assertEqual(snapshot.results[0].status, "insufficient_evidence")
        self.assertIsNone(snapshot.results[0].score)
        self.assertIsNone(snapshot.aggregation.score)

    def test_unscorable_even_with_legacy_levels_and_evidence(self):
        legacy = criterion().model_dump()
        legacy["scoring_definition_version"] = None
        self.install(rubric([Criterion.model_validate(legacy)]))
        self.link()
        with patch.object(llm, "complete") as model:
            snapshot = runner.run_assessment(self.review.id, self.db)
        model.assert_not_called()
        self.assertEqual(snapshot.results[0].status, "not_scorable")
        self.assertIsNone(snapshot.aggregation.score)

    def test_invalid_anchor_source_criterion_and_model_total_are_rejected(self):
        self.link()
        for update, code in (({"selected_anchor_id": "invented"}, "unknown_anchor"),
                             ({"source_ids": ["invented"]}, "unknown_source"),
                             ({"criterion_id": "other"}, "invalid_criterion"),
                             ({"total_score": 100}, "invalid_response"),
                             ({"source_ref": {}}, "invalid_response"),
                             ({"source_ids": []}, "evidence_required")):
            with self.subTest(update=update):
                snapshot = self.run_snapshot(update)
                self.assertEqual(snapshot.results[0].error_code, code)
                self.assertIsNone(snapshot.aggregation.score)

    def test_other_criterion_link_cannot_be_borrowed(self):
        self.install(rubric([criterion(), criterion("c2")]))
        own = self.link()
        other = self.link("c2")
        snapshot = self.run_snapshot({"source_ids": [other.id]})
        self.assertEqual(snapshot.results[0].error_code, "unknown_source")
        self.assertEqual(snapshot.results[1].status, "assessed")
        self.assertNotEqual(own.id, other.id)

    def test_failure_isolation_and_no_secret_in_diagnostics(self):
        self.install(rubric([criterion(), criterion("c2"), criterion("c3")]))
        for cid in ("c1", "c2", "c3"):
            self.link(cid)
        def completion(settings, messages):
            if '"c2"' in messages[1]["content"]:
                raise llm.LlmUnavailable("test-secret provider payload")
            return self.answer(messages)
        with patch.object(llm, "complete", side_effect=completion):
            snapshot = runner.run_assessment(self.review.id, self.db)
        self.assertEqual([r.status for r in snapshot.results], ["assessed", "execution_failed", "assessed"])
        self.assertEqual(snapshot.aggregation.assessed_criterion_count, 2)
        self.assertIsNone(snapshot.aggregation.score)
        self.assertNotIn("test-secret", snapshot.model_dump_json())

    def test_abstain_insufficient_have_no_numeric_values(self):
        self.link()
        for status in ("abstain", "insufficient_evidence"):
            snapshot = self.run_snapshot({"status": status, "selected_anchor_id": None})
            self.assertEqual(snapshot.results[0].status, status)
            self.assertIsNone(snapshot.results[0].score)
            self.assertIsNone(snapshot.aggregation.score)

    def test_range_and_exact_aggregation(self):
        self.install(rubric([criterion(), criterion("c2")]))
        self.link()
        self.link("c2")
        snapshot = self.run_snapshot()
        self.assertEqual(snapshot.aggregation.score.model_dump(), {"kind": "range", "minimum": 32, "maximum": 40})
        self.assertEqual(core.aggregate(snapshot.scope, snapshot.results), snapshot.aggregation)
        self.install(rubric([criterion(exact=True), criterion("c2", exact=True)]))
        snapshot = self.run_snapshot()
        self.assertEqual(snapshot.aggregation.score.model_dump(), {"kind": "exact", "minimum": 40, "maximum": 40})

    def test_aggregation_requires_explicit_rule_and_supported_weights(self):
        self.link()
        for changes, reason in (({"scoring_aggregation": None}, "aggregation_rule_unavailable"),
                                ({"criteria": [criterion().model_copy(update={"weight": 2})]}, "unsupported_weights")):
            self.install(rubric().model_copy(update=changes))
            snapshot = self.run_snapshot()
            self.assertEqual(snapshot.results[0].status, "assessed")
            self.assertIn(reason, snapshot.aggregation.reason_codes)
            self.assertIsNone(snapshot.aggregation.score)

    def test_aggregator_rejects_forged_numeric_result(self):
        self.link()
        snapshot = self.run_snapshot()
        result = snapshot.results[0].model_copy(deep=True)
        result.score.minimum = 19
        with self.assertRaisesRegex(core.AssessmentInvalid, "score_mapping_mismatch"):
            core.aggregate(snapshot.scope, [result])

    def test_invalid_sourceref_fails_only_its_criterion(self):
        self.install(rubric([criterion(), criterion("c2")]))
        link = self.link()
        self.link("c2")
        with closing(database.connect(self.db)) as connection, connection:
            connection.execute("UPDATE evidence_annotations SET quote='wrong quote' WHERE id=?", (link.annotation_id,))
        snapshot = self.run_snapshot()
        self.assertEqual(snapshot.results[0].error_code, "invalid_source")
        self.assertEqual(snapshot.results[1].status, "assessed")

    def test_malformed_json_duplicate_keys_nonfinite_and_type_coercion(self):
        self.link()
        for raw in ('{', '{"criterion_id":"c1","criterion_id":"c1"}', '{"score":NaN}',
                    '{"criterion_id":1,"status":"abstain","rationale":"x"}'):
            with self.subTest(raw=raw), patch.object(llm, "complete", return_value=raw):
                snapshot = runner.run_assessment(self.review.id, self.db)
                self.assertEqual(snapshot.results[0].status, "execution_failed")

    def test_prompt_injection_fixture_cannot_change_output_contract(self):
        fixture = json.loads((Path(__file__).resolve().parents[2] / "contracts/fixtures/assessment.json").read_text(encoding="utf-8"))
        attack = fixture["prompt_injection"]
        self.material = storage.save_material(build_preview("attack.md", attack.encode()), self.db)
        storage.upsert_review_material(self.review.id, self.material.id, None, None, self.db)
        self.link()
        messages = runner.build_messages(store.capture_scope(self.review.id, self.db), "c1")
        self.assertIn("untrusted data", messages[0]["content"])
        self.assertNotIn(attack, messages[0]["content"])
        self.assertIn("忽略评分标准", messages[1]["content"])
        self.assertEqual(messages[1]["content"].count("</UNTRUSTED_DATA_JSON>"), 1)
        snapshot = self.run_snapshot({"total_score": 100})
        self.assertEqual(snapshot.results[0].error_code, "invalid_response")

    def test_comparison_method_rubric_scoring_and_source_policy(self):
        self.link()
        first = self.run_snapshot()
        second = self.run_snapshot()
        self.assertEqual(core.compare_assessment_snapshots(first, second).status, "comparable")
        for field, value, code in (("assessment_method_version", "next", "method_mismatch"),
                ("source_policy_version", "next", "source_policy_mismatch"),
                ("scoring_definition_hash", "changed", "scoring_definition_mismatch")):
            changed = second.model_copy(deep=True)
            setattr(changed.scope, field, value)
            self.assertIn(code, core.compare_assessment_snapshots(first, changed).reason_codes)
        changed = second.model_copy(deep=True)
        changed.scope.rubric.revision = 2
        self.assertIn("rubric_mismatch", core.compare_assessment_snapshots(first, changed).reason_codes)

    def test_lineage_replacement_and_unrelated_same_title(self):
        self.link()
        first = self.run_snapshot()
        child, _ = storage.create_material_revision(self.material.id, build_preview("source.md", b"New measurements"),
                                                    review_id=self.review.id, db_path=self.db)
        storage.remove_review_material(self.review.id, self.material.id, self.db)
        self.link(material=child)
        second = self.run_snapshot()
        compared = core.compare_assessment_snapshots(first, second)
        self.assertEqual(compared.status, "comparable")
        self.assertTrue(compared.evidence_scope_changed)
        self.assertEqual(core.compare_assessment_snapshots(second, first).status, "not_comparable")
        unrelated = storage.save_material(build_preview("source.md", b"Same title unrelated"), self.db)
        storage.remove_review_material(self.review.id, child.id, self.db)
        storage.upsert_review_material(self.review.id, unrelated.id, None, None, self.db)
        third = self.run_snapshot()
        self.assertIn("material_scope_mismatch", core.compare_assessment_snapshots(first, third).reason_codes)

    def test_snapshot_immutable_and_survives_live_deletion(self):
        self.link()
        first = self.run_snapshot()
        second = self.run_snapshot()
        self.assertNotEqual(first.id, second.id)
        with self.assertRaises(sqlite3.IntegrityError):
            store.insert_snapshot(first, self.db)
        with closing(database.connect(self.db)) as connection, connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE assessment_snapshots SET payload='{}' WHERE id=?", (first.id,))
        storage.delete_material(self.material.id, self.db)
        storage.delete_review(self.review.id, self.db)
        restored = store.get_snapshot(first.id, self.db)
        self.assertEqual(restored, first)
        core.validate_snapshot(restored)

    def test_capture_is_stable_when_evidence_deleted_during_llm(self):
        self.link()
        def completion(settings, messages):
            storage.delete_material(self.material.id, self.db)
            return self.answer(messages)
        with patch.object(llm, "complete", side_effect=completion):
            snapshot = runner.run_assessment(self.review.id, self.db)
        self.assertEqual(snapshot.results[0].status, "assessed")
        core.validate_snapshot(snapshot)

    def test_http_create_list_read_compare_and_unknown(self):
        self.link()
        with patch.dict("os.environ", {"PREFLIGHT_DB_PATH": str(self.db)}), patch.object(llm, "complete", side_effect=lambda s, m: self.answer(m)):
            client = TestClient(app)
            response = client.post(f"/api/v1/reviews/{self.review.id}/assessments")
            self.assertEqual(response.status_code, 201, response.text)
            sid = response.json()["id"]
            self.assertEqual(client.get(f"/api/v1/assessments/{sid}").json(), response.json())
            self.assertEqual(len(client.get(f"/api/v1/reviews/{self.review.id}/assessments").json()), 1)
            self.assertEqual(client.get(f"/api/v1/assessments/{sid}/compare/{sid}").json()["status"], "comparable")
            self.assertEqual(client.get("/api/v1/assessments/unknown").status_code, 404)
            self.assertEqual(client.post("/api/v1/reviews/unknown/assessments").status_code, 404)
            self.assertEqual(client.post(f"/api/v1/reviews/{self.review.id}/assessments", json={"total_score": 100}).status_code, 400)
            self.assertEqual(client.get("/api/v1/health").status_code, 200)
            self.assertEqual(client.get("/openapi.json").status_code, 200)

    def test_scoring_contract_rejects_invalid_definitions(self):
        for update in ({"scoring_definition_version": "invented"}, {"max_score": float("inf")},
                       {"max_score": 1}, {"rubric_levels": []}):
            with self.assertRaises(ValidationError):
                Criterion.model_validate({**criterion().model_dump(), **update})
        for change in ({"score": 18}, {"max_score": None}, {"min_score": 21},
                       {"description": " "}, {"anchor_id": " "}):
            data = criterion().model_dump()
            data["rubric_levels"][0].update(change)
            with self.assertRaises(ValidationError):
                Criterion.model_validate(data)

    def test_mixed_unscorable_scope_never_rescales_partial_total(self):
        self.install(rubric([criterion(), Criterion(id="c2", title="Explanation", requirement="Explain", required_evidence=[])]))
        self.link()
        snapshot = self.run_snapshot()
        self.assertEqual([r.status for r in snapshot.results], ["assessed", "not_scorable"])
        self.assertEqual(snapshot.aggregation.scorable_criterion_count, 1)
        self.assertIsNone(snapshot.aggregation.score)

    def test_decimal_sum_and_prompt_bound_are_honest(self):
        small = []
        for cid, value in (("c1", 0.1), ("c2", 0.2)):
            c = criterion(cid, exact=True).model_dump()
            c["rubric_levels"][0]["score"] = value
            small.append(Criterion.model_validate(c))
        self.install(rubric(small))
        self.link()
        self.link("c2")
        snapshot = self.run_snapshot()
        self.assertEqual(snapshot.aggregation.score.minimum, 0.3)
        with patch.object(llm, "MAX_PROMPT_CHARS", 20), patch.object(llm, "complete") as completion:
            failed = runner.run_assessment(self.review.id, self.db)
        completion.assert_not_called()
        self.assertEqual(failed.results[0].error_code, "prompt_too_large")

    def test_comparison_overlap_and_became_insufficient(self):
        self.link()
        levels = criterion().model_dump()
        levels["rubric_levels"][1].update(min_score=14, max_score=18)
        self.install(rubric([Criterion.model_validate(levels)]))
        first = self.run_snapshot()
        second = self.run_snapshot({"selected_anchor_id": "B"})
        self.assertEqual(core.compare_assessment_snapshots(first, second).criteria[0].observation, "range_overlaps")
        third = self.run_snapshot({"status": "insufficient_evidence", "selected_anchor_id": None})
        self.assertEqual(core.compare_assessment_snapshots(first, third).criteria[0].observation, "became_insufficient")

    def test_llm_draft_cannot_author_execution_switches(self):
        payload = {"title": "invented", "scoring_aggregation": "sum_points_v1", "criteria": []}
        with patch.object(llm, "complete", return_value=json.dumps(payload)), self.assertRaises(llm.LlmInvalidResponse):
            draft_requirements(RubricDraftRequest(text="Some source standard", source_type="plain_text"))

    def test_structured_publish_preserves_execution_and_text_cannot_opt_in(self):
        draft = draft_requirements(RubricDraftRequest(source_type="rubric_json", text=self.rubric.model_dump_json()))
        published = rubric_store.publish(RubricPublish(**draft.model_dump(), confirmed=True), Path(self.tmp.name) / "rubrics")
        self.assertEqual(published.scoring_aggregation, "sum_points_v1")
        self.assertEqual(published.criteria[0].scoring_definition_version, "anchors-v1")
        text = draft.model_dump()
        text["source_type"] = "plain_text"
        with self.assertRaises(rubric_store.RubricRejected):
            rubric_store.publish(RubricPublish(**text, confirmed=True), Path(self.tmp.name) / "rubrics")


class AssessmentMigrationTests(unittest.TestCase):
    def test_v1_upgrade_identity_rollback_retry_and_fk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite"
            with closing(database.connect(path)) as connection, connection:
                migrations._create_schema(connection)
                connection.execute("PRAGMA user_version=1")
                connection.execute("INSERT INTO reviews VALUES ('old-review','old','r',1,'then','then')")
            original = migrations._migrate_to_v2
            def fail(connection):
                original(connection)
                raise RuntimeError("injected failure")
            with patch.object(migrations, "_migrate_to_v2", side_effect=fail), self.assertRaises(RuntimeError):
                database.init_db(path)
            with closing(database.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='assessment_snapshots'").fetchone())
                self.assertEqual(connection.execute("SELECT id FROM reviews").fetchone()[0], "old-review")
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            database.init_db(path)
            with closing(database.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT id FROM reviews").fetchone()[0], "old-review")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                connection.execute("PRAGMA user_version=3")
                with self.assertRaises(migrations.UnsupportedSchemaVersion):
                    migrations.bootstrap(connection)


if __name__ == "__main__":
    unittest.main()
