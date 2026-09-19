"""R2A：prompt 窗口规划 plan_windows（整块装箱、不丢块、不静默截断）。

边界不写死魔数：窗口能不能装下，由 llm.build_messages 自己回答（它是唯一的字符裁判）。
本包允许的 llm 接触面只有 build_messages / MAX_PROMPT_CHARS / PromptTooLarge。
"""
import unittest

from app import llm
from app.contracts import Block, Criterion, Locator
from app.prompt_planner import plan_windows


def make_block(block_id: str, text: str, index: int = 7) -> Block:
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


def text_budget(criterion: Criterion, count: int) -> int:
    """count 个空文本 block 的窗里，还能再塞多少字符正文（用 build_messages 现算）。"""
    empties = [make_block(f"b{i}", "", index=1) for i in range(count)]
    user = llm.build_messages(criterion, empties)[1]["content"]
    return llm.MAX_PROMPT_CHARS - len(llm.SYSTEM_PROMPT) - len(user)


def window_ids(windows: list[list[Block]]) -> list[list[str]]:
    return [[block.id for block in window] for window in windows]


def many_blocks(count: int = 100) -> list[Block]:
    return [make_block(f"b{i:03d}", "句子。" * 100) for i in range(count)]


class PlanWindowsShapeTest(unittest.TestCase):
    def test_empty_blocks_pin_single_empty_window(self) -> None:
        self.assertEqual(plan_windows(make_criterion(), []), [[]])

    def test_small_blocks_stay_in_one_window_in_input_order(self) -> None:
        blocks = [make_block(f"b{i}", f"第 {i} 段原文。") for i in range(5)]
        windows = plan_windows(make_criterion(), blocks)
        self.assertEqual(len(windows), 1)
        self.assertEqual(window_ids(windows), [[block.id for block in blocks]])

    def test_all_blocks_covered_exactly_once(self) -> None:
        blocks = many_blocks()
        windows = plan_windows(make_criterion(), blocks)
        flat_ids = [block.id for window in windows for block in window]
        self.assertEqual(flat_ids, [b.id for b in blocks])
        self.assertEqual(len(set(flat_ids)), len(blocks))
        for window in windows:
            self.assertTrue(window, "窗不能为空")


class PlanWindowsLimitTest(unittest.TestCase):
    def test_every_window_fits_the_prompt_limit_and_is_maximal(self) -> None:
        criterion = make_criterion()
        windows = plan_windows(criterion, many_blocks())
        self.assertGreater(len(windows), 1, "100 个长块应当被切成多窗，否则本测试没有覆盖切窗路径")
        for window in windows:
            llm.build_messages(criterion, window)  # 抛 PromptTooLarge 即违规
        for current, following in zip(windows, windows[1:]):
            with self.assertRaises(llm.PromptTooLarge):
                llm.build_messages(criterion, current + [following[0]])

    def test_whole_block_text_lands_inside_its_window(self) -> None:
        criterion = make_criterion()
        windows = plan_windows(criterion, many_blocks())
        for window in windows:
            user = llm.build_messages(criterion, window)[1]["content"]
            for block in window:
                self.assertIn(block.text, user)

    def test_boundary_exactly_at_limit_stays_one_window(self) -> None:
        criterion = make_criterion()
        budget = text_budget(criterion, 2)
        first = make_block("b0", "甲" * (budget // 2), index=1)
        second = make_block("b1", "乙" * (budget - budget // 2), index=1)
        windows = plan_windows(criterion, [first, second])
        self.assertEqual(window_ids(windows), [["b0", "b1"]])
        llm.build_messages(criterion, windows[0])  # 正好等于上限不算超

    def test_boundary_one_char_over_splits_into_two_windows(self) -> None:
        criterion = make_criterion()
        budget = text_budget(criterion, 2)
        first = make_block("b0", "甲" * (budget // 2), index=1)
        second = make_block("b1", "乙" * (budget - budget // 2 + 1), index=1)
        self.assertEqual(window_ids(plan_windows(criterion, [first, second])), [["b0"], ["b1"]])


class PlanWindowsOversizedBlockTest(unittest.TestCase):
    def test_single_oversized_block_raises(self) -> None:
        criterion = make_criterion()
        huge = make_block("b_huge", "超" * (llm.MAX_PROMPT_CHARS + 1))
        with self.assertRaises(llm.PromptTooLarge):
            plan_windows(criterion, [huge])

    def test_oversized_block_in_the_middle_raises_instead_of_dropping_it(self) -> None:
        criterion = make_criterion()
        small = make_block("b_small", "正常一段。")
        huge = make_block("b_huge", "超" * (llm.MAX_PROMPT_CHARS + 1))
        with self.assertRaises(llm.PromptTooLarge) as ctx:
            plan_windows(criterion, [small, huge, small])
        self.assertIn("b_huge", str(ctx.exception.message))


class PlanWindowsGovernanceTest(unittest.TestCase):
    def test_prompt_limit_is_not_raised_by_this_slice(self) -> None:
        self.assertEqual(llm.MAX_PROMPT_CHARS, 24000)


if __name__ == "__main__":
    unittest.main()
