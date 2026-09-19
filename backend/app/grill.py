"""I9 答辩 Grill v1：把当前材料里已发现的问题转成带原文引用的答辩追问。

只读材料（调用方传入 SavedMaterial，本模块不碰库）；一次请求一次 LLM 调用。
prompt 列出数值对照问题（度量词/不同数值/引用）与至多 8 条关键陈述，只给已复验过的原文片段。
响应只接受严格 JSON：{"questions":[{prompt, quote, block_id, start, end}]}，最多 5 条；
超过 5 条或不合 schema 抛 LlmInvalidResponse（API 层映射 502），绝不静默截断。
解析后逐条复验 quote == block.text[start:end]：对不上的整条丢弃，不修、不猜；
全部丢弃就返回空列表——空列表是合法结果。位置数字只来自 Block 的 Locator，绝不编造。
不判分、不落库、不写材料；追问是答辩准备材料，不是结论。
"""
import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from . import llm
from .claim_inspector import inspect_statements
from .consistency import find_numeric_findings
from .contracts import Block, ConsistencyFinding, DetectedStatement, SavedMaterial

MAX_QUESTIONS = 5
MAX_STATEMENTS_IN_PROMPT = 8
PROMPT_MAX_CHARS = 200

logger = logging.getLogger("preflight.grill")

SYSTEM_PROMPT = (
    "你是质询官。任务：根据给定的「已发现的问题」与「关键陈述」，提出需要材料作者解释清楚的问题。"
    "必须遵守："
    "1. 只从给定列表出题：每个问题的 quote 必须从列表照抄，block_id、start、end 必须与列表给出的一致；"
    "不得编造、改写或补充引用。"
    "2. 每个问题都必须能对应列表中的原文；没有可对应的原文就不出题，输出空数组（空数组是正常结果）。"
    "3. 只提问题，不给答案、不给修改建议；不打分、不判断材料是否合格、不预测结果；不写「满足/支撑」类判词。"
    "4. 问题只针对需要解释清楚的点（数值口径、依据出处、前后说法）。"
    "5. 每条 prompt 不超过 200 字；questions 最多 5 条，宁少勿多。"
    '6. 只输出严格 JSON：{"questions":[{"prompt":"...","quote":"...","block_id":"...","start":n,"end":n}]}，'
    "不要任何其他文字。"
)


class GrillRequest(BaseModel):
    """答辩追问请求：只接受用户显式选中的一份材料。"""

    material_id: str = Field(min_length=1)


class GrillQuestion(BaseModel):
    """答辩追问：quote == block.text[start:end]（复验通过才返回，否则整条丢弃）。"""

    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_CHARS)
    quote: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)


@dataclass
class RawQuestion:
    """解析通过、尚未复验的追问；只有复验通过才会变成 GrillQuestion。"""

    prompt: str
    quote: str
    block_id: str
    start: int
    end: int


