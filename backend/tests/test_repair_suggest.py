"""Leaf A：待核对问题的修复建议（stub LLM，无真实网络）。

TDD：本文件先写、先红，再实现 app/repair_suggest.py 与 POST /repair-suggestions。
纪律：调用前逐条复验 citation（quote == text[start:end]），任一条对不上就不调 LLM；
只接受 {suggestion, action} 严格 JSON（suggestion ≤ 200 字）；不落库、不改材料、不加表。
"""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import llm, main, repair_suggest, storage
from app.claim_inspector import inspect_statements
from app.consistency import find_numeric_findings
from app.contracts import Block, ConsistencyCitation, ConsistencyFinding, Locator
from app.markdown_preview import build_preview

TEXT = "本文系统准确率达到 95%。\n\n复现实验的准确率达到 90%。\n"
SUGGESTION_REPLY = json.dumps(
    {
        "suggestion": "先核对两次实验的统计口径，再把两处「准确率」统一为同一个数值或同一口径表述。",
        "action": "统一数值",
    },
    ensure_ascii=False,
)


def blocks_of(text: str):
    """预览 Block 与持久化无关；一致性判定只要求 block_id 能在 blocks 里找到。"""
    preview = build_preview("ev.md", text.encode("utf-8"))
    return [block.model_copy(update={"id": f"blk_{index}"}) for index, block in enumerate(preview.blocks)]


def finding_of(blocks):
    findings = find_numeric_findings(inspect_statements(blocks), blocks)
    assert findings, "fixture 必须产生一条待核对问题"
    return findings[0]


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


class RepairSuggestionPureTest(unittest.TestCase):
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

    def test_valid_finding_returns_suggestion_and_sends_quotes(self) -> None:
        blocks = blocks_of(TEXT)
        finding = finding_of(blocks)
        self.complete._replies = [SUGGESTION_REPLY]

        result = repair_suggest.suggest_repair(finding, blocks)

        self.assertEqual(result.action, "统一数值")
        self.assertIn("准确率", result.suggestion)
        self.assertEqual(len(self.complete.calls), 1)
        system, user = self.complete.calls[0]
        self.assertEqual(system["role"], "system")
        self.assertEqual(user["role"], "user")
        # 引用只来自材料原文：两条 quote 都进了 prompt，且写明 JSON 输出。
        self.assertIn("95%", user["content"])
        self.assertIn("90%", user["content"])
        self.assertIn("suggestion", user["content"])
        self.assertIn("JSON", system["content"])

    def test_quote_mismatch_raises_without_calling_llm(self) -> None:
        blocks = blocks_of(TEXT)
        broken = finding_of(blocks).model_copy(deep=True)
        broken.citations[0].quote = "95.5%"

        with self.assertRaises(repair_suggest.CitationMismatch):
            repair_suggest.suggest_repair(broken, blocks)
        self.assertEqual(self.complete.calls, [])

    def test_block_missing_raises_without_calling_llm(self) -> None:
        blocks = blocks_of(TEXT)
        broken = finding_of(blocks).model_copy(deep=True)
        broken.citations[0].block_id = "blk_missing"

        with self.assertRaises(repair_suggest.CitationMismatch):
            repair_suggest.suggest_repair(broken, blocks)
        self.assertEqual(self.complete.calls, [])

    def test_out_of_range_span_raises_without_calling_llm(self) -> None:
        blocks = blocks_of(TEXT)
        broken = finding_of(blocks).model_copy(deep=True)
        broken.citations[1].end = broken.citations[1].start  # 空区间复验不过

        with self.assertRaises(repair_suggest.CitationMismatch):
            repair_suggest.suggest_repair(broken, blocks)
        self.assertEqual(self.complete.calls, [])

    def test_invalid_replies_are_rejected(self) -> None:
        blocks = blocks_of(TEXT)
        finding = finding_of(blocks)
        cases = {
            "not_json": "不是 JSON",
            "extra_field": json.dumps({"suggestion": "改", "action": "统一", "confidence": 0.9}, ensure_ascii=False),
            "missing_action": json.dumps({"suggestion": "改"}, ensure_ascii=False),
            "blank_action": json.dumps({"suggestion": "改", "action": "  "}, ensure_ascii=False),
            "blank_suggestion": json.dumps({"suggestion": " ", "action": "统一"}, ensure_ascii=False),
            "overlong_suggestion": json.dumps({"suggestion": "改" * 201, "action": "统一"}, ensure_ascii=False),
        }
        for name, reply in cases.items():
            with self.subTest(name=name):
                self.complete._replies = [reply]
                with self.assertRaises(llm.LlmInvalidResponse):
                    repair_suggest.suggest_repair(finding, blocks)

    def test_unconfigured_settings_raise_without_calling_llm(self) -> None:
        blocks = blocks_of(TEXT)
        finding = finding_of(blocks)
        llm.load_settings = lambda: llm.LlmSettings(None, None, None, 1.0)

        with self.assertRaises(llm.LlmNotConfigured):
            repair_suggest.suggest_repair(finding, blocks)
        self.assertEqual(self.complete.calls, [])

    def test_oversized_prompt_is_rejected_without_calling_llm(self) -> None:
        text = ("甲" * 13000) + "95%" + ("乙" * 13000)
        blocks = [
            Block(
                id="blk_big",
                document_id="mat_big",
                ordinal=0,
                text=text,
                locator=Locator(kind="line", index=1, end_index=None, block_index=1),
            )
        ]
        finding = ConsistencyFinding(
            material_id="mat_big",
            kind="needs_review",
            measure="",
            values=["95%", "90%"],
            searched_block_count=1,
            searched_statement_count=2,
            statement_scan_limit=20,
            explanation="同一单位出现不同数值",
            citations=[
                ConsistencyCitation(
                    block_id="blk_big", line_number=1, quote="甲" * 13000, start=0, end=13000, value="95", unit="%"
                ),
                ConsistencyCitation(
                    block_id="blk_big", line_number=1, quote="乙" * 13000, start=13003, end=26003, value="90", unit="%"
                ),
            ],
        )

        with self.assertRaises(llm.PromptTooLarge):
            repair_suggest.build_messages(finding, repair_suggest.verify_citations(finding, blocks))
        self.assertEqual(self.complete.calls, [])


