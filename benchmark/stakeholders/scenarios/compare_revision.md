# Scenario: Compare Revision（版本对比）

> 覆盖产品树叶子：重跑与版本 Diff（resolved / new / unchanged 的用户侧表现）。检验"改完有没有提升，一眼看得出来吗"。

## USER GOAL

改完出 v2 后，我想一眼看出"上次的问题解决了几个、新增了几个、没变的几个"，而不是两份报告来回翻、自己人肉 diff。

## STARTING STATE

- 已有同一份材料的 2 个版本（v1 改前、v2 改后），各有 1 次检查结果（报告均可打开）。
- tester 记得自己改了哪 1 处（例如把 95% 改成 87% 并补了一句依据），但 scenario 不给 oracle（"应该显示 resolved"不是预设答案，只看 UI 能不能讲清变化）。

## TASK

1. 找到"对比/变化/前后差异"类入口（按 UI 实际文字；找不到就记 BLOCKED，不猜路径）。
2. 打开 v1 vs v2 的对比，看系统怎么说变化（抄原话，不转述）。
3. 对当初改的那 1 处，判断：系统说"变了/没变/没提"？你信吗？为什么（点回原文验证）？
4. 对系统说的其他变化（如果有），抽 1 条点回原文验证真假。
5. 说出：这次对比帮你省了翻报告的时间吗？还是更晕了？

## ALLOWED KNOWLEDGE

- 允许：自己的改动内容、两份报告的 UI 文字、前后对比的大众含义（新增/解决/没变）。
- 禁止：VersionDiff 契约 / resolved/new/unchanged 字段名 / API / 数据库 / 代码路径。UI 若用了这些英文词且无解释 → 记 INTERNAL_CONCEPT_LEAK，不得靠"我懂这个字段"来理解对比。

## SUCCESS CONDITION

- [ ] 对比入口人找得到（从材料页或版本页一步可达，或有明确文字指引）。
- [ ] 对比说清了"哪条变了"（至少对 tester 改的那 1 处有明确说法：变了/没变/未评估三选一，不悬空）。
- [ ] 抽查的变化点得回原文（新旧各点一次，或对比行直达原文）。
- [ ] tester 能用一句话复述"改完提升在哪"（或诚实说"系统没讲清，我自己翻出来的"→ 后者算 DEAD_END，不算成功）。

## BLOCKED CONDITION

- 无对比入口；入口点了无内容/报错；对比页只列版本号不列变化。
- 变化点不回原文；新旧报告打不开其一。
- 需 API/数据库/源码绕过 → BLOCKED，本轮作废。

## TRUST FAILURE

- 明明没改的地方显示"已解决"；改了的地方显示"已解决"但点回去还是旧文（Diff 撒谎，致命）。
- 用分数/覆盖率/✅❌总结对比（"v2 得分 90，比 v1 高 10 分"类，禁用）。
- 新旧混淆：v1 的结论标成 v2 的，或要求版本换了却不标。
- 对比结论给不出"点哪里看原文" → 按"缺三件套的结论"记 TRUST FAILURE（见 metrics.md）。

## METRICS

- `USEFUL_MOMENTS`（主）：对比讲清的变化条数（点得回去且说得对）。
- `BLOCKED_FLOWS` / `DEAD_ENDS`：找不到入口 / 看完更晕的次数。
- `TRUST_FAILURES`：Diff 撒谎/分数总结/新旧混淆计数。
- `TIME_TO_FIRST_VALUE`：从找对比入口到看懂第一条变化的时长。
- `DELIGHT_MOMENTS`：一目了然的变化视图（有则记，Judge 最看重这个）。
- `INTERNAL_CONCEPT_LEAKS` / `WAIT_WITHOUT_VALUE`：通用记法。

## 推荐 persona 组合

- 主力：`contestant`（"改完有没有提升"）、`competition_judge`（wow 视角：对比一眼看懂即 wow）。
- 对抗：`adversarial_skeptic`（改错地方看系统敢不敢说"已解决"）。
