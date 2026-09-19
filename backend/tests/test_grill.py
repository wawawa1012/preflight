"""I9 答辩 Grill：stub LLM，无真实网络、无数据库。

纪律：prompt 只列已复验的原文片段；响应严格 JSON 且最多 5 条；
逐条复验 quote == block.text[start:end]，对不上整条丢弃（全丢是合法结果，返回空列表）；
不判分、不落库、不改材料；位置数字只来自 Block 的 Locator。
"""
import json
import unittest
from dataclasses import replace

from app import grill, llm
from app.claim_inspector import inspect_statements
from app.consistency import find_numeric_findings
from app.contracts import DetectedStatement, SavedMaterial
from app.markdown_preview import build_preview

TEXT = "本文系统准确率达到 95%。\n\n复现实验的准确率达到 90%。\n"


def material_of(text: str, material_id: str = "mat_grill") -> SavedMaterial:
    """预览 Block 与持久化无关；grill 只要求 block_id 能在 material.blocks 里找到。"""
    preview = build_preview("ev.md", text.encode("utf-8"))
    blocks = [block.model_copy(update={"id": f"blk_{index}"}) for index, block in enumerate(preview.blocks)]
    return SavedMaterial(
        id=material_id,
        filename="ev.md",
        size_bytes=len(text.encode("utf-8")),
        sha256="a" * 64,
        line_count=preview.line_count,
        created_at="2026-09-19T00:00:00+00:00",
        blocks=blocks,
    )


def reply_of(*questions: dict) -> str:
    return json.dumps({"questions": list(questions)}, ensure_ascii=False)


def sources_of(material):
    statements = inspect_statements(material.blocks)
    return grill.prepare_sources(find_numeric_findings(statements, material.blocks), statements, material.blocks)


def question_of(statement: DetectedStatement, prompt: str) -> dict:
    """This two-block fixture has one source per block, in block order."""
    return {"prompt": prompt, "source_id": f"s{int(statement.block_id.split('_')[-1]) + 1}"}


class StubComplete:
    """按序返回预设响应；记录每次调用，供「不得调用 LLM」断言。"""

    def __init__(self, replies=(), error=None):
        self.calls = []
        self._replies = list(replies)
        self._error = error

    def __call__(self, settings, messages):
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        return self._replies.pop(0) if self._replies else "{}"