class RepairSuggestionRouteTest(unittest.TestCase):
    """API 直调层：临时库 + stub LLM；路由只加载材料并转交 repair_suggest。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "repair.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()
        self.material = storage.save_material(build_preview("ev.md", TEXT.encode("utf-8")))
        self.finding = finding_of(self.material.blocks)
        self._original_complete = llm.complete
        self._original_settings = llm.load_settings
        llm.load_settings = lambda: llm.LlmSettings("http://stub/v1", "stub-key", "stub-model", 1.0)
        self.complete = StubComplete([SUGGESTION_REPLY, SUGGESTION_REPLY])
        llm.complete = self.complete

    def tearDown(self) -> None:
        llm.complete = self._original_complete
        llm.load_settings = self._original_settings
        storage.connect = self._original_connect
        self._tmp.cleanup()

    def test_route_returns_suggestion_and_persists_nothing(self) -> None:
        first = main.create_repair_suggestion(self.material.id, self.finding)
        second = main.create_repair_suggestion(self.material.id, self.finding)

        self.assertEqual(first.action, "统一数值")
        self.assertEqual(second.suggestion, first.suggestion)
        self.assertEqual(len(self.complete.calls), 2)
        # 不落库：材料本体不变，且库里没有新增 repair 相关表。
        self.assertEqual(storage.get_material(self.material.id), self.material)
        with closing(sqlite3.connect(self.db)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual([name for name in tables if "repair" in name.lower()], [])

    def test_unknown_material_maps_to_material_not_found(self) -> None:
        with self.assertRaises(main.LookupFailed) as unknown:
            main.create_repair_suggestion("mat_missing", self.finding)
        self.assertEqual(unknown.exception.code, "material_not_found")
        self.assertEqual(self.complete.calls, [])

    def test_citation_mismatch_bubbles_up_and_llm_not_called(self) -> None:
        broken = self.finding.model_copy(deep=True)
        broken.citations[0].quote = "95.5%"
        with self.assertRaises(repair_suggest.CitationMismatch):
            main.create_repair_suggestion(self.material.id, broken)
        self.assertEqual(self.complete.calls, [])

    def test_citation_mismatch_handler_is_machine_readable(self) -> None:
        response = asyncio.run(main.citation_mismatch(None, repair_suggest.CitationMismatch("引用与原文不一致")))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body)["code"], "citation_mismatch")


if __name__ == "__main__":
    unittest.main()
