"""待核对问题的修复建议：LLM 只给「文本怎么改」，不判结论、不碰材料。

调用前逐条复验 citation（quote == block.text[start:end]）：任一条对不上就抛 CitationMismatch，
不调用 LLM——原文是事实源。响应只接受 {suggestion, action} 严格 JSON，suggestion 上限 200 字；
超限或不合 schema 抛 LlmInvalidResponse（API 层映射 502），绝不静默截断。
本模块不写库、不改材料、不新增表；一次请求一次 LLM 调用。
"""
import json

from . import llm
from .contracts import Block, ConsistencyCitation, ConsistencyFinding, RepairSuggestion

SUGGESTION_MAX_CHARS = 200

SYSTEM_PROMPT = (
    "你是参赛材料的修订顾问。任务：针对一条「待核对问题」——同一材料里同一度量词在不同位置给出不同数值——"
    "给出改稿方向，让两处数字在文档中取得一致。"
    "必须遵守："
    "1. 只谈文本怎么改：指出应核对哪几处引用、建议统一为哪一个数值，或改写成不产生数值对照的表述。"
    "2. 引用只能照抄给定列表中的原文片段；不得编造、改写或补充引用、页码、数字。"
    "3. 不给结论性判词（例如「满足要求」），也不谈评分；只给文本层面的修改方向。"
    "4. suggestion 不超过 200 字；action 用一句短语概括动作（例如「统一数值」）。"
    '5. 只输出严格 JSON：{"suggestion":"...","action":"..."}，不要任何其他文字。'
)


class CitationMismatch(Exception):
    """待核对问题的引用无法在材料原文复验；此时不调用 LLM。"""

    def __init__(
        self, message: str = "待核对问题的引用无法在材料原文复验", details: list[str] | None = None
    ) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


def verify_citations(
    finding: ConsistencyFinding, blocks: list[Block]
) -> list[tuple[ConsistencyCitation, Block]]:
    """逐条复验 quote == text[start:end]；返回 (citation, block) 对供拼 prompt。"""
    blocks_by_id = {block.id: block for block in blocks}
    verified: list[tuple[ConsistencyCitation, Block]] = []
    for citation in finding.citations:
        block = blocks_by_id.get(citation.block_id)
        if block is None:
            raise CitationMismatch("引用指向的 Block 不在该材料中", [f"block_id={citation.block_id}"])
        if not (0 <= citation.start < citation.end <= len(block.text)) or (
            block.text[citation.start : citation.end] != citation.quote
        ):
            raise CitationMismatch(
                "引用与 Block 原文不一致",
                [
                    f"block_id={citation.block_id}",
                    f"quote={citation.quote}",
                    f"span=[{citation.start},{citation.end})",
                ],
            )
        verified.append((citation, block))
    return verified


def build_messages(
    finding: ConsistencyFinding, verified: list[tuple[ConsistencyCitation, Block]]
) -> list[dict[str, str]]:
    lines = [
        "待核对问题（同一材料内部的数值对照）：",
        f"- 类型：{finding.kind}",
        f"- 度量词：{finding.measure or '（无共同度量词）'}",
        f"- 不同数值：{'、'.join(finding.values)}",
        f"- 说明：{finding.explanation}",
        "",
        "引用（材料原文的精确片段，不得改写）：",
    ]
    for index, (citation, _block) in enumerate(verified, start=1):
        lines.append(
            f"[{index}] 「{citation.quote}」（block_id={citation.block_id}，start={citation.start}，end={citation.end}）"
        )
    lines.extend(
        ["", '输出 JSON（不要多余字段）：{"suggestion":"不超过 200 字的改稿建议","action":"一句话动作"}']
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
    prompt_chars = sum(len(message["content"]) for message in messages)
    if prompt_chars > llm.MAX_PROMPT_CHARS:
        raise llm.PromptTooLarge(f"prompt 长度 {prompt_chars} 超过 {llm.MAX_PROMPT_CHARS}")
    return messages


def parse_suggestion(content: str) -> RepairSuggestion:
    """严格解析：必须是只含 suggestion/action 的 JSON 对象，suggestion ≤ 200 字。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise llm.LlmInvalidResponse(f"响应不是合法 JSON（{exc.msg}）") from exc
    if not isinstance(payload, dict) or set(payload) != {"suggestion", "action"}:
        raise llm.LlmInvalidResponse("响应必须是只含 suggestion/action 的 JSON 对象")
    suggestion = payload.get("suggestion")
    action = payload.get("action")
    if not isinstance(suggestion, str) or not suggestion.strip():
        raise llm.LlmInvalidResponse("suggestion 缺失或为空")
    if not isinstance(action, str) or not action.strip():
        raise llm.LlmInvalidResponse("action 缺失或为空")
    suggestion = suggestion.strip()
    if len(suggestion) > SUGGESTION_MAX_CHARS:
        raise llm.LlmInvalidResponse(f"suggestion 超过 {SUGGESTION_MAX_CHARS} 字")
    return RepairSuggestion(suggestion=suggestion, action=action.strip())


def suggest_repair(finding: ConsistencyFinding, blocks: list[Block]) -> RepairSuggestion:
    """复验引用 → 检查配置 → 单次 LLM 调用 → 严格解析；不写库、不改材料。"""
    verified = verify_citations(finding, blocks)
    settings = llm.load_settings()
    if not settings.configured:
        raise llm.LlmNotConfigured()
    content = llm.complete(settings, build_messages(finding, verified))
    return parse_suggestion(content)
