"""LLM 适配层：环境配置、单 criterion 预检 prompt、严格 JSON 解析与错误分类。

只做一次 chat completion 调用，不引入编排框架；绝不静默截断 prompt。
配置缺失/上游失败/超时/响应不合 schema 分别抛不同异常，由 API 层映射为 503/502/504/502。
"""
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, OpenAI, OpenAIError

from .contracts import Block, Criterion

PROMPT_VERSION = "p5-criterion-preflight-v2.1"
MAX_PROMPT_CHARS = 24000
DEFAULT_TIMEOUT_S = 60.0
# OpenCode Go 网关按会话路由，要求稳定的 x-opencode-session，且 UA 不能是通用 SDK 名。
_SESSION_ID = f"preflight-{uuid.uuid4().hex}"
_CLIENT_HEADERS = {"User-Agent": "preflight/0.1", "x-opencode-session": _SESSION_ID}

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

logger = logging.getLogger("preflight.llm")

SYSTEM_PROMPT = (
    "你是参赛材料预检助手。任务：从给定 blocks 中找出可作为「本项目材料对该评分要求的直接依据」的原文片段。"
    "必须遵守："
    "1. 只使用给定的 blocks，不得编造 block_id、quote、页码或结论；quote 必须是该 block 原文的精确子串。"
    "2. 不判断要求是否满足，只说明该片段为何能作为本项目的直接依据。"
    "3. 教程、课后练习、模拟考题、语言语法说明、与本项目无关的泛技术知识，即使主题词沾边，也不是证据，不得输出为候选。"
    "4. 没有直接依据时必须输出 {\"candidates\":[]}。空数组是正常结果，且优于任何牵强候选。"
    "5. 每个候选 rationale 不超过 40 个汉字；candidates 最多 3 条。"
    "6. 只输出严格 JSON，不要输出任何其他文字。"
)


class LlmNotConfigured(Exception):
    def __init__(self, message: str = "未配置 LLM（PREFLIGHT_LLM_BASE_URL/API_KEY/MODEL）") -> None:
        self.message = message
        super().__init__(message)


class LlmUnavailable(Exception):
    def __init__(self, message: str = "LLM 上游不可用") -> None:
        self.message = message
        super().__init__(message)


class LlmTimeout(Exception):
    def __init__(self, message: str = "LLM 请求超时") -> None:
        self.message = message
        super().__init__(message)


class LlmInvalidResponse(Exception):
    def __init__(self, message: str = "LLM 响应不符合 schema", raw_response: str | None = None) -> None:
        self.message = message
        self.raw_response = raw_response
        super().__init__(message)


class PromptTooLarge(Exception):
    def __init__(self, message: str = "prompt 超出上限") -> None:
        self.message = message
        super().__init__(message)


@dataclass
class LlmSettings:
    base_url: str | None
    api_key: str | None
    model: str | None
    timeout_s: float

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


@dataclass
class RawCandidate:
    block_id: str
    quote: str
    rationale: str
    risk_note: str | None = None


