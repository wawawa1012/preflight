# Benchmark UAT（Black-Box Evaluation Assets）

> Pod：Evaluation / User Research（非产品 implementer）。
> 分支：`sprint2/eval`。基线：`4cee9f3`（本包编写起点；执行门控时以 gate 文件记录的实际 build 为准）。
> 状态：Sprint 1 Gate 待 `S1_PRODUCT_CLOSEOUT_READY`，不得提前宣判；Sprint 2 scenarios 为待执行资产。

## FILE WALL（本包遵守）

允许写入：`benchmark/stakeholders/**`（已有 Lab，不动）、`benchmark/uat/**`、`scripts/eval/**`、`docs/uat/**`、必要的 eval-only fixtures（仅 `benchmark/uat/fixtures/` 内新鲜手写小材料模板）。

禁止触碰：`backend/**`、`frontend/src/**`、`contracts/**`、生产 router/store/service。本包任何文件不得包含内部 API 路径、DB 操作、oracle 答案、代码路径、backend logs 解读。只定义"人眼可见"的测试。

## 目录

```
benchmark/uat/
  README.md                  # 本文件
  sprint1_gate.md            # Phase A：Sprint 1 Gate 计划 + 状态（NOT_EXECUTED until closeout）
  scenarios/                 # Phase B：Sprint 2 black-box scenarios（6 个）
    action_inbox_first_use.md
    progressive_evidence.md
    stale_response_switch.md
    defense_preparation.md
    unsupported_answer.md
    model_failure_degradation.md
  sprint2_traps.md           # Sprint 2 新增对抗陷阱（7 个，test-only）
  sprint2_readiness.md       # BLOCKERS + READY_FOR_SPRINT2_STAKEHOLDER_GATE
  fixtures/
    fresh_review_material.md     # 新鲜小材料模板（每次手写新一份，不复用）
    raw_requirements_snippet.md  # 原始要求片段模板（同上）
docs/uat/
  sprint1_sprint2_eval.md    # 人用 UAT 指南（新鲜材料规则、golden 规则、执行顺序）
scripts/eval/
  check_scenarios.py         # eval-only 自检：scenario 八要素 + 禁止模式（stdlib only，不碰产品代码）
```

## 与 Stakeholder Lab 的关系

- `benchmark/stakeholders/`（persona / metrics / report-template / gate-policy）是**尺和角色**，本包复用，不复制。
- `benchmark/uat/` 是**本轮题目**：Sprint 1 门控计划 + Sprint 2 场景题 + 陷阱 + readiness。
- `benchmark/golden-v2/` 是 engineering regression 用，不向 tester 透露答案（见 `docs/uat/sprint1_sprint2_eval.md`）。

## 黑盒纪律（所有 scenario 通用）

1. Tester 不读源码、API 代码、DB、oracle、backend logs，只用普通 UI。
2. UI 卡住 = `USER FLOW BLOCKED`，停止并记录；不得用 API 绕过后算成功（绕过即作废）。
3. Tester 默认不知道 Agent / Binding / schema / revision 锚定实现；除非 UI 自己用大白话解释，否则不得用这些概念推进任务。
4. 每次运行记录 9 指标：`TIME_TO_FIRST_VALUE` / `SETUP_STEPS` / `BLOCKED_FLOWS` / `DEAD_ENDS` / `TRUST_FAILURES` / `INTERNAL_CONCEPT_LEAKS` / `WAIT_WITHOUT_VALUE` / `USEFUL_MOMENTS` / `DELIGHT_MOMENTS`（定义见 `benchmark/stakeholders/metrics.md`）。
5. 措辞纪律（PRODUCT_TREE 第六节）：tester 与报告只用"已确认关联 N 条 / 已关联 N 条 / 已绑定 rev N / 未评估 / 当前范围尚未发现引用（须说明范围）"；门控词「缺失/有矛盾」仅当产品已实现对应检查并答上三问时承认；禁用"已满足 / 已支撑 / 覆盖率% / 分数预测 / ✅❌"（出现即 TRUST_FAILURE 候选）。
