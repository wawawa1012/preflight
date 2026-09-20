# Multi-Stakeholder Black-Box Acceptance Pack

> 状态：准备阶段（Sprint 复用资产）。现在只准备 persona / scenario / metrics / report templates，不测试当前正在变化的 Sprint 1 页面，不修改产品。
> 写入范围：仅 `benchmark/stakeholders/**`。禁止触碰 `backend/**`、`frontend/**`、`contracts/**`、`benchmark/golden-v2/**`。不 commit（由用户决定何时收口）。

## 这是什么

以后每个 Sprint 都能复用的黑盒验收包。回答一个问题：

**一个没见过源码、没读过 MASTER_PLAN 的外部人，第一次用产品能不能拿到价值、会不会被误导？**

- Engineering tests green（单测 / stub benchmark / build）只证明"程序没坏"。
- 本包证明"人能用、敢信、愿意继续"。
- 两者都绿，Sprint 才能算完成。详见 `gate-policy.md`。

## 它增强哪个产品闭环

- 直接增强 **Evidence Adjudication / Repair Loop** 的外部可验证性：每个 scenario 都要求"结论能点回原文、修完能看到变化"，呼应 `docs/PRODUCT_TREE.md` 第四节账本（报告 / Drawer / 修复 / Diff）。
- 新框架收益：6 persona × 6 scenario = 可轮换矩阵，一次准备、每 Sprint 只跑子集（必跑 2 + 轮换 N），成本低于每 Sprint 现写用例。
- 成本：纯文档 + 人工/黑盒 Agent 执行，不引入新依赖、新服务、新表。
- 替代方案（已否决）：① 用工程单测代替验收 —— 测的是代码路径，不是人的理解；② 现场临时找人试用 —— 不可复现、不可对比 Sprint 间变化。

## 目录

```
benchmark/stakeholders/
  README.md            # 本文件：定位、用法、防失真
  metrics.md           # 9 个统一指标定义 + 测量法
  report-template.md   # 单次运行记录 + Sprint 门控汇总模板
  gate-policy.md       # 三门控政策（Engineering / Black-box / Human）
  personas/            # 6 个固定 persona（互相真的不同）
    zero_patience_user.md
    contestant.md
    enterprise_reviewer.md
    paper_author_reviewer.md
    competition_judge.md
    adversarial_skeptic.md
  scenarios/           # 6 个黑盒 scenario（都不含内部实现）
    first_review.md
    fix_one_issue.md
    create_revision.md
    compare_revision.md
    prepare_defense.md
    criteria_from_raw_requirements.md
```

## 准入三问（本包自己的答案，符合 PRODUCT_TREE.md 第五节）

1. 屏幕入口：无。本包是验收资产，不上产品屏幕；执行时从产品首页开始，不指定内部路由。
2. 验收标准：本包 16 个文件齐全；每个 persona 有差异化决策规则；每个 scenario 含 8 要素（USER GOAL / STARTING STATE / TASK / ALLOWED KNOWLEDGE / SUCCESS / BLOCKED / TRUST FAILURE / METRICS）；`metrics.md` 定义 9 指标测量法；`gate-policy.md` 定义三门 + 必跑 + 轮换。
3. Demo 秒数：0 秒。本包不上台；它是让台上 3 分钟 demo 不翻车的门槛。

## 关键纪律（执行者必读）

1. **Black-box**：scenario 不含内部 API、数据库操作、oracle 答案、代码路径。只描述人眼可见的起点、任务、成功/卡住的判断。
2. **Stakeholder Agent 无知假设**：默认不知道 Block / Criterion schema / Binding / Finding / SourceRef / 内部 API。除非 UI 自己把这个词暴露出来并给出解释，否则 tester 不得使用它来推进任务，也不得把它算作"我理解了"。
3. **UI 卡住 = USER FLOW BLOCKED**：记录在案，按失败/阻塞处理。不得用 API、数据库、直接读源码绕过之后再把它算成功。绕过即作废本次运行。
4. **措辞纪律**（与 PRODUCT_TREE.md 第六节一致，tester 也要遵守）：
   - 始终允许：已确认关联 N 条 / 已关联 N 条 / 已绑定 rev N / 未评估 / 当前范围尚未发现引用（须说明范围，例如"当前这份材料"）。
   - 门控词「缺失」「有矛盾」仅在对应检查已实现并执行后使用；本包的 scenario 模板里不预设这些结论。
   - 禁用：已满足 / 已支撑 / 覆盖率% / 分数预测 / ✅❌ 满足芯片。看到产品出现这些措辞，记 TRUST FAILURE 或 INTERNAL_CONCEPT_LEAK，详见 `metrics.md`。
5. **现在不测**：Sprint 1 页面正在变化，本包本轮只做准备，不产生对当前 UI 的 verdict。任何试点运行必须标记为 `dry-run / template-validation`，不得写入正式 Sprint 门控结论。

## 每个 Sprint 怎么用（摘要，细则见 gate-policy.md）

1. 定 build（记录 commit hash + 部署方式）。
2. 必跑：`zero_patience_user` + `adversarial_skeptic` 各至少 1 个 scenario。
3. 轮换：其余 4 persona 按 Sprint 主题轮换至少 2 个（见 gate-policy 轮换表）。
4. 每个运行填一份 `report-template.md` 的"单次运行记录"。
5. 汇总成"Sprint 门控汇总"，判 Black-box Stakeholder Gate 通过 / 有条件通过 / 不通过。
6. 再过 Human Product Gate（真人 5 秒测试 + 抽查录像/记录）。

## 防失真：tester 知道源码怎么办

完整协议见 `gate-policy.md` 第五节。这里是摘要：

- **角色隔离**：当前 Sprint 的 implementer 不得担任同一 Sprint 的 stakeholder tester（自己测自己的叶子必失真）。
- **无知扮演**：tester 必须按 persona 的 ALLOWED KNOWLEDGE 行事；persona 文件中的 FORBIDDEN 词表（Block / Binding / Finding / SourceRef / schema / API / 表名）在运行中视为"不存在的知识"，不得用来猜 UI、猜路径、猜术语。
- **新鲜材料**：验收用的材料不得是 `benchmark/golden-v2/**` 或 tester 事先调过的内部 fixture；每次用新写的 1 页 Markdown（≤50 行），避免"我知道答案在哪"。
- **无 oracle**：scenario 不给标准答案；tester 按自己的理解判成功/卡住，不对照源码或 golden 期望。
- **先行为后解释**：先记录点击流 + 截图/原文引用，再写"我觉得它想表达什么"。解释不得美化卡住。
- **失真自首**：如果 tester 发现自己用了源码知识（例如"我知道要点那个 Drawer 因为我看过代码"），必须在报告中勾选 `contamination: true` 并作废该轮，或换不知情的人重跑。

## 与现有 benchmark 的关系

- `benchmark/README.md` 的 stub/live 是**工程质量门**（解析 + 验证门 + LLM 提案回归）。
- 本包是**人的接受门**（能不能用、敢不敢信）。
- 两者互不替代，Sprint 完成需要两者都过。`benchmark/golden-v2/**` 冻结不动，本包不引用其答案。
