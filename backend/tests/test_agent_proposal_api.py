"""Iteration 5：Agent 提案 API 直调测试（stub LLM，无真实网络；合成 rubric，test-only）。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app import database
from app import llm, main, rubric_store, storage
from app.contracts import AgentProposalCreate, Criterion, ProposalCandidateReject, Rubric
from app.markdown_preview import build_preview

TEXT = "中文语料：准确率达到 95%，整体稳定。"
QUOTE = "准确率达到 95%"


def synthetic_rubric() -> Rubric:
    return Rubric(
        id="rubric_syn",
        revision=1,
        title="Synthetic rubric (test-only)",
        source_note="test-only synthetic",
        criteria=[
            Criterion(id="c_syn_1", title="Criterion A", requirement="requirement A", required_evidence=["x"]),
            Criterion(id="c_syn_2", title="Criterion B", requirement="requirement B", required_evidence=["y"]),
        ],
    )


class AgentProposalApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "api.db"
        self._original_connect = database.connect
        database.connect = lambda db_path=database.DEFAULT_DB_PATH: self._original_connect(self.db)
        database.init_db()
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric()})

        self._original_propose = llm.propose_candidates
        self.material = storage.save_material(build_preview("ev.md", TEXT.encode("utf-8")))
        self.block = self.material.blocks[0]
        storage.bind_material_rubric(self.material.id, "rubric_syn", 1)

    def tearDown(self) -> None:
        llm.propose_candidates = self._original_propose
        database.connect = self._original_connect
        rubric_store.reset_index()
        self._tmp.cleanup()

    def stub_llm(self, candidates, raw='{"candidates":[]}', error=None):
        def fake(criterion, blocks):
            if error is not None:
                raise error
            return candidates, raw, "http://stub/v1", "stub-model"

        llm.propose_candidates = fake

    def test_unbound_or_unknown_inputs_are_rejected(self) -> None:
        other = storage.save_material(build_preview("other.md", "乙\n".encode("utf-8")))
        with self.assertRaises(storage.RubricNotBound):
            main.create_agent_proposal(other.id, AgentProposalCreate(criterion_id="c_syn_1"))
        with self.assertRaises(main.LookupFailed) as unknown_material:
            main.create_agent_proposal("mat_missing", AgentProposalCreate(criterion_id="c_syn_1"))
        self.assertEqual(unknown_material.exception.code, "material_not_found")
        with self.assertRaises(main.LookupFailed) as unknown_criterion:
            main.create_agent_proposal(self.material.id, AgentProposalCreate(criterion_id="c_missing"))
        self.assertEqual(unknown_criterion.exception.code, "criterion_not_found")

    def test_completed_proposal_validates_candidates(self) -> None:
        self.stub_llm(
            [
                llm.RawCandidate(self.block.id, QUOTE, "相关", "需复核"),
                llm.RawCandidate("blk_missing", QUOTE, "相关"),
                llm.RawCandidate(self.block.id, "不存在的引用", "相关"),
            ]
        )
        proposal = main.create_agent_proposal(self.material.id, AgentProposalCreate(criterion_id="c_syn_1"))
        self.assertEqual(proposal.status, "completed")
        self.assertEqual(proposal.provider, "http://stub/v1")
        self.assertEqual(proposal.prompt_version, llm.PROMPT_VERSION)
        self.assertEqual(
            [(c.validation_status, c.validation_code) for c in proposal.candidates],
            [("passed", None), ("invalid", "block_not_found"), ("invalid", "quote_not_found")],
        )
        self.assertEqual(main.agent_proposal_by_id(proposal.id).id, proposal.id)
        self.assertEqual(len(main.material_agent_proposals(self.material.id)), 1)
        self.assertEqual(len(main.material_agent_proposals(self.material.id, "c_syn_2")), 0)

    def test_failure_paths_persist_failed_proposal_and_raise(self) -> None:
        cases = [
            (llm.LlmNotConfigured(), "llm_unconfigured"),
            (llm.LlmTimeout(), "llm_timeout"),
            (llm.LlmUnavailable("upstream 500"), "llm_unavailable"),
            (llm.LlmInvalidResponse("bad json", raw_response="not json"), "llm_invalid_response"),
            (llm.PromptTooLarge("too big"), "material_too_large"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.stub_llm([], error=error)
                with self.assertRaises(type(error)):
                    main.create_agent_proposal(self.material.id, AgentProposalCreate(criterion_id="c_syn_1"))
                failed = main.material_agent_proposals(self.material.id)[0]
                self.assertEqual(failed.status, "failed")
                self.assertTrue(failed.error.startswith(expected), failed.error)
                self.assertEqual(failed.candidates, [])

    def test_accept_and_reject_endpoints(self) -> None:
        self.stub_llm([llm.RawCandidate(self.block.id, QUOTE, "人工判断相关")])
        proposal = main.create_agent_proposal(self.material.id, AgentProposalCreate(criterion_id="c_syn_1"))
        candidate = proposal.candidates[0]

        acceptance = main.accept_proposal_candidate(self.material.id, candidate.id)
        self.assertEqual(acceptance.annotation.proposed_by, "agent")
        self.assertEqual(acceptance.link.proposed_by, "agent")
        self.assertEqual(acceptance.link.criterion_id, "c_syn_1")
        self.assertEqual(len(storage.list_links(self.material.id)), 1)

        second = main.create_agent_proposal(self.material.id, AgentProposalCreate(criterion_id="c_syn_2"))
        rejected = main.reject_proposal_candidate(
            self.material.id, second.candidates[0].id, ProposalCandidateReject(reason="不采用")
        )
        self.assertEqual(rejected.review_status, "rejected")
        self.assertEqual(rejected.reject_reason, "不采用")

        with self.assertRaises(main.LookupFailed) as missing_candidate:
            main.accept_proposal_candidate(self.material.id, "apc_missing")
        self.assertEqual(missing_candidate.exception.code, "candidate_not_found")
        with self.assertRaises(main.LookupFailed) as missing_proposal:
            main.agent_proposal_by_id("ap_missing")
        self.assertEqual(missing_proposal.exception.code, "proposal_not_found")

    def test_error_handlers_are_machine_readable(self) -> None:
        cases = [
            (main.llm_unconfigured(None, llm.LlmNotConfigured()), 503, "llm_unconfigured"),
            (main.llm_unavailable(None, llm.LlmUnavailable()), 502, "llm_unavailable"),
            (main.llm_timeout(None, llm.LlmTimeout()), 504, "llm_timeout"),
            (main.llm_invalid_response(None, llm.LlmInvalidResponse()), 502, "llm_invalid_response"),
            (main.prompt_too_large(None, llm.PromptTooLarge()), 400, "material_too_large"),
            (main.invalid_candidate(None, storage.InvalidCandidate()), 400, "invalid_candidate"),
        ]
        for handler, status, code in cases:
            with self.subTest(code=code):
                response = asyncio.run(handler)
                self.assertEqual(response.status_code, status)
                self.assertEqual(json.loads(response.body)["code"], code)


if __name__ == "__main__":
    unittest.main()
