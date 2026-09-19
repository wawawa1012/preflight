"""Iteration 5 + R2B：LLM 适配层的解析、配置、prompt 上限、窗口化调用与错误分类测试（无真实网络调用）。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import llm
from app.contracts import Block, Criterion, Locator
from app.prompt_planner import plan_windows


def make_block(block_id: str = "blk_1", text: str = "中文语料：准确率达到 95%，整体稳定。", index: int = 7) -> Block:
    return Block(
        id=block_id,
        document_id="mat_x",
        ordinal=0,
        text=text,
        locator=Locator(kind="line", index=index, end_index=None, block_index=1),
    )


def make_criterion() -> Criterion:
    return Criterion(
        id="crit_implementation",
        title="技术实现与关键指标可验证",
        requirement="关键数字在材料中有明确出处，数字与结论一致。",
        required_evidence=["关键数字及其出处的原文"],
    )


def candidates_payload(items: list[tuple[str, str, str]]) -> str:
    """构造 LLM 应答：items 为 (block_id, quote, rationale)。"""
    return json.dumps(
        {
            "candidates": [
                {"block_id": block_id, "quote": quote, "rationale": rationale}
                for block_id, quote, rationale in items
            ]
        },
        ensure_ascii=False,
    )


def two_window_blocks() -> list[Block]:
    """4 个 ~8000 字 block：plan_windows 切成两窗 [b0,b1] / [b2,b3]（单块远小于上限）。"""
    return [make_block(f"blk_w{i}", "长文本。" * 2000, index=i + 1) for i in range(4)]


def many_short_blocks(count: int = 100) -> list[Block]:
    """100 个短 block（每块 ~300 字）合计超单窗上限：plan_windows 必然切多窗。"""
    return [make_block(f"blk_s{i:03d}", "句子。" * 100, index=i + 1) for i in range(count)]


class ParseCandidatesTest(unittest.TestCase):
    def test_valid_single_and_multiple(self) -> None:
        one = llm.parse_candidates(
            '{"candidates":[{"block_id":"blk_1","quote":"准确率达到 95%","rationale":"与指标相关"}]}'
        )
        self.assertEqual(len(one), 1)
        self.assertIsNone(one[0].risk_note)

        many = llm.parse_candidates(
            '{"candidates":['
            '{"block_id":"blk_1","quote":"准确率达到 95%","rationale":"相关","risk_note":"需复核"},'
            '{"block_id":"blk_2","quote":"第二行","rationale":"相关"}'
            "]}"
        )
        self.assertEqual([item.block_id for item in many], ["blk_1", "blk_2"])
        self.assertEqual(many[0].risk_note, "需复核")

    def test_empty_candidates_list_is_valid(self) -> None:
        self.assertEqual(llm.parse_candidates('{"candidates":[]}'), [])

    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaises(llm.LlmInvalidResponse):
            llm.parse_candidates(
                '{"candidates":[{"block_id":"blk_1","quote":"x","rationale":"y","confidence":0.9}]}'
            )
        with self.assertRaises(llm.LlmInvalidResponse):
            llm.parse_candidates('{"candidates":[],"note":"extra"}')

    def test_missing_fields_are_rejected(self) -> None:
        for payload in (
            '{"candidates":[{"quote":"x","rationale":"y"}]}',
            '{"candidates":[{"block_id":"blk_1","rationale":"y"}]}',
            '{"candidates":[{"block_id":"blk_1","quote":"x"}]}',
            '{"candidates":[{"block_id":"blk_1","quote":"x","rationale":"   "}]}',
        ):
            with self.assertRaises(llm.LlmInvalidResponse):
                llm.parse_candidates(payload)

    def test_invalid_json_and_shape_are_rejected(self) -> None:
        for payload in ("not json", '["candidates"]', '{"candidates":{}}', '{"candidates":[1]}'):
            with self.assertRaises(llm.LlmInvalidResponse):
                llm.parse_candidates(payload)


class BuildMessagesTest(unittest.TestCase):
    def test_prompt_contains_criterion_and_blocks(self) -> None:
        messages = llm.build_messages(make_criterion(), [make_block()])
        self.assertEqual(messages[0]["role"], "system")
        user = messages[1]["content"]
        self.assertIn("crit_implementation", user)
        self.assertIn("blk_1", user)
        self.assertIn("准确率达到 95%", user)

    def test_prompt_v2_requires_direct_evidence_and_allows_abstention(self) -> None:
        messages = llm.build_messages(make_criterion(), [make_block()])
        joined = messages[0]["content"] + messages[1]["content"]
        self.assertIn("直接依据", joined)
        self.assertIn("练习", joined)
        self.assertIn("candidates 必须为 []", joined)
        self.assertNotIn("最多 8", joined)

    def test_oversize_prompt_is_rejected_not_truncated(self) -> None:
        huge = make_block(text="长文本" * 20000)
        with self.assertRaises(llm.PromptTooLarge):
            llm.build_messages(make_criterion(), [huge])


class CompletionCapTest(unittest.TestCase):
    """I6.2：输出封顶与 prompt v2.1（只为延迟，不为 precision）。"""

    def setUp(self) -> None:
        self._original_openai = llm.OpenAI
        self._saved = {key: os.environ.get(key) for key in (
            "PREFLIGHT_LLM_BASE_URL",
            "PREFLIGHT_LLM_API_KEY",
            "PREFLIGHT_LLM_MODEL",
        )}
        os.environ["PREFLIGHT_LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
        os.environ["PREFLIGHT_LLM_API_KEY"] = "test-key"
        os.environ["PREFLIGHT_LLM_MODEL"] = "test-model"

    def tearDown(self) -> None:
        llm.OpenAI = self._original_openai
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_prompt_v26_caps_rationale_and_candidate_count(self) -> None:
        messages = llm.build_messages(make_criterion(), [make_block()])
        joined = messages[0]["content"] + messages[1]["content"]
        self.assertIn("最多 3 条", joined)
        self.assertIn("40", joined)
        self.assertEqual(llm.PROMPT_VERSION, "p5-criterion-preflight-v2.6")

    def test_create_does_not_send_max_tokens(self) -> None:
        captured: dict = {}

        class Message:
            content = '{"candidates":[]}'

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        class StubCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return Response()

        class StubChat:
            completions = StubCompletions()

        class StubClient:
            def __init__(self, **kwargs):
                self.chat = StubChat()

        llm.OpenAI = StubClient
        llm.propose_candidates(make_criterion(), [make_block()])
        self.assertNotIn("max_tokens", captured)


class SettingsAndEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in (
            "PREFLIGHT_LLM_BASE_URL",
            "PREFLIGHT_LLM_API_KEY",
            "PREFLIGHT_LLM_MODEL",
            "PREFLIGHT_LLM_TIMEOUT_S",
        )}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_unconfigured_and_configured(self) -> None:
        for key in self._saved:
            os.environ.pop(key, None)
        self.assertFalse(llm.load_settings().configured)
        with self.assertRaises(llm.LlmNotConfigured):
            llm.propose_candidates(make_criterion(), [make_block()])

        os.environ["PREFLIGHT_LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
        os.environ["PREFLIGHT_LLM_API_KEY"] = "test-key"
        os.environ["PREFLIGHT_LLM_MODEL"] = "test-model"
        os.environ["PREFLIGHT_LLM_TIMEOUT_S"] = "3"
        settings = llm.load_settings()
        self.assertTrue(settings.configured)
        self.assertEqual(settings.timeout_s, 3.0)
        os.environ["PREFLIGHT_LLM_TIMEOUT_S"] = "not-a-number"
        self.assertEqual(llm.load_settings().timeout_s, llm.DEFAULT_TIMEOUT_S)

    def test_env_file_parsing_does_not_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# comment\nPREFLIGHT_LLM_MODEL=from-file\nPREFLIGHT_LLM_API_KEY=file-key\nBROKEN LINE\n",
                encoding="utf-8",
            )
            os.environ.pop("PREFLIGHT_LLM_MODEL", None)
            os.environ["PREFLIGHT_LLM_API_KEY"] = "already-set"
            llm.load_env_file(path)
            self.assertEqual(os.environ["PREFLIGHT_LLM_MODEL"], "from-file")
            self.assertEqual(os.environ["PREFLIGHT_LLM_API_KEY"], "already-set")


class CompleteErrorMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_openai = llm.OpenAI
        self._saved = {key: os.environ.get(key) for key in (
            "PREFLIGHT_LLM_BASE_URL",
            "PREFLIGHT_LLM_API_KEY",
            "PREFLIGHT_LLM_MODEL",
        )}
        os.environ["PREFLIGHT_LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
        os.environ["PREFLIGHT_LLM_API_KEY"] = "test-key"
        os.environ["PREFLIGHT_LLM_MODEL"] = "test-model"

    def tearDown(self) -> None:
        llm.OpenAI = self._original_openai
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _stub_client(self, error: Exception):
        class StubCompletions:
            def create(self, **kwargs):
                raise error

        class StubChat:
            completions = StubCompletions()

        class StubClient:
            def __init__(self, **kwargs):
                self.chat = StubChat()

        return StubClient

    def test_upstream_error_maps_to_unavailable(self) -> None:
        llm.OpenAI = self._stub_client(llm.OpenAIError("boom"))
        with self.assertRaises(llm.LlmUnavailable):
            llm.propose_candidates(make_criterion(), [make_block()])

    def test_timeout_maps_to_timeout(self) -> None:
        llm.OpenAI = self._stub_client(llm.APITimeoutError(request=object()))
        with self.assertRaises(llm.LlmTimeout):
            llm.propose_candidates(make_criterion(), [make_block()])

    def test_empty_response_maps_to_invalid(self) -> None:
        class EmptyMessage:
            content = None

        class EmptyChoice:
            message = EmptyMessage()

        class EmptyResponse:
            choices = [EmptyChoice()]

        class StubCompletions:
            def create(self, **kwargs):
                return EmptyResponse()

        class StubChat:
            completions = StubCompletions()

        class StubClient:
            def __init__(self, **kwargs):
                self.chat = StubChat()

        llm.OpenAI = StubClient
        with self.assertRaises(llm.LlmInvalidResponse):
            llm.propose_candidates(make_criterion(), [make_block()])

    def test_client_sends_opencode_session_and_product_ua(self) -> None:
        captured: dict = {}

        class StubCompletions:
            def create(self, **kwargs):
                raise llm.OpenAIError("stop-after-init")

        class StubChat:
            completions = StubCompletions()

        class StubClient:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)
                self.chat = StubChat()

        llm.OpenAI = StubClient
        with self.assertRaises(llm.LlmUnavailable):
            llm.propose_candidates(make_criterion(), [make_block()])
        headers = captured.get("default_headers") or {}
        self.assertEqual(headers.get("User-Agent"), "preflight/0.1")
        session = headers.get("x-opencode-session") or ""
        self.assertTrue(session.startswith("preflight-"), session)
        self.assertEqual(session, llm._SESSION_ID)


class LlmLoggingTest(unittest.TestCase):
    """I5.1：调用观测日志（不改契约）。token 仅在 usage 存在时记录。"""

    def setUp(self) -> None:
        self._original_openai = llm.OpenAI
        self._saved = {key: os.environ.get(key) for key in (
            "PREFLIGHT_LLM_BASE_URL",
            "PREFLIGHT_LLM_API_KEY",
            "PREFLIGHT_LLM_MODEL",
        )}
        os.environ["PREFLIGHT_LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
        os.environ["PREFLIGHT_LLM_API_KEY"] = "test-key"
        os.environ["PREFLIGHT_LLM_MODEL"] = "test-model"

    def tearDown(self) -> None:
        llm.OpenAI = self._original_openai
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @staticmethod
    def _stub_client(response):
        class StubCompletions:
            def create(self, **kwargs):
                return response

        class StubChat:
            completions = StubCompletions()

        class StubClient:
            def __init__(self, **kwargs):
                self.chat = StubChat()

        return StubClient

    @staticmethod
    def _response(content: str, usage=None):
        class Usage:
            pass

        class Message:
            def __init__(self) -> None:
                self.content = content

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        response = Response()
        if usage is not None:
            response.usage = usage
        return response

    def test_logs_timing_version_and_usage(self) -> None:
        usage = type("Usage", (), {"prompt_tokens": 101, "completion_tokens": 7})()
        llm.OpenAI = self._stub_client(self._response('{"candidates":[]}', usage))
        with self.assertLogs("preflight.llm", level="INFO") as captured:
            candidates, _, _, _ = llm.propose_candidates(make_criterion(), [make_block()])
        self.assertEqual(candidates, [])
        joined = "\n".join(captured.output)
        self.assertIn(f"prompt_version={llm.PROMPT_VERSION}", joined)
        self.assertIn("model=test-model", joined)
        self.assertIn("block_count=1", joined)
        self.assertIn("prompt_chars=", joined)
        self.assertIn("elapsed_ms=", joined)
        self.assertIn("candidate_count=0", joined)
        self.assertIn("prompt_tokens=101", joined)
        self.assertIn("completion_tokens=7", joined)

    def test_missing_usage_omits_tokens_without_crash(self) -> None:
        content = '{"candidates":[{"block_id":"blk_1","quote":"准确率达到 95%","rationale":"相关"}]}'
        llm.OpenAI = self._stub_client(self._response(content))
        with self.assertLogs("preflight.llm", level="INFO") as captured:
            candidates, _, _, _ = llm.propose_candidates(make_criterion(), [make_block()])
        self.assertEqual(len(candidates), 1)
        joined = "\n".join(captured.output)
        self.assertIn("candidate_count=1", joined)
        self.assertNotIn("prompt_tokens=", joined)
        self.assertNotIn("completion_tokens=", joined)


class WindowedProposalTest(unittest.TestCase):
    """R2B：逐窗调用（plan_windows）、坏 JSON 单窗重试一次、跨窗去重合并与逐窗 raw_content。"""

    def setUp(self) -> None:
        self._original_complete = llm.complete
        self._saved = {key: os.environ.get(key) for key in (
            "PREFLIGHT_LLM_BASE_URL",
            "PREFLIGHT_LLM_API_KEY",
            "PREFLIGHT_LLM_MODEL",
        )}
        os.environ["PREFLIGHT_LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
        os.environ["PREFLIGHT_LLM_API_KEY"] = "test-key"
        os.environ["PREFLIGHT_LLM_MODEL"] = "test-model"

    def tearDown(self) -> None:
        llm.complete = self._original_complete
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def stub_complete(self, payloads: list[str]) -> list[list[dict[str, str]]]:
        """按调用序返回 payloads，并记录每次 messages；调用超出列表时沿用最后一条。"""
        calls: list[list[dict[str, str]]] = []

        def fake_complete(settings, messages):
            calls.append(messages)
            return payloads[min(len(calls), len(payloads)) - 1]

        llm.complete = fake_complete
        return calls

    def test_many_short_blocks_send_one_complete_per_window(self) -> None:
        criterion = make_criterion()
        blocks = many_short_blocks()
        windows = plan_windows(criterion, blocks)
        self.assertGreater(len(windows), 1, "本测试需要多窗场景")
        payloads = [
            candidates_payload([(window[0].id, f"第 {index} 窗引用", "理由")])
            for index, window in enumerate(windows)
        ]
        calls = self.stub_complete(payloads)

        candidates, _, provider, model = llm.propose_candidates(criterion, blocks)

        self.assertEqual(len(calls), len(windows))
        self.assertEqual([item.block_id for item in candidates], [window[0].id for window in windows])
        for index, call in enumerate(calls):
            user = call[1]["content"]
            self.assertIn(windows[index][0].id, user)
            if index + 1 < len(windows):
                self.assertNotIn(windows[index + 1][0].id, user)
        self.assertEqual(provider, "http://127.0.0.1:9/v1")
        self.assertEqual(model, "test-model")

    def test_small_material_sends_exactly_one_complete(self) -> None:
        payload = candidates_payload([("blk_1", "准确率达到 95%", "相关")])
        calls = self.stub_complete([payload])

        candidates, raw_content, _, _ = llm.propose_candidates(make_criterion(), [make_block()])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(candidates), 1)
        self.assertIn(payload, raw_content)

    def test_merge_two_windows_keeps_every_unique_candidate(self) -> None:
        criterion = make_criterion()
        blocks = two_window_blocks()
        windows = plan_windows(criterion, blocks)
        self.assertEqual(len(windows), 2, "本测试需要恰好两窗")
        first = [
            (windows[0][0].id, "第一窗引用甲", "理由甲"),
            (windows[0][0].id, "第一窗引用乙", "理由乙"),
            (windows[0][1].id, "第一窗引用丙", "理由丙"),
        ]
        second = [
            (windows[1][0].id, "第二窗引用丁", "理由丁"),
            (windows[1][1].id, "第二窗引用戊", "理由戊"),
        ]
        calls = self.stub_complete([candidates_payload(first), candidates_payload(second)])

        candidates, _, _, _ = llm.propose_candidates(criterion, blocks)

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [(item.block_id, item.quote, item.rationale) for item in candidates],
            first + second,
        )
        self.assertGreater(len(candidates), 3, "跨窗合并不得截断到 3 条")

    def test_duplicate_block_quote_is_kept_once_from_first_window(self) -> None:
        criterion = make_criterion()
        blocks = two_window_blocks()
        windows = plan_windows(criterion, blocks)
        first = [(windows[0][0].id, "同一句原文", "第一窗理由")]
        second = [
            (windows[0][0].id, "同一句原文", "第二窗理由"),
            (windows[1][1].id, "另一句原文", "第二窗理由"),
        ]
        self.stub_complete([candidates_payload(first), candidates_payload(second)])

        candidates, _, _, _ = llm.propose_candidates(criterion, blocks)

        self.assertEqual(
            [(item.block_id, item.quote, item.rationale) for item in candidates],
            [first[0], second[1]],
        )

    def test_safety_cap_limits_merged_unique_candidates_to_twelve(self) -> None:
        criterion = make_criterion()
        blocks = two_window_blocks()
        windows = plan_windows(criterion, blocks)
        first = [(windows[0][0].id, f"第一窗引用{i}", "理由") for i in range(7)]
        second = [(windows[1][0].id, f"第二窗引用{i}", "理由") for i in range(7)]
        self.stub_complete([candidates_payload(first), candidates_payload(second)])

        with self.assertLogs("preflight.llm", level="WARNING") as captured:
            candidates, _, _, _ = llm.propose_candidates(criterion, blocks)

        self.assertEqual(llm.MAX_MERGED_CANDIDATES, 12)
        self.assertEqual(len(candidates), llm.MAX_MERGED_CANDIDATES)
        self.assertEqual(
            [item.quote for item in candidates],
            [quote for _, quote, _ in first + second][: llm.MAX_MERGED_CANDIDATES],
        )
        self.assertIn("safety cap", "\n".join(captured.output))

    def test_bad_json_retries_the_same_window_once_then_succeeds(self) -> None:
        payload = candidates_payload([("blk_1", "准确率达到 95%", "相关")])
        calls = self.stub_complete(["这不是 JSON", payload])

        candidates, raw_content, _, _ = llm.propose_candidates(make_criterion(), [make_block()])

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1], "重试必须复用同一窗口的 prompt")
        self.assertEqual(len(candidates), 1)
        self.assertIn(payload, raw_content)
        self.assertNotIn("这不是 JSON", raw_content, "最终 raw_content 只保留每窗成功载荷")

    def test_retry_stays_inside_its_own_window(self) -> None:
        criterion = make_criterion()
        blocks = two_window_blocks()
        windows = plan_windows(criterion, blocks)
        payloads = [
            "still not json",
            candidates_payload([(windows[0][0].id, "第一窗引用", "理由")]),
            candidates_payload([(windows[1][0].id, "第二窗引用", "理由")]),
        ]
        calls = self.stub_complete(payloads)

        candidates, raw_content, _, _ = llm.propose_candidates(criterion, blocks)

        self.assertEqual(len(calls), 3, "仅坏窗重试一次，其他窗各一次")
        self.assertEqual([item.block_id for item in candidates], [windows[0][0].id, windows[1][0].id])
        self.assertIn("--- window 1/2 ---", raw_content)
        self.assertIn("--- window 2/2 ---", raw_content)

    def test_two_bad_json_mark_scan_incomplete_and_return_nothing(self) -> None:
        calls = self.stub_complete(["{坏 JSON", "{仍然坏"])

        with self.assertRaises(llm.LlmInvalidResponse) as ctx:
            llm.propose_candidates(make_criterion(), [make_block()])

        self.assertEqual(len(calls), 2, "同一窗最多重试一次")
        message = str(ctx.exception)
        self.assertIn("window 1/1", message)
        self.assertIn("未完成", message)
        self.assertEqual(ctx.exception.raw_response, "{仍然坏")

    def test_later_window_failure_never_returns_partial_candidates(self) -> None:
        criterion = make_criterion()
        blocks = two_window_blocks()
        windows = plan_windows(criterion, blocks)
        self.assertEqual(len(windows), 2)
        payloads = [
            candidates_payload([(windows[0][0].id, "第一窗引用", "理由")]),
            "坏 JSON 之一",
            "坏 JSON 之二",
        ]
        calls = self.stub_complete(payloads)

        with self.assertRaises(llm.LlmInvalidResponse) as ctx:
            llm.propose_candidates(criterion, blocks)

        self.assertEqual(len(calls), 3, "第一窗一次 + 第二窗重试一次")
        message = str(ctx.exception)
        self.assertIn("window 2/2", message)
        self.assertIn("未完成", message)
        self.assertEqual(ctx.exception.raw_response, "坏 JSON 之二")

    def test_raw_content_keeps_every_window_payload(self) -> None:
        criterion = make_criterion()
        blocks = two_window_blocks()
        first = candidates_payload([("blk_a", "第一窗引用", "理由")])
        second = candidates_payload([("blk_b", "第二窗引用", "理由")])
        self.stub_complete([first, second])

        _, raw_content, _, _ = llm.propose_candidates(criterion, blocks)

        self.assertIn("--- window 1/2 ---", raw_content)
        self.assertIn("--- window 2/2 ---", raw_content)
        self.assertIn(first, raw_content)
        self.assertIn(second, raw_content)
        self.assertNotEqual(raw_content, second, "raw_content 不得只留最后一窗")

    def test_oversized_single_block_raises_before_any_call(self) -> None:
        huge = make_block("blk_huge", "长文本" * 20000)
        calls = self.stub_complete([])

        with self.assertRaises(llm.PromptTooLarge):
            llm.propose_candidates(make_criterion(), [huge])

        self.assertEqual(calls, [], "超限材料不得发出任何请求，也不得丢块")

    def test_window_logging_reports_progress_and_retry_count(self) -> None:
        payload = candidates_payload([("blk_1", "准确率达到 95%", "相关")])
        self.stub_complete(["{坏 JSON", payload])

        with self.assertLogs("preflight.llm", level="INFO") as captured:
            candidates, _, _, _ = llm.propose_candidates(make_criterion(), [make_block()])

        self.assertEqual(len(candidates), 1)
        joined = "\n".join(captured.output)
        for fragment in (
            f"prompt_version={llm.PROMPT_VERSION}",
            "model=test-model",
            "window_index=1",
            "window_count=1",
            "block_count=1",
            "prompt_chars=",
            "elapsed_ms=",
            "retry_count=1",
            "candidate_count=1",
        ):
            self.assertIn(fragment, joined)
        self.assertNotIn("prompt_tokens=", joined, "无 usage 时不得编 token 数")
        self.assertNotIn("completion_tokens=", joined, "无 usage 时不得编 token 数")


if __name__ == "__main__":
    unittest.main()
