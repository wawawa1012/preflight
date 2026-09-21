# docs/uat：Sprint 1 + Sprint 2 评估指南（人用）

> 给 gate keeper / tester / Product Pod 看的一页纸。可执行定义以 `benchmark/uat/` 为准，本文件只讲规则与顺序。

## 顺序（现在 →  Gate）

1. 现在：Product Pod 接线中 → Evaluation Pod 不执行、不宣判（`sprint1_gate.md` = NOT_EXECUTED）。
2. Product Pod 给出 `S1_PRODUCT_CLOSEOUT_READY`（锁定 commit + Engineering 全绿）→ Evaluation Pod 按 `benchmark/uat/sprint1_gate.md` 执行 Sprint 1 Gate（2 必跑 + 2 轮换 + 5 个特别看）。
3. Sprint 1 Gate verdict（PASS / PASS_WITH_P1 / FAIL）+ Human Product Gate 签字 → 收口。
4. Sprint 2 build 就绪 → 按 `benchmark/uat/scenarios/S2-*` + `sprint2_traps.md` 执行 Sprint 2 Gate（另行 closeout，不在本文件提前定义 verdict）。

## 新鲜材料规则（防失真核心）

- 每次运行手写新材料（`benchmark/uat/fixtures/` 为模板，每次重写，不复用）。
- tester 知道自己材料的真相，题目不给答案；tester 按自己的知识判"点得回去/说得对"。
- 禁止：复用上一轮材料、抄 golden 句子、用真实赛事全文/私有材料、把 golden 答案告诉 tester。

## Golden 规则

- `benchmark/golden-v2/` 是 engineering regression 的 oracle，不是用户的标准答案。
- Evaluation 运行时 tester 不读、不对照、不引用 golden；gate keeper 也不用 golden 判"对/错"。
- 唯一允许的对照：tester 自己的新鲜材料原文（点回原文验证）。

## 黑盒规则（复述）

- 不读源码、API 代码、DB、oracle、backend logs；只用普通 UI。
- UI 卡住 = USER FLOW BLOCKED；禁 API 绕过后算成功。
- 先行为后解释：点击流 + 截图 + 系统原话先行，判断引用证据编号。
- 失真自首：用了源码知识 → `contamination: true`，作废/换人重跑。

## 9 指标与报告

- 定义：`benchmark/stakeholders/metrics.md`；单轮 A 表 + Sprint B 表：`benchmark/stakeholders/report-template.md`。
- Sprint 1 额外要求：Diff 句、版本句、删除确认句必须抄原话（措辞即证据）。
