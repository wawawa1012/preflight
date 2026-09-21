"""Iteration 5：提案验证门、accept 原子物化与裁决测试（合成数据，test-only）。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import database
from app import storage
from app.markdown_preview import build_preview
from app.storage import CandidateInput

TEXT = "中文语料：准确率达到 95%，整体稳定。"
QUOTE = "准确率达到 95%"


class AgentProposalTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        database.init_db(self.db)
        self.material = storage.save_material(build_preview("ev.md", TEXT.encode("utf-8")), self.db)
        self.block = self.material.blocks[0]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def save(self, candidates, criterion_id="c_syn_1", status="completed", error=None, raw_response='{"candidates":[]}'):
        return storage.save_agent_proposal(
            self.material,
            criterion_id,
            "rubric_syn",
            1,
            "stub",
            "stub-model",
            "p5-criterion-preflight-v1",
            status,
            error,
            raw_response,
            candidates,
            self.db,
        )

    def valid_candidate(self) -> CandidateInput:
        return CandidateInput(self.block.id, QUOTE, "人工判断：该引用与该项相关")

    def test_validation_gate_marks_candidates_with_machine_codes(self) -> None:
        proposal = self.save(
            [
                self.valid_candidate(),
                CandidateInput("blk_missing", QUOTE, "相关"),
                CandidateInput(self.block.id, "不存在的引用", "相关"),
            ]
        )
        self.assertEqual(
            [(c.validation_status, c.validation_code) for c in proposal.candidates],
            [("passed", None), ("invalid", "block_not_found"), ("invalid", "quote_not_found")],
        )
        self.assertEqual([c.ordinal for c in proposal.candidates], [0, 1, 2])
        self.assertTrue(all(c.review_status == "unreviewed" for c in proposal.candidates))

    def test_failed_proposal_is_persisted_and_visible(self) -> None:
        failed = self.save([], status="failed", error="llm_timeout")
        listed = storage.list_agent_proposals(self.material.id, db_path=self.db)
        self.assertEqual(listed[0].id, failed.id)
        self.assertEqual(listed[0].status, "failed")
        self.assertEqual(listed[0].error, "llm_timeout")
        self.assertIsNone(storage.get_agent_proposal("ap_missing", self.db))

    def test_list_filters_by_criterion(self) -> None:
        first = self.save([self.valid_candidate()], criterion_id="c_syn_1")
        second = self.save([self.valid_candidate()], criterion_id="c_syn_2")
        only_first = storage.list_agent_proposals(self.material.id, "c_syn_1", self.db)
        self.assertEqual([item.id for item in only_first], [first.id])
        self.assertEqual(len(storage.list_agent_proposals(self.material.id, db_path=self.db)), 2)
        self.assertIn(second.id, [item.id for item in storage.list_agent_proposals(self.material.id, db_path=self.db)])

    def test_accept_materializes_with_agent_provenance(self) -> None:
        proposal = self.save([self.valid_candidate()])
        candidate = proposal.candidates[0]

        result = storage.accept_candidate(self.material.id, candidate.id, self.db)
        self.assertIsNotNone(result)
        self.assertEqual(result.annotation.proposed_by, "agent")
        self.assertEqual(result.link.proposed_by, "agent")
        self.assertEqual((result.annotation.source.start, result.annotation.source.end), (5, 14))
        self.assertEqual(result.annotation.source.quote, QUOTE)
        self.assertEqual(result.link.rationale, "人工判断：该引用与该项相关")
        self.assertEqual(result.link.criterion_id, "c_syn_1")
        self.assertEqual(result.link.rubric_id, "rubric_syn")

        updated = storage.get_agent_proposal(proposal.id, self.db).candidates[0]
        self.assertEqual(updated.review_status, "accepted")
        self.assertEqual(updated.created_annotation_id, result.annotation.id)
        self.assertEqual(updated.created_link_id, result.link.id)
        self.assertEqual([link.id for link in storage.list_links(self.material.id, self.db)], [result.link.id])

    def test_accept_is_atomic_under_injected_failure(self) -> None:
        proposal = self.save([self.valid_candidate()])
        candidate_id = proposal.candidates[0].id
        with closing(database.connect(self.db)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER reject_candidate_update BEFORE UPDATE ON proposal_candidates"
                " BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            storage.accept_candidate(self.material.id, candidate_id, self.db)

        self.assertEqual(storage.list_evidence_annotations(self.material.id, self.db), [])
        self.assertEqual(storage.list_links(self.material.id, self.db), [])
        after = storage.get_agent_proposal(proposal.id, self.db).candidates[0]
        self.assertEqual(after.review_status, "unreviewed")
        self.assertIsNone(after.created_annotation_id)
        self.assertIsNone(after.created_link_id)

    def test_accept_rejects_invalid_and_reviewed_candidates(self) -> None:
        invalid = self.save([CandidateInput("blk_missing", QUOTE, "相关")]).candidates[0]
        with self.assertRaises(storage.InvalidCandidate):
            storage.accept_candidate(self.material.id, invalid.id, self.db)

        valid = self.save([self.valid_candidate()]).candidates[0]
        storage.accept_candidate(self.material.id, valid.id, self.db)
        with self.assertRaises(storage.CandidateAlreadyReviewed):
            storage.accept_candidate(self.material.id, valid.id, self.db)

        rejected = self.save([self.valid_candidate()]).candidates[0]
        storage.reject_candidate(self.material.id, rejected.id, "不采用", self.db)
        with self.assertRaises(storage.CandidateAlreadyReviewed):
            storage.accept_candidate(self.material.id, rejected.id, self.db)

    def test_semantic_duplicate_is_rejected_without_residue(self) -> None:
        first = self.save([self.valid_candidate()])
        storage.accept_candidate(self.material.id, first.candidates[0].id, self.db)

        second = self.save([self.valid_candidate()])
        with self.assertRaises(storage.DuplicateLink):
            storage.accept_candidate(self.material.id, second.candidates[0].id, self.db)
        self.assertEqual(len(storage.list_evidence_annotations(self.material.id, self.db)), 1)
        self.assertEqual(len(storage.list_links(self.material.id, self.db)), 1)
        after = storage.get_agent_proposal(second.id, self.db).candidates[0]
        self.assertEqual(after.review_status, "unreviewed")

    def test_cross_material_access_returns_none_and_isolates_lists(self) -> None:
        proposal = self.save([self.valid_candidate()])
        candidate_id = proposal.candidates[0].id
        other = storage.save_material(build_preview("other.md", "乙\n".encode("utf-8")), self.db)
        self.assertIsNone(storage.accept_candidate(other.id, candidate_id, self.db))
        self.assertIsNone(storage.reject_candidate(other.id, candidate_id, "x", self.db))
        self.assertEqual(storage.list_agent_proposals(other.id, db_path=self.db), [])

    def test_reject_records_reason_and_persists_across_connections(self) -> None:
        proposal = self.save([self.valid_candidate()])
        candidate_id = proposal.candidates[0].id
        rejected = storage.reject_candidate(self.material.id, candidate_id, "证据不足以外的人工决定", self.db)
        self.assertEqual(rejected.review_status, "rejected")
        self.assertEqual(rejected.reject_reason, "证据不足以外的人工决定")

        reloaded = storage.get_agent_proposal(proposal.id, self.db).candidates[0]
        self.assertEqual(reloaded.review_status, "rejected")
        self.assertEqual(reloaded.reject_reason, "证据不足以外的人工决定")
        self.assertIsNone(storage.reject_candidate(self.material.id, "apc_missing", None, self.db))

    def test_material_delete_cascades_proposals(self) -> None:
        target = storage.save_material(build_preview("target.md", "甲\n".encode("utf-8")), self.db)
        storage.save_material(build_preview("keep.md", "乙\n".encode("utf-8")), self.db)
        proposal = storage.save_agent_proposal(
            target, "c_syn_1", "rubric_syn", 1, "stub", "m", "p5", "completed", None, "{}", [], self.db
        )
        with closing(database.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM materials WHERE id = ?", (target.id,))
        self.assertIsNone(storage.get_agent_proposal(proposal.id, self.db))


if __name__ == "__main__":
    unittest.main()
