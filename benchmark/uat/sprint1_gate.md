# SPRINT1_STAKEHOLDER_GATE（Phase A）

> 状态：**NOT_EXECUTED — 等待 `S1_PRODUCT_CLOSEOUT_READY`**。
> Product Pod 正在完成 Criteria Builder / Binding 的最后真实接线。在 Product Pod 明确给出 `S1_PRODUCT_CLOSEOUT_READY` 之前，本文件仅为**可执行计划**，不产生 PASS / PASS_WITH_P1 / FAIL verdict，不在变化中的 UI 上提前宣判。

## 基线与执行前提

- Eval 基线：`sprint2/eval @ 4cee9f3`（资产编写起点）。
- 执行门控时的 build 以本节记录为准（gate keeper 在执行轮填写）：
  - `gate_build_commit: ____`（Product Pod 给出 closeout 时锁定的 commit）
  - `closeout_signal: S1_PRODUCT_CLOSEOUT_READY（时间/链接：____）`
  - `engineering_gate: 通过/未通过（记录链接：____）`—— Engineering 不绿不进 Black-box。
- 前提不满足 → 本 Gate 保持 NOT_EXECUTED，不得填 verdict。

## Sprint 1 目标用户旅程（黑盒描述，不含实现）

创建 Review → 选择/创建标准 → 加入材料 → 得到第一个有用检查 → 看来源 → 编辑为修订稿 → 保存 → Diff → Re-review。

- 每一步只允许"人眼可见"的动作（找入口、粘贴/上传、点选、阅读报告、点回原文、场外改稿、保存、看对比、再跑一次）。
- 不出现内部 API、DB 操作、oracle 答案、代码路径、backend logs。

## 必跑 Persona（正式执行时）

1. `zero_patience_user`（必跑）：不理解 Rubric/Binding，能否建起第一场审查。
2. `adversarial_skeptic`（必跑）：专找过度宣称（见本文件"特别看"与陷阱）。
3. `contestant`（本 Sprint 轮换）：哪里扣分/怎么改/改完变了吗。
4. `competition_judge`（本 Sprint 轮换）：3 分钟价值+差异+wow+首点不卡。
5. `enterprise_reviewer`（时间允许）：追溯/范围/版本/人机区分。

最小矩阵：2 必跑 + 2 轮换 = 4 张 A 表 + 1 张 B 表（A/B 表见 `benchmark/stakeholders/report-template.md`）。

## 测试材料规则

- 遵守 Stakeholder Lab：每次用**新鲜手写小材料**（模板见 `benchmark/uat/fixtures/`，每次重写一份 ≤50 行 Markdown + 一段 3–5 条原始要求；tester 自己知道真相，题目不给答案）。
- 不要直接用 `golden-v2` oracle 告诉 tester 答案。Golden 仅用于 engineering regression，不是用户知道的标准答案。
- tester 不对照 golden 判分；只按自己的材料知识判断"点得回去/说得对"。

## Sprint 1 Gate 特别看（5 项，每项都是独立 FAIL 候选）

### 1. 新用户不理解 Rubric/Binding，能否创建第一场审查

- 操作：Zero-Patience 从首页开始，不读教程，创建一场 Review（含选/建标准 + 加材料）直到看到第一条有用检查。
- 通过线：`SETUP_STEPS` 可复述、无需 tester 脑补"Rubric/Binding 是什么"；遇到内部词无解释 → `INTERNAL_CONCEPT_LEAKS` +1。
- FAIL 候选：首次流程完全 blocked（找不到建 Review 入口 / 标准选不上 / 材料加不进 / 检查跑不起来）→ Sprint 1 Gate 直接 FAIL。

### 2. Criteria Builder：原始要求 → 草稿 → 人工确认是否自然

- 操作：粘贴一段原始要求文字 → 得到一份草稿清单 → 人工确认/改后生效 → 用它跑一次检查。
- 通过线：草稿与原文条数一致、无改意（多/少/改意须提示且可改）；tester 能说出"现在按哪份清单查的"。
- TRUST 候选：清单与原文严重不符却不提示、照跑（按错卷子）→ 致命 TRUST_FAILURE → FAIL。

### 3. Revision：用户是否清楚"保存的是新版本，不是覆盖原稿"

- 操作：改稿后保存，回答"旧稿还在吗？现在看的是哪一版？"
- 通过线：新旧版本分得清（版本号/时间/要求版本至少其二可见）；旧报告不冒充新报告。
- TRUST 候选：旧结论在新版本下无标注展示 → 版本混淆（致命）→ FAIL。

### 4. Diff："本次未再检出"是否会被理解成绝对解决

- 操作：看 v1 vs v2 对比，对改过的 1 处说出"变了/没变/没提"，抽 1 条点回原文。
- 通过线：对比措辞诚实（"本次未再检出" + 范围说明，不说"已解决/已满足/无风险"）；tester **不会**把它理解成"问题绝对消失"（tester 用自己的改稿知识判断 + 点回原文验证）。
- TRUST 候选：没改的地方显示"已解决"；改完点回去还是旧文；用分数/✅❌总结对比 → 致命 → FAIL。Contestant 必答："改完提升在哪？"说不清 = DEAD_END。

### 5. 删除 Review：是否误以为 material binding 被撤销

- 操作：在删除 Review 前后，分别说出"材料还在吗？它和标准的关系还在吗？"
- 通过线：删除 Review 只删"这场审查"，材料的存在性与材料的标准关系有明确、可复述的说明（UI 原话为准，不猜实现）。
- TRUST/BLOCKED 候选：删 Review 后材料"消失"且无说明；或反之，UI 暗示"已撤销绑定"但实际关系不清 → tester 按所见记录，gate keeper 判 TRUST_FAILURE 或 BLOCKED（主线混淆 = FAIL 候选）。

## 记录（9 指标）

见 `benchmark/stakeholders/metrics.md`。Sprint 1 额外要求：每轮必须抄**系统原话**（Diff 句、版本句、删除确认句一字不改），因为本 Sprint 的风险集中在措辞误导。

## Gate 输出

```
SPRINT1_STAKEHOLDER_GATE: NOT_EXECUTED（当前）/ PASS / PASS_WITH_P1 / FAIL
```

- 任何致命 TRUST FAILURE → FAIL。
- 任何首次流程完全 blocked → FAIL。
- PASS_WITH_P1：无致命、无主线 BLOCKED，但有 P1（严重措辞/边缘阻塞/单个特别看项弱通过），附必改清单 + 下 Sprint 验证项，由 Human Product Gate 决定是否放行。
- 当前 verdict：**NOT_EXECUTED**（等待 closeout，无 tester 运行、无 build、无证据，不得改写为 PASS/FAIL）。

## 执行后要填的（现在留空）

- Runs（A 表 id）：____
- 矩阵与指标汇总（B 表）：见 `benchmark/stakeholders/report-template.md` B 表，执行轮粘贴于此或链接。
- 必改清单（P1）：____
- Human Product Gate 交接（5 秒测试 + 抽查 + 签字）：____
