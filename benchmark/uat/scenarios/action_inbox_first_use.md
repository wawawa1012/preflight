# Scenario S2-1: action_inbox_first_use（进入 Review 先知道下一步）

> Sprint 2 待执行资产（不改产品）。检验：用户进入一场 Review，不需要知道"Agent"是什么，也能判断最重要的下一步。

## USER GOAL

我打开一场 Review（可能是别人建好的，也可能是我刚建的），我想在 30 秒内知道"现在最重要的是干什么"，点一次就走对路，不用学"Agent/任务/队列"这些词。

## STARTING STATE（用户可见）

- 已有一场 Review（tester 用新鲜小材料新建，或复用上一轮自己建的那场；不指定路由，只要求"人找得到回去的路"）。
- 该 Review 可能处于任意进度（还没跑 / 正在跑 / 已出部分结果），tester 进去前不知道是哪种（保持真实）。
- tester 不知道"Agent"概念（装作不知道；即使听过也视为没听过）。

## TASK（黑盒步骤）

1. 从首页/列表进入这场 Review，停 30 秒：说出"它现在是什么状态、下一步建议我干什么"（抄 UI 原话）。
2. 按 UI 指出的"最重要的下一步"点一次（只点一次，不探索支线）。
3. 说出：这次点击后，你知道"在等什么、等完有什么"吗？
4. 记录：是否出现了需要理解"Agent/模型/队列/任务"才能懂的词句（抄原话）。

## ALLOWED KNOWLEDGE

- 允许：Review（"一场审查"）、材料、标准/清单、检查、报告、来源/原文、下一步。
- 禁止：Agent、prompt、模型名、队列、request、任务 ID、API、DB、代码路径、oracle。UI 若用这些词且无大白话解释 → 记 INTERNAL_CONCEPT_LEAK。

## SUCCESS CONDITION

- [ ] 30 秒内能说出当前状态 + 下一步（"正在查第 X 条/去看第一条结果/去加材料"三选一，用 UI 原话复述）。
- [ ] "最重要的下一步"视觉唯一（主按钮/置顶提示，二选一），tester 第一次就点对（Zero-Patience 2 次点击规则同样适用）。
- [ ] 点击后有反馈（进度话术/状态变化/下一步指引三选一，不悬空）。
- [ ] 全程无需理解"Agent"（tester 能复述行动且不借助该词）。

## BLOCKED CONDITION（任一即 USER FLOW BLOCKED）

- 进 Review 白屏/报错无指引；状态与下一步都不显示（"进来不知道干什么"）。
- 下一步点了没反应；或下一步有 3 个以上并列主按钮且无主次（"不知道哪个最重要"→ DEAD_END + BLOCKED 候选）。
- 需要读教程/配 key/理解 Agent 才能继续。
- 处理：停止记录，不许 API/源码绕过后算成功。

## TRUST FAILURE

- 状态撒谎：显示"已完成/无风险"但结果区是空的；或显示"失败"但结果明明有（状态与内容对不上）。
- 用禁用词总结状态：已满足/已支撑/覆盖率%/分数/✅❌。
- 把"还没查"说成"没问题"（缺三件套的结论：搜了多大范围？为什么这样判？点哪里看原文？）。
- 内部词裸奔且伴随行动误导（例如"Agent 队列阻塞，请重试 request"且无下一步）→ 先记 LEAK，误导成立则升级 TRUST。

## METRICS

- `TIME_TO_FIRST_VALUE`（主）：进 Review 到看懂下一步 + 点对一次的时长（Judge 线 ≤60 秒）。
- `SETUP_STEPS`：进 Review 到走对下一步共几步。
- `BLOCKED_FLOWS` / `DEAD_ENDS`：进门卡住 / 进门迷路次数。
- `INTERNAL_CONCEPT_LEAKS`（主之一）：Agent/队列/模型/任务词裸奔计数。
- `TRUST_FAILURES` / `WAIT_WITHOUT_VALUE` / `USEFUL_MOMENTS`（看懂下一步即 1 个）/ `DELIGHT_MOMENTS`（一步到位、话术诚实则记）。

## 推荐 persona

- 必跑：`zero_patience_user`（2 次点击规则最严的一场）。
- 轮换：`competition_judge`（30 秒计时版）、`contestant`（"我先改哪个"视角）。
