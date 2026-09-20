# Report Templates（报告模板）

> 两张表：A. 单次运行记录（每次 persona × scenario 填一张）；B. Sprint 门控汇总（每个 Sprint 填一张）。
> 现在（准备阶段）不填对当前 UI 的 verdict；试点只验证模板好不好用，`verdict` 一律写 `dry-run`。

---

## A. 单次运行记录（复制一份填一份）

```markdown
### Run ID: ST-YYYYMMDD-01（例 ST-20260920-01）
- date / tester: ____ / ____（tester 非本 Sprint implementer，见 gate-policy）
- build: commit ____ + 部署方式 ____（本地/预览链接）
- persona: ____（personas/ 下文件名）
- scenario: ____（scenarios/ 下文件名）
- 材料：手写新文件 ____（≤50 行，不复用 golden-v2；附全文或链接）
- verdict（单轮）: SUCCESS / BLOCKED / TRUST_FAIL / dry-run（准备阶段只用 dry-run）
- contamination: false / true（true 则说明用了什么源码知识并作废/重跑）

#### 行为流（按步骤记，只写人可见的）
1. [0:00] 打开 ____，看到 ____（截图1）
2. [0:30] 点击 ____，得到 ____（截图2）
3. ……

#### 指标（见 metrics.md）
| 指标 | 数值 | 证据 |
|------|------|------|
| TIME_TO_FIRST_VALUE | | |
| SETUP_STEPS | | |
| BLOCKED_FLOWS | | |
| DEAD_ENDS | | |
| TRUST_FAILURES | | |
| INTERNAL_CONCEPT_LEAKS | | |
| WAIT_WITHOUT_VALUE | | |
| USEFUL_MOMENTS | | |
| DELIGHT_MOMENTS | | |

#### 关键证据（抄原话，不转述）
- 系统原话1："____"（位置：____，截图__）→ 判定：诚实/禁用词/泄露/失真
- 系统原话2："____" ……
- 点回原文验证：抽查 __ 条，对得上 __ 条，对不上 __ 条（列出对不上的那条：系统说__，原文是__）

#### Persona 视角三问（用该 persona 的口吻答）
- 它是干什么的？____
- 对我有用吗？____
- 我会再回来/敢签字/敢拿去答辩吗？为什么？____
```

---

## B. Sprint 门控汇总（每个 Sprint 一张，由 gate keeper 填）

```markdown
## Sprint __ Black-box Stakeholder Gate 汇总
- sprint 主题：____（例 I6 报告中心 / I9 答辩 Grill；准备阶段写 TEMPLATE-VALIDATION）
- build: commit ____；Engineering Gate: 通过/未通过（链接：____）
- 执行日期：____；gate keeper：____（非 implementer）
- 必跑：zero_patience_user × ____（run id：____）+ adversarial_skeptic × ____（run id：____）
- 轮换：____ × ____，____ × ____（按 gate-policy 轮换表，至少 2 个）
- verdict: 通过 / 有条件通过（附必改清单）/ 不通过（附阻塞清单）/ dry-run

#### 矩阵（每格填 SUCCESS / BLOCKED / TRUST_FAIL / 未跑）
| persona \ scenario | first_review | fix_one_issue | create_revision | compare_revision | prepare_defense | criteria_from_raw |
|---|---|---|---|---|---|---|
| zero_patience_user | | | | | | |
| contestant | | | | | | |
| enterprise_reviewer | | | | | | |
| paper_author_reviewer | | | | | | |
| competition_judge | | | | | | |
| adversarial_skeptic | | | | | | |

#### 指标汇总（跨轮加总 + 最差轮）
- TRUST_FAILURES 总计 __（致命 __，严重 __；分布：__）
- BLOCKED_FLOWS 总计 __（主线 __，支线 __）
- TIME_TO_FIRST_VALUE 最差 __秒（persona/scenario：__）
- USEFUL_MOMENTS 总计 __ / DELIGHT 总计 __ / LEAK 总计 __ / WAIT 总计 __秒

#### 必改清单（有条件通过/不通过时填，抄系统原话 + 改法）
1. [致命/严重/文案] ____（run：____，原话："____"，改法：____）
2. ……

#### Human Product Gate 交接
- 5 秒测试结论：____（新人原话："____"）
- 抽查录像/记录链接：____
- 人工签字：通过 / 打回（理由：____）
```
