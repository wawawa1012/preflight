# Gate Policy（三门控政策）

> Engineering tests green ≠ Sprint 完成。Sprint 完成 = 三门全过。

## 一、三门定义

### Gate 1 — Engineering Gate（程序没坏）

- 内容：与变更相称的检查（AGENTS.md）：单测 / stub benchmark（`scripts/run_preflight_benchmark.py --mode=stub`）/ 前端 `npm.cmd ci + run build` / `scripts/check_contracts.py`（动契约时）等。
- 通过标准：所跑检查全绿；失败即打回，不进入 Gate 2。
- 负责人：implementer 自测 + reviewer 复核。
- 输出：commit hash + 检查记录链接。

### Gate 2 — Black-box Stakeholder Gate（人能用、敢信）

- 内容：本包（`benchmark/stakeholders/`）的 persona × scenario 矩阵运行，黑盒执行，只看 UI。
- 通过标准（见第四节 verdict 规则）：无致命 TRUST_FAILURE、无主线 BLOCKED；严重项清零或转为"有条件通过的必改清单"并在下个 Sprint 验证关闭。
- 负责人：gate keeper（非本 Sprint implementer，见第五节防失真）。
- 输出：`report-template.md` B 表（Sprint 门控汇总）+ 所有 A 表（单次运行记录）。

### Gate 3 — Human Product Gate（产品说了算）

- 内容：真人 5 秒测试 + 抽查 Gate 2 的录像/记录 + 产品负责人签字。
- 5 秒测试（PRODUCT_TREE.md 第七节）：找一个没见过产品的人打开首页，5 秒内能说出"这是按评审标准预审材料、每条点回原文的工具"（Grill 完成后用完整口吻）。说不出 → 打回重做首页/首屏，不接受"多讲两句就懂了"。
- 输出：一句话签字（通过/打回 + 理由）。

## 二、Sprint 完成判据

```
Engineering Gate 通过
  AND Black-box Stakeholder Gate 通过（或有条件通过 + 必改清单立案）
  AND Human Product Gate 通过
  => Sprint 完成，可更新 MILESTONES/CHANGELOG 并 commit
```

- 任一门不通过 → Sprint 未完成，不得记完成、不得合入"已验收"账本（PRODUCT_TREE.md 第四节）。
- "有条件通过"仅用于非致命问题（文案、边缘阻塞、单个 Delight 缺失）；致命 TRUST_FAILURE（编造引用/空材料说通过/版本混淆/人机混淆）无"有条件"，直接不通过。

## 三、每 Sprint 必跑 + 轮换

- **必跑（每 Sprint，不接受轮空）**：
  - `zero_patience_user` × 至少 1 个 scenario（Sprint 有新页改首屏/主线时跑 `first_review`；改修复/对比时跑对应 scenario）。
  - `adversarial_skeptic` × 至少 2 个陷阱（见该 persona 文件 S1–S6；与 scenario 组合跑，例如 `first_review+S3`、`create_revision+S4`）。
- **轮换（每 Sprint 至少 2 个，按主题选）**：

| Sprint 主题 | 优先轮换 |
|-------------|----------|
| 报告/矩阵/Drawer（I6/I7 类） | enterprise_reviewer + paper_author_reviewer |
| 数字矛盾/Overclaim（I8 类） | paper_author_reviewer + adversarial_skeptic（加测） |
| 答辩 Grill（I9 类） | contestant + competition_judge |
| 修复/重跑/Diff（I10/I11 类） | contestant + enterprise_reviewer |
| 新模板/第二垂直（I12 类） | enterprise_reviewer + contestant（criteria_from_raw 必跑） |
| 导出/审阅 UX（I13/I14 类） | competition_judge + zero_patience_user（加测） |

- 最小矩阵：2 必跑 + 2 轮换 = 4 张 A 表 + 1 张 B 表。时间充裕可加，但不得减。
- 豁免：无。赶时间只许加测（并行加人），不许减测。

## 四、Verdict 规则

- **通过**：0 致命 TRUST、0 主线 BLOCKED；严重 TRUST = 0；LEAK 可有但已立案改文案；TIME/USEFUL 达参考线（见 metrics.md）。
- **有条件通过**：无致命、无主线 BLOCKED，但有严重 TRUST 或边缘 BLOCKED；必须附必改清单（抄系统原话 + 改法 + 下 Sprint 验证项），由 Human Gate 决定是否放行。
- **不通过**：任一致命 TRUST；或任一主线 BLOCKED（含 USER FLOW BLOCKED）；或 5 秒测试失败且属首屏问题。
- 单轮 verdict 与 Sprint verdict 区分：单轮 TRUST_FAIL 只否决该轮；Sprint 不通过需 gate keeper 在 B 表中说明是哪几轮、什么原话、为什么致命。

## 五、防失真协议（tester 知道源码怎么办）

1. **角色隔离**：本 Sprint 的 implementer 不得做本 Sprint 的 Gate 2 tester；gate keeper 另指派（轮换表点名）。Reviewer 默认只读，不得边测边改产品。
2. **无知扮演**：tester 只能用 persona 的 ALLOWED KNOWLEDGE；FORBIDDEN 词表（Block / Criterion schema / Binding / Finding / SourceRef / API / 表名 / prompt）在运行中视为不存在。违反 → 该轮 `contamination: true`，作废或换人重跑。
3. **新鲜材料**：每次用 tester 手写的新 1 页 Markdown（≤50 行），不用 `benchmark/golden-v2/**`、不用旧 fixture、不用线上真实赛事全文/私有材料。陷阱材料同样新手写。
4. **无 oracle、无代码路径**：scenario 不给答案；tester 不对照源码/golden判分；不走 API/数据库/网络请求面板推进或验证。UI 卡住记 BLOCKED，不绕行。
5. **先行为后解释**：先记点击流 + 截图 + 系统原话，再写判断；判断须引用证据编号。禁止"我觉得它其实想……"式美化。
6. **失真自首与抽查**：A 表必须填 contamination；gate keeper 抽查 ≥1 轮录像；Human Gate 可随机指定重跑一轮（换不知情的人）。
7. **准备阶段冻结**：当前 Sprint 页面变化中，本包只做模板验证；任何试跑 verdict 写 `dry-run`，不得作为 Sprint 完成依据。

## 六、USER FLOW BLOCKED 处理

- 定义见各 scenario：UI 卡住即 BLOCKED。
- 禁止：用 API/数据库/源码绕过后算成功（绕过即作废）。
- 记录：按 report-template A 表记步骤 + 截图 + 有无下一步指引；B 表汇总主线/支线。
- 主线 BLOCKED（first_review / 改后反馈 / 版本对比主入口）→ Sprint 不通过；支线 BLOCKED → 有条件通过 + 必改清单。

## 七、与其他治理的关系

- 本政策服从 `docs/PRODUCT_TREE.md`（准入三问/树干串行/树冠并行/措辞纪律）与 `AGENTS.md`（单 implementer / 每阶段检查 + commit）。
- 本包自身不新增产品功能，不触碰树干；它是"树冠验收尺"，每个 Sprint 复用。
- 措辞审计：Gate 2  Floral 负责检查产品是否出现禁用词（已满足/已支撑/覆盖率%/分数/✅❌），见一次立案一次；门控词「缺失/有矛盾」无三件套即记 TRUST_FAILURE。
