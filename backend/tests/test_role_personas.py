"""角色人设契约：依据审计员 / 修复顾问 / 质询官三条 LLM 角色的 prompt 边界（无真实 LLM 调用）。

三个角色共用一个 LLM 客户端，但纪律各不相同：
- 依据审计员（llm.SYSTEM_PROMPT，PROMPT_VERSION v2.4）：只认直接依据，没有就空数组，禁止常识脑补/弱相关；
- 修复顾问（repair_suggest.SYSTEM_PROMPT）：只谈文本怎么改，不创造新事实、不替用户在冲突数字中选边；
- 质询官（grill.SYSTEM_PROMPT）：只出题不打分，引用对不上就丢题，全丢返回空列表是合法结果。

中立性/抗脑补这类语义约束 parser 无法判定（例如 {"suggestion":"选88%"} 结构完全合法），
只能由 SYSTEM_PROMPT 文本承载：人设断言直接读 prompt；行为层用 StubComplete 替换 llm.complete，
复用 test_grill / test_repair_suggest 的 fixture helper。
"""
import json
import unittest

from app import grill, llm, repair_suggest
from app.claim_inspector import inspect_statements
from tests.test_grill import material_of, question_of, reply_of
from tests.test_repair_suggest import StubComplete, blocks_of, finding_of

TEXT = "本文系统准确率达到 95%。\n\n复现实验的准确率达到 90%。\n"


class StubLlmMixin:
    """把 llm.complete / llm.load_settings 换成 stub：零网络、零数据库。"""

    def setUp(self) -> None:
        self._original_complete = llm.complete
        self._original_settings = llm.load_settings
        llm.load_settings = lambda: llm.LlmSettings("http://stub/v1", "stub-key", "stub-model", 1.0)
        self.complete = StubComplete()
        llm.complete = self.complete

    def tearDown(self) -> None:
        llm.complete = self._original_complete
        llm.load_settings = self._original_settings


class EvidenceAuditorPersonaTest(unittest.TestCase):
    """依据审计员：人设名、弃权条款、抗脑补条款、版本钉死。"""

    def test_persona_name_and_abstention_clause(self) -> None:
        prompt = llm.SYSTEM_PROMPT
        self.assertIn("依据审计员", prompt)
        self.assertIn("没有直接依据", prompt)
        # 空数组必须是显式合法结果，而不是兜底。
        self.assertIn('{"candidates":[]}', prompt)

    def test_anti_hallucination_clause(self) -> None:
        prompt = llm.SYSTEM_PROMPT
        self.assertTrue(
            "禁止常识脑补" in prompt or "弱相关" in prompt,
            "依据审计员必须禁止常识脑补/弱相关候选",
        )

    def test_no_contest_wording(self) -> None:
        self.assertNotIn("参赛", llm.SYSTEM_PROMPT)

    def test_prompt_version_is_v24(self) -> None:
        self.assertTrue(llm.PROMPT_VERSION.endswith("v2.4"), llm.PROMPT_VERSION)


class RepairAdvisorPersonaTest(unittest.TestCase):
    """修复顾问：只给文本改稿方向；中立性由 prompt 承载，parser 只做结构校验。"""

    def test_persona_name_and_no_new_facts(self) -> None:
        prompt = repair_suggest.SYSTEM_PROMPT
        self.assertIn("修复顾问", prompt)
        self.assertIn("不创造新事实", prompt)

    def test_prompt_forbids_picking_a_side(self) -> None:
        prompt = repair_suggest.SYSTEM_PROMPT
        self.assertTrue(
            "不替用户选择" in prompt or "不假定任何一方正确" in prompt,
            "修复顾问必须在 prompt 里禁止替用户在冲突数值中选边",
        )


class RepairAdvisorBehaviorTest(StubLlmMixin, unittest.TestCase):
    """两条数值冲突路径：结构合法即通过（parser 无法 NLP 判定），非法 JSON 一律拒绝。"""

    def test_side_picking_payload_still_parses_structurally(self) -> None:
        # parser 只校验结构；「选88%」这种越权建议在结构上合法，越权与否只能靠 prompt 约束。
        blocks = blocks_of(TEXT)
        finding = finding_of(blocks)  # 95% vs 90% 数值对照
        self.complete._replies = [json.dumps({"suggestion": "选88%", "action": "选值"}, ensure_ascii=False)]

        result = repair_suggest.suggest_repair(finding, blocks)

        self.assertEqual(result.action, "选值")
        self.assertEqual(result.suggestion, "选88%")
        _system, user = self.complete.calls[0]
        self.assertIn("95%", user["content"])
        self.assertIn("90%", user["content"])
        self.assertTrue(
            "不替用户选择" in repair_suggest.SYSTEM_PROMPT
            or "不假定任何一方正确" in repair_suggest.SYSTEM_PROMPT,
            "越权建议在 parser 层无法拦截，约束必须落在 prompt",
        )

    def test_conflicting_numbers_still_require_strict_json(self) -> None:
        blocks = blocks_of(TEXT)
        finding = finding_of(blocks)
        self.complete._replies = ["直接选 88% 就好"]

        with self.assertRaises(llm.LlmInvalidResponse):
            repair_suggest.suggest_repair(finding, blocks)

    def test_conflicting_numbers_reject_extra_fields(self) -> None:
        blocks = blocks_of(TEXT)
        finding = finding_of(blocks)
        self.complete._replies = [
            json.dumps({"suggestion": "选88%", "action": "选值", "chosen": "88"}, ensure_ascii=False)
        ]

        with self.assertRaises(llm.LlmInvalidResponse):
            repair_suggest.suggest_repair(finding, blocks)