class GrillPureTest(unittest.TestCase):
    """纯函数层：零数据库、零网络（stub complete/load_settings）。"""

    def setUp(self) -> None:
        self._original_complete = llm.complete
        self._original_settings = llm.load_settings
        llm.load_settings = lambda: llm.LlmSettings("http://stub/v1", "stub-key", "stub-model", 1.0)
        self.complete = StubComplete()
        llm.complete = self.complete

    def tearDown(self) -> None:
        llm.complete = self._original_complete
        llm.load_settings = self._original_settings

    def statements_of(self, material: SavedMaterial) -> list[DetectedStatement]:
        statements = inspect_statements(material.blocks)
        self.assertEqual(len(statements), 2, "fixture 必须产生两条关键陈述")
        return statements

    def test_valid_reply_returns_verified_questions(self) -> None:
        material = material_of(TEXT)
        first, second = self.statements_of(material)
        self.complete._replies = [
            reply_of(
                question_of(first, "请说明「95%」的统计口径与实验条件。"),
                question_of(second, "复现实验的「90%」与主实验差异的原因是什么？"),
            )
        ]

        questions = grill.generate_grill(material)

        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0].quote, "95%")
        self.assertEqual(questions[0].block_id, first.block_id)
        self.assertEqual(questions[0].start, first.start)
        self.assertEqual(questions[0].end, first.end)
        self.assertEqual(questions[1].quote, "90%")
        self.assertEqual(len(self.complete.calls), 1)
        system, user = self.complete.calls[0]
        self.assertEqual(system["role"], "system")
        self.assertEqual(user["role"], "user")
        # prompt 只列材料原文里的问题与陈述，并写明 JSON 输出与条数上限。
        self.assertIn("95%", user["content"])
        self.assertIn("90%", user["content"])
        self.assertIn("准确率", user["content"])
        self.assertIn("questions", user["content"])
        self.assertIn("JSON", system["content"])
        self.assertIn("最多 5 条", system["content"])

    def test_unknown_source_is_dropped_not_fixed(self) -> None:
        material = material_of(TEXT)
        first, second = self.statements_of(material)
        broken = question_of(first, "「95.5%」是怎么回事？")
        broken["source_id"] = "s_missing"

        self.complete._replies = [reply_of(broken, question_of(second, "请说明复现实验口径。"))]
        questions = grill.generate_grill(material)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].quote, "90%")
        self.assertEqual(len(self.complete.calls), 1)

    def test_all_mismatched_returns_empty_list(self) -> None:
        material = material_of(TEXT)
        first, second = self.statements_of(material)
        first_bad = question_of(first, "问题一")
        first_bad["source_id"] = "s_missing1"
        second_bad = question_of(second, "问题二")
        second_bad["source_id"] = "s_missing2"

        self.complete._replies = [reply_of(first_bad, second_bad)]
        questions = grill.generate_grill(material)

        self.assertEqual(questions, [])
        self.assertEqual(len(self.complete.calls), 1)

    def test_out_of_range_span_is_dropped(self) -> None:
        material = material_of(TEXT)
        first, second = self.statements_of(material)
        out_of_range = question_of(second, "问题")
        sources = sources_of(material)
        sources[1] = replace(sources[1], end=len(material.blocks[1].text) + 5)
        raw = grill.parse_questions(reply_of(question_of(first, "保留的问题"), out_of_range))
        questions = grill.verify_questions(raw, sources, material.blocks)

        self.assertEqual([item.quote for item in questions], ["95%"])

    def test_unconfigured_settings_raise_without_calling_llm(self) -> None:
        material = material_of(TEXT)
        llm.load_settings = lambda: llm.LlmSettings(None, None, None, 1.0)

        with self.assertRaises(llm.LlmNotConfigured):
            grill.generate_grill(material)
        self.assertEqual(self.complete.calls, [])

    def test_invalid_replies_are_rejected(self) -> None:
        material = material_of(TEXT)
        first, _second = self.statements_of(material)
        good = question_of(first, "合法问题")
        cases = {
            "not_json": "不是 JSON",
            "top_level_extra": json.dumps({"questions": [good], "scores": []}, ensure_ascii=False),
            "questions_not_array": json.dumps({"questions": {}}, ensure_ascii=False),
            "item_not_object": json.dumps({"questions": ["问题"]}, ensure_ascii=False),
            "extra_field": json.dumps({"questions": [{**good, "line_number": 7}]}, ensure_ascii=False),
            "missing_field": json.dumps({"questions": [{k: v for k, v in good.items() if k != "source_id"}]}, ensure_ascii=False),
            "blank_prompt": json.dumps({"questions": [{**good, "prompt": "  "}]}, ensure_ascii=False),
            "overlong_prompt": json.dumps({"questions": [{**good, "prompt": "问" * 201}]}, ensure_ascii=False),
            "source_not_string": json.dumps({"questions": [{**good, "source_id": 10}]}, ensure_ascii=False),
            "model_coordinates": reply_of({"prompt": "问题", "quote": first.quote, "block_id": first.block_id, "start": first.start, "end": first.end}),
            "too_many": json.dumps({"questions": [good] * (grill.MAX_QUESTIONS + 1)}, ensure_ascii=False),
        }
        for name, reply in cases.items():
            with self.subTest(name=name):
                self.complete._replies = [reply]
                with self.assertRaises(llm.LlmInvalidResponse):
                    grill.generate_grill(material)

    def test_oversized_prompt_is_rejected_without_calling_llm(self) -> None:
        statements = [
            DetectedStatement(
                block_id="blk_big", line_number=1, quote="甲" * 13000, start=0, end=13000, signal="numeric"
            ),
            DetectedStatement(
                block_id="blk_big", line_number=1, quote="乙" * 13000, start=13000, end=26000, signal="numeric"
            ),
        ]

        with self.assertRaises(llm.PromptTooLarge):
            grill.build_messages([grill.Source(f"s{i}", s.block_id, s.quote, s.start, s.end, "test", "")
                                  for i, s in enumerate(statements)])
        self.assertEqual(self.complete.calls, [])

    def test_statements_in_prompt_are_capped_at_eight(self) -> None:
        material = material_of("\n\n".join(f"第{i}项指标达到 50%。" for i in range(1, 11)) + "\n")
        self.complete._replies = [reply_of()]

        grill.generate_grill(material)

        _system, user = self.complete.calls[0]
        sources = sources_of(material)
        self.assertEqual(len(sources), grill.MAX_STATEMENTS_IN_PROMPT)
        self.assertNotIn('"source_id": "s9"', user["content"])
        self.assertEqual(find_numeric_findings(inspect_statements(material.blocks), material.blocks), [])

    def test_empty_material_abstains_without_llm(self) -> None:
        material = material_of("没有数字的一句话。\n")
        self.complete._replies = [reply_of()]

        questions = grill.generate_grill(material)

        self.assertEqual(questions, [])
        self.assertEqual(self.complete.calls, [])

    def test_prompt_has_no_conclusion_or_contest_words(self) -> None:
        for forbidden in ("已满足", "已支撑", "分数", "参赛"):
            self.assertNotIn(forbidden, grill.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
