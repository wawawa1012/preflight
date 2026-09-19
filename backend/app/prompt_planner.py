"""R2A：把一份材料的所有 block 装进多个 prompt 窗口。

规则：整块装箱（一块不跨两窗）、顺序即输入顺序、不丢块。窗口能不能装下，唯一裁判是
``llm.build_messages``——本模块不自己算字符，也不改 prompt 文本或上限。单块自身就超限时抛
``PromptTooLarge``，绝不用「丢掉该块」换取其余窗成立。

只做规划：切窗之后一次跑几个窗、失败怎么合并、候选怎么汇总，属于后续切片（R2B），本模块不碰。
"""
from .contracts import Block, Criterion
from .llm import PromptTooLarge, build_messages


def _ensure_single_block_fits(criterion: Criterion, block: Block) -> None:
    """单块自检：装不下就带着 block_id 抛错，避免调用方以为「只是这个块没进来」。"""
    try:
        build_messages(criterion, [block])
    except PromptTooLarge as exc:
        raise PromptTooLarge(f"block {block.id} 单独就超过 prompt 上限：{exc.message}") from exc


def _fits(criterion: Criterion, window: list[Block]) -> bool:
    try:
        build_messages(criterion, window)
    except PromptTooLarge:
        return False
    return True


def plan_windows(criterion: Criterion, blocks: list[Block]) -> list[list[Block]]:
    """返回覆盖全部 block 的窗口列表；空材料钉死为 ``[[]]``（调用方无需分支）。"""
    if not blocks:
        return [[]]
    windows: list[list[Block]] = []
    current: list[Block] = []
    for block in blocks:
        if not current:
            _ensure_single_block_fits(criterion, block)
            current = [block]
            continue
        if _fits(criterion, current + [block]):
            current.append(block)
            continue
        windows.append(current)
        _ensure_single_block_fits(criterion, block)
        current = [block]
    windows.append(current)
    return windows