class ChallengeExaminerPersonaTest(unittest.TestCase):
    """质询官：只出题、不打分、不判合格；没有可对应的原文就不出题。"""

    def test_persona_name_and_quote_discipline(self) -> None:
        prompt = grill.SYSTEM_PROMPT
        self.assertIn("质询官", prompt)
        self.assertIn("没有可对应的原文就不出题", prompt)

    def test_no_scoring_clause(self) -> None:
        prompt = grill.SYSTEM_PROMPT
        self.assertIn("不打分", prompt)
        self.assertNotIn("参赛", prompt)


class ChallengeExaminerBehaviorTest(StubLlmMixin, unittest.TestCase):
    """mock 追问逐条复验：坏引用整条丢弃；全丢返回空列表是合法结果，不是错误。"""

    def statements_of(self, material):
        statements = inspect_statements(material.blocks)
        self.assertEqual(len(statements), 2, "fixture 必须产生两条关键陈述")
        return statements

    def test_matching_quote_is_kept(self) -> None:
        material = material_of(TEXT)
        first, second = self.statements_of(material)
        self.complete._replies = [
            reply_of(
                question_of(first, "请说明「95%」的统计口径与实验条件。"),
                question_of(second, "复现实验的「90%」与主实验差异的原因是什么？"),
            )
        ]

        questions = grill.generate_grill(material)

        self.assertEqual([item.quote for item in questions], ["95%", "90%"])
        self.assertEqual(questions[0].block_id, first.block_id)
        self.assertEqual(questions[0].start, first.start)
        self.assertEqual(questions[0].end, first.end)

    def test_bad_quote_is_dropped_and_empty_list_is_legal(self) -> None:
        material = material_of(TEXT)
        first, _second = self.statements_of(material)
        bad = question_of(first, "「95.5%」是怎么回事？")
        bad["quote"] = "95.5%"  # 原文没有这个片段
        self.complete._replies = [reply_of(bad)]

        questions = grill.generate_grill(material)

        self.assertEqual(questions, [])
        self.assertEqual(len(self.complete.calls), 1, "复验失败是丢弃而不是重调 LLM")
        # 直接复用 verify_questions：坏引用整条丢弃（不修、不猜）。
        raw = grill.parse_questions(reply_of(bad))
        self.assertEqual(grill.verify_questions(raw, material.blocks), [])

    def test_mixed_batch_keeps_only_verified(self) -> None:
        material = material_of(TEXT)
        first, second = self.statements_of(material)
        bad = question_of(second, "「90.5%」来源？")
        bad["quote"] = "90.5%"
        self.complete._replies = [reply_of(question_of(first, "保留的问题"), bad)]

        questions = grill.generate_grill(material)

        self.assertEqual([item.quote for item in questions], ["95%"])


class RoleSeparationTest(unittest.TestCase):
    """三个角色互不串味：人设名各归各家，谁都不谈竞赛/打分式语言。"""

    def test_no_contest_wording_in_any_role(self) -> None:
        roles = {
            "evidence": llm.SYSTEM_PROMPT,
            "repair": repair_suggest.SYSTEM_PROMPT,
            "grill": grill.SYSTEM_PROMPT,
        }
        for name, prompt in roles.items():
            with self.subTest(role=name):
                self.assertNotIn("参赛", prompt)

    def test_personas_are_distinct(self) -> None:
        personas = {
            "依据审计员": llm.SYSTEM_PROMPT,
            "修复顾问": repair_suggest.SYSTEM_PROMPT,
            "质询官": grill.SYSTEM_PROMPT,
        }
        for persona, own_prompt in personas.items():
            with self.subTest(persona=persona):
                self.assertIn(persona, own_prompt)
                for other in personas:
                    if other != persona:
                        self.assertNotIn(other, own_prompt)


if __name__ == "__main__":
    unittest.main()
