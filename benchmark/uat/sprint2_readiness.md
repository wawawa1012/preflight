# Sprint 2 Readiness（BLOCKERS + 是否可进 Sprint 2 Gate）

> 结论先行：**READY_FOR_SPRINT2_STAKEHOLDER_GATE: NO**（资产就绪，执行未就绪）。

## 资产就绪（本包已交付）

- S2 scenarios：`benchmark/uat/scenarios/` 6 个（S2-1 action_inbox / S2-2 progressive / S2-3 stale-switch / S2-4 defense / S2-5 unsupported / S2-6 degradation），八要素齐全，黑盒。
- Traps：`benchmark/uat/sprint2_traps.md` 7 个（injection / 假 source / late return / timeout / 空 evidence 措辞 / unsupported 当 false / 代写答案）。
- 自检：`scripts/eval/check_scenarios.py`（stdlib only）；fixtures 模板 2 个；人用指南 `docs/uat/sprint1_sprint2_eval.md`。
- Persona/指标/报告模板复用 `benchmark/stakeholders/`（不动）。

## BLOCKERS（按严重度）

1. [P0] Sprint 1 Gate 未执行：等待 `S1_PRODUCT_CLOSEOUT_READY`（Criteria Builder / Binding 最后接线中）。在 closeout 前不得在变化 UI 上宣判，Sprint 2 执行顺序排在 Sprint 1 verdict 之后。
2. [P0] Sprint 2 build 未锁定：无 Sprint 2 closeout commit、无 Engineering Gate 记录 → S2 scenarios 不得开跑（开了即失真）。
3. [P1] 自然失败覆盖待确认：S2-6 与 T4 依赖自然失败/超时；若执行轮两次不触发，记 `not_triggered` + `dry-run`，不硬造（不拔网/不改 key/不读 logs）。
4. [P1] Tester 隔离待排班：gate keeper + 非 implementer tester 名单未定（防失真协议要求，见 Lab gate-policy 第五节）。

## READY_FOR_SPRINT2_STAKEHOLDER_GATE

```
READY_FOR_SPRINT2_STAKEHOLDER_GATE: NO
```

- 转为 YES 的条件（缺一不可）：
  - [ ] `S1_PRODUCT_CLOSEOUT_READY` 已给出且 Sprint 1 Gate verdict 已定（PASS / PASS_WITH_P1 / FAIL）。
  - [ ] Sprint 2 Product closeout 已给出（锁定 commit + Engineering 全绿）。
  - [ ] gate keeper 已定 + tester 非 implementer + 新鲜材料流程就绪。
- 本文件在条件满足前不得改写为 YES；改写时同步更新 build、日期、签字。