def load_env_file(path: Path = _ENV_FILE) -> None:
    """十行内手写 .env 解析：KEY=VALUE，跳过空行与 # 注释，不覆盖已有环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_settings() -> LlmSettings:
    try:
        timeout_s = float(os.environ.get("PREFLIGHT_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    except ValueError:
        timeout_s = DEFAULT_TIMEOUT_S
    return LlmSettings(
        base_url=os.environ.get("PREFLIGHT_LLM_BASE_URL"),
        api_key=os.environ.get("PREFLIGHT_LLM_API_KEY"),
        model=os.environ.get("PREFLIGHT_LLM_MODEL"),
        timeout_s=timeout_s,
    )


def build_messages(criterion: Criterion, blocks: list[Block]) -> list[dict[str, str]]:
    lines = [
        "评分要求（criterion）：",
        f"- id: {criterion.id}",
        f"- title: {criterion.title}",
        f"- requirement: {criterion.requirement}",
        f"- required_evidence: {'；'.join(criterion.required_evidence) or '（无）'}",
        "",
        "材料 blocks（完整原文；block_id 必须原样返回）：",
    ]
    for block in blocks:
        lines.append(f"[{block.id}] line {block.locator.index}: {block.text}")
    lines.extend(
        [
            "",
            '输出 JSON（不要多余字段）：{"candidates":[{"block_id":"...","quote":"原文精确子串",'
            '"rationale":"为什么可能相关","risk_note":"可选风险提示"}]}',
            "若没有本项目自身的直接依据，candidates 必须为 []。",
        ]
    )
    user = "\n".join(lines)
    if len(SYSTEM_PROMPT) + len(user) > MAX_PROMPT_CHARS:
        raise PromptTooLarge(f"prompt 长度 {len(SYSTEM_PROMPT) + len(user)} 超过 {MAX_PROMPT_CHARS}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


_CANDIDATE_FIELDS = {"block_id", "quote", "rationale", "risk_note"}


def parse_candidates(content: str) -> list[RawCandidate]:
    """严格解析：必须是 JSON 对象且只含 candidates；每个候选字段必须合法。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmInvalidResponse(f"响应不是合法 JSON（{exc.msg}）") from exc
    if not isinstance(payload, dict) or set(payload) != {"candidates"}:
        raise LlmInvalidResponse("响应必须是只含 candidates 的 JSON 对象")
    items = payload["candidates"]
    if not isinstance(items, list):
        raise LlmInvalidResponse("candidates 必须是数组")
    parsed: list[RawCandidate] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise LlmInvalidResponse(f"candidates[{index}] 不是对象")
        extra = set(item) - _CANDIDATE_FIELDS
        if extra:
            raise LlmInvalidResponse(f"candidates[{index}] 含未知字段：{sorted(extra)}")
        block_id = item.get("block_id")
        quote = item.get("quote")
        rationale = item.get("rationale")
        if not isinstance(block_id, str) or not block_id:
            raise LlmInvalidResponse(f"candidates[{index}].block_id 缺失")
        if not isinstance(quote, str) or not quote:
            raise LlmInvalidResponse(f"candidates[{index}].quote 缺失")
        if not isinstance(rationale, str) or not rationale.strip():
            raise LlmInvalidResponse(f"candidates[{index}].rationale 缺失")
        risk_note = item.get("risk_note")
        if risk_note is not None and not isinstance(risk_note, str):
            raise LlmInvalidResponse(f"candidates[{index}].risk_note 非法")
        parsed.append(RawCandidate(block_id=block_id, quote=quote, rationale=rationale, risk_note=risk_note))
    return parsed


def _usage_fields(usage: object) -> str:
    """usage 存在才附 token 字段；缺失时省略而不是编 0。"""
    if usage is None:
        return ""
    fields = ""
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    if prompt_tokens is not None:
        fields += f" prompt_tokens={prompt_tokens}"
    completion_tokens = getattr(usage, "completion_tokens", None)
    if completion_tokens is not None:
        fields += f" completion_tokens={completion_tokens}"
    return fields


def complete(settings: LlmSettings, messages: list[dict[str, str]]) -> str:
    client = OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=settings.timeout_s,
        default_headers=_CLIENT_HEADERS,
    )
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=800,
        )
    except APITimeoutError as exc:
        raise LlmTimeout() from exc
    except (APIConnectionError, OpenAIError) as exc:
        raise LlmUnavailable(str(exc)) from exc
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "llm call model=%s prompt_version=%s elapsed_ms=%.1f%s",
        settings.model,
        PROMPT_VERSION,
        elapsed_ms,
        _usage_fields(getattr(response, "usage", None)),
    )
    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise LlmInvalidResponse("响应内容为空")
    return content


def propose_candidates(criterion: Criterion, blocks: list[Block]) -> tuple[list[RawCandidate], str, str, str]:
    """配置检查 → 构建 prompt → 单次调用 → 严格解析；返回 (candidates, raw_content, provider, model)。"""
    settings = load_settings()
    if not settings.configured:
        raise LlmNotConfigured()
    messages = build_messages(criterion, blocks)
    prompt_chars = sum(len(message["content"]) for message in messages)
    content = complete(settings, messages)
    try:
        candidates = parse_candidates(content)
    except LlmInvalidResponse as exc:
        exc.raw_response = content
        raise
    logger.info(
        "llm proposal model=%s prompt_version=%s block_count=%d prompt_chars=%d candidate_count=%d",
        settings.model,
        PROMPT_VERSION,
        len(blocks),
        prompt_chars,
        len(candidates),
    )
    return candidates, content, settings.base_url or "", settings.model or ""