def build_messages(
    findings: list[ConsistencyFinding], statements: list[DetectedStatement]
) -> list[dict[str, str]]:
    """组 prompt：数值问题在前，关键陈述至多 8 条；只列已复验的 quote 与 span。"""
    lines = ["已发现的问题（同材料数值对照；quote 为材料原文精确片段）："]
    if findings:
        for index, finding in enumerate(findings, start=1):
            lines.append(
                f"[问题 {index}] 类型：{finding.kind}；度量词：{finding.measure or '（无共同度量词）'}；"
                f"不同数值：{'、'.join(finding.values)}"
            )
            for citation in finding.citations:
                lines.append(
                    f"    引用：「{citation.quote}」"
                    f"（block_id={citation.block_id}，start={citation.start}，end={citation.end}）"
                )
    else:
        lines.append("（当前材料尚未发现数值对照问题）")
    lines.extend(["", f"关键陈述（材料原文精确片段，最多 {MAX_STATEMENTS_IN_PROMPT} 条）："])
    selected = statements[:MAX_STATEMENTS_IN_PROMPT]
    if selected:
        for index, statement in enumerate(selected, start=1):
            lines.append(
                f"[{index}] 「{statement.quote}」"
                f"（block_id={statement.block_id}，start={statement.start}，end={statement.end}）"
            )
    else:
        lines.append("（当前材料未扫描到关键陈述）")
    lines.extend(
        [
            "",
            '输出 JSON（不要多余字段）：{"questions":[{"prompt":"不超过 200 字的答辩追问",'
            '"quote":"从上面列表照抄的原文片段","block_id":"对应 block_id","start":整数,"end":整数}]}',
            f"questions 最多 {MAX_QUESTIONS} 条；没有可追问的就输出 {{\"questions\":[]}}。",
        ]
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
    prompt_chars = sum(len(message["content"]) for message in messages)
    if prompt_chars > llm.MAX_PROMPT_CHARS:
        raise llm.PromptTooLarge(f"prompt 长度 {prompt_chars} 超过 {llm.MAX_PROMPT_CHARS}")
    return messages


_QUESTION_FIELDS = {"prompt", "quote", "block_id", "start", "end"}


def parse_questions(content: str) -> list[RawQuestion]:
    """严格解析：必须是只含 questions 的 JSON 对象，至多 5 条，每条字段齐全且类型正确。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise llm.LlmInvalidResponse(f"响应不是合法 JSON（{exc.msg}）") from exc
    if not isinstance(payload, dict) or set(payload) != {"questions"}:
        raise llm.LlmInvalidResponse("响应必须是只含 questions 的 JSON 对象")
    items = payload["questions"]
    if not isinstance(items, list):
        raise llm.LlmInvalidResponse("questions 必须是数组")
    if len(items) > MAX_QUESTIONS:
        raise llm.LlmInvalidResponse(f"questions 超过 {MAX_QUESTIONS} 条")
    parsed: list[RawQuestion] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise llm.LlmInvalidResponse(f"questions[{index}] 不是对象")
        if set(item) != _QUESTION_FIELDS:
            raise llm.LlmInvalidResponse(f"questions[{index}] 字段必须是 {sorted(_QUESTION_FIELDS)}")
        prompt = item.get("prompt")
        quote = item.get("quote")
        block_id = item.get("block_id")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(prompt, str) or not prompt.strip():
            raise llm.LlmInvalidResponse(f"questions[{index}].prompt 缺失或为空")
        prompt = prompt.strip()
        if len(prompt) > PROMPT_MAX_CHARS:
            raise llm.LlmInvalidResponse(f"questions[{index}].prompt 超过 {PROMPT_MAX_CHARS} 字")
        if not isinstance(quote, str) or not quote:
            raise llm.LlmInvalidResponse(f"questions[{index}].quote 缺失或为空")
        if not isinstance(block_id, str) or not block_id:
            raise llm.LlmInvalidResponse(f"questions[{index}].block_id 缺失或为空")
        if not isinstance(start, int) or isinstance(start, bool):
            raise llm.LlmInvalidResponse(f"questions[{index}].start 必须是整数")
        if not isinstance(end, int) or isinstance(end, bool):
            raise llm.LlmInvalidResponse(f"questions[{index}].end 必须是整数")
        parsed.append(RawQuestion(prompt=prompt, quote=quote, block_id=block_id, start=start, end=end))
    return parsed


def verify_questions(questions: list[RawQuestion], blocks: list[Block]) -> list[GrillQuestion]:
    """逐条复验 quote == block.text[start:end]；对不上的整条丢弃（原文是事实源）。"""
    blocks_by_id = {block.id: block for block in blocks}
    verified: list[GrillQuestion] = []
    dropped = 0
    for question in questions:
        block = blocks_by_id.get(question.block_id)
        if block is None:
            dropped += 1
            continue
        text = block.text
        if not (0 <= question.start < question.end <= len(text)) or (
            text[question.start : question.end] != question.quote
        ):
            dropped += 1
            continue
        verified.append(
            GrillQuestion(
                prompt=question.prompt,
                quote=question.quote,
                block_id=question.block_id,
                start=question.start,
                end=question.end,
            )
        )
    if dropped:
        logger.info("grill questions dropped count=%d kept=%d", dropped, len(verified))
    return verified


def generate_grill(material: SavedMaterial) -> list[GrillQuestion]:
    """扫描材料 → 组 prompt → 检查配置 → 单次 LLM 调用 → 严格解析 → 逐条复验。

    不写库、不改材料；引用复验不过的追问整条丢弃，空列表是合法结果。
    """
    statements = inspect_statements(material.blocks)
    findings = find_numeric_findings(statements, material.blocks)
    settings = llm.load_settings()
    if not settings.configured:
        raise llm.LlmNotConfigured()
    content = llm.complete(settings, build_messages(findings, statements))
    return verify_questions(parse_questions(content), material.blocks)
