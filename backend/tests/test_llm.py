"""Iteration 5：LLM 适配层的解析、配置、prompt 上限与错误分类测试（无真实网络调用）。"""
import os
import tempfile
import unittest
from pathlib import Path

from app import llm
from app.contracts import Block, Criterion, Locator


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

    def test_prompt_v22_caps_rationale_and_candidate_count(self) -> None:
        messages = llm.build_messages(make_criterion(), [make_block()])
        joined = messages[0]["content"] + messages[1]["content"]
        self.assertIn("最多 3 条", joined)
        self.assertIn("40", joined)
        self.assertEqual(llm.PROMPT_VERSION, "p5-criterion-preflight-v2.2")

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


if __name__ == "__main__":
    unittest.main()
