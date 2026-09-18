# Handoff Verification Report

- Date: 2026-09-18
- Author role: Principal Architect / Product & Technical Lead (this session). Not current implementer. No code, no commit.
- Next deliverable: Iteration 6 计划书 — **only after this report is approved**. Not in this file.

## Goal

核对战场事实（HEAD、质量基线、路由、账本、宪法 v1.1 是否已在仓库），独立判断 Iteration 6 方向，停下等用户批准。

## Current context / assumptions

- 仓库：`F:\project\Preflight`，branch `main`，ahead of `origin/main` by 17.
- 宪法修正案 v1.1 的六条已由前任 architect 写入 HEAD `f28cc81`。本轮 **不重复实现** 那些文档。
- 质量数字以本次实测为准，不以交接提示词里的“88”为权威。实测碰巧仍是 88。
- 本报告不授权任何人开工改 `contracts.py` / `storage.py` / API。

---

## 1. Git HEAD / status（实测）

```
HEAD     f28cc817b21c75b18c36f50a9882b884e6451a51
subject  docs: adopt product tree governance with positioning upgrade and v1.1 corrections
parent   a410186 fix: return raw response from llm adapter for audit
branch   main → origin/main [ahead 17]
status   clean（git status --porcelain 空）
```

`f28cc81` 四文件、+139 行、无代码：

| 文件 | 作用 |
| --- | --- |
| `docs/PRODUCT_TREE.md` | 新建 121 行；功能取舍最高准则 |
| `AGENTS.md` | 增补「算力与并行施工治理」 |
| `docs/MILESTONES.md` | I6 方向、治理模型、时间线澄清 |
| `CHANGELOG.md` | 2026-09-18 治理条目 |

代码仍停在 `a410186`（LLM adapter raw_response）。

---

## 2. 宪法 v1.1 六条 vs HEAD（核对，不改）

| # | 修正案要求 | HEAD 落点 | 结论 |
| --- | --- | --- | --- |
| 1 | Grok = Architect；DS = 默认施工；GLM = 只读 reviewer；同时只有一个 implementer | `docs/MILESTONES.md:28` | 已落地 |
| 2 | 第一轮 = handoff verification，批准前不开工 I6 | `docs/MILESTONES.md:28` | 已落地；本文件即该任务 |
| 3 | 账本不是 KPI；否决 ≥12 | `docs/PRODUCT_TREE.md` §四 | 已落地（仓库内仅此处提及 ≥12，且为否决句） |
| 4 | 措辞能力分级；门控词；禁止满足/覆盖率/打分 | `docs/PRODUCT_TREE.md` §六 | 已落地 |
| 5 | 架构定位 ≠ 当前能力；仅 UTF-8 MD ≤1 MiB；Trust Layer 不上首页 | `docs/PRODUCT_TREE.md` 定位节 | 已落地 |
| 6 | 10/7 freeze；10/15 = 报名截止不是开发截止 | `docs/MILESTONES.md:29` | 已落地 |

**不重做。** 残留文档债（本轮仍不改）：

- `AGENTS.md:6-7` 仍写「本轮仅 Phase 0」「不提前实现 RubricMatrix」——与仓库已到 Iteration 5 矛盾。
- `AGENTS.md` 措辞节把「缺失／有矛盾」写成可直接上界面的词，未复述 PRODUCT_TREE 的门控条件。冲突时以 `docs/PRODUCT_TREE.md` 为准。
- `docs/PRODUCT_TREE.md` §八：「与 MASTER_PLAN 冲突时以 MASTER_PLAN 为准」。`docs/MASTER_PLAN.md` 自己规定「用户后续明确指令 > 本计划」。v1.1 / PRODUCT_TREE 是后续指令，产品取舍跟 PRODUCT_TREE；MASTER_PLAN 冻结不改。

---

## 3. 质量基线（实测，原样）

测试在 `f28cc81` 提交前跑完。当时工作区 = `a410186` + 未提交文档；`f28cc81` 只提交那些文档，**无 backend/frontend 变更**。数字对当前 HEAD 的代码仍有效。

### unittest

```
workdir: F:\project\Preflight\backend
cmd:     ./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
result:  Ran 88 tests in 1.782s
         OK
```

交接期望「88」与仓库一致。未为凑数改代码。

### 契约检查（只读，未跑 export）

```
workdir: F:\project\Preflight
cmd:     ./backend/.venv/Scripts/python.exe -X utf8 scripts/check_contracts.py
result:  PASS: schema freshness, fixture structure/references, quote checks, evidence annotation checks, criterion link checks, proposal checks, negative cases
exit:    0
```

### frontend build

```
workdir: F:\project\Preflight\frontend
cmd:     npm.cmd run build
script:  vite build && vue-tsc --noEmit
result:  vite v7.3.6；748 modules；built in 3.85s；exit 0
         dist/assets/index-kZZiSSWr.css  197.20 kB
         dist/assets/index-0WBdTwbm.js   356.51 kB
```

`&& vue-tsc --noEmit` 未单独打印，exit 0 表示 typecheck 通过。

### 五个 check 脚本

均 `cd frontend && node scripts/<name>.mjs`，exit 0。

| 脚本 | SUMMARY |
| --- | --- |
| `check-materials-nav.mjs` | 12/12 passed |
| `check-preview-race.mjs` | 23/23 passed |
| `check-evidence-annotation.mjs` | 14/14 passed |
| `check-rubric-link.mjs` | 24/24 passed |
| `check-agent-proposal.mjs` | 19/19 passed |

`check-materials-nav` / 同类脚本有 Vue `v-scx` overwrite warn，不计入失败。

---

## 4. 页面与路由（当前代码）

`frontend/src/router/index.ts`：

| path | name | 组件 | 产品角色 |
| --- | --- | --- | --- |
| `/` | workbench | `WorkbenchView.vue` | 首页。文案「参赛材料的 CI」。主卡 `ProjectCard` 为 **MOCK**：就绪度 `blocked`、评分项覆盖 `0 / 3`、关键风险 `1`，按钮「查看 Mock 报告」→ `/report`。另有添加材料 / 材料库 / 开发诊断「检查后端连接」。 |
| `/report` | report | `ReportView.vue` | `GET /api/v1/report` → 内存 `MOCK_REPORT`（`backend/app/mock_report.py`）。标签 `REPORT / MOCK`。含 Conflict / Missing / Overclaim、Supports、Rubric coverage、Submission readiness。 |
| `/materials` | materials | `MaterialsView.vue` | 材料库列表。 |
| `/materials/new` | material-new | `MaterialNewView.vue` | 上传 MD、Block 预览、保存。 |
| `/materials/:materialId` | material-detail | `MaterialDetailView.vue` | 证据标注、绑定、人工关联、AI 预检、`#block-*` 滚动高亮、「查看原文」。无独立 Drawer 组件。 |
| `/preview` | redirect | → `/materials/new` | 兼容旧链。 |

**没有** `/materials/:id/report`，没有 `/runs/:id/report`。

后端已实现（`backend/app/main.py`）：health、mock report、preview/save/list/get materials、evidence annotations、rubrics、binding、criterion-evidence-links、agent-proposals + accept/reject。

未实现冻结表里的 Project / Run / `GET /api/v1/runs/:id/report`。

---

## 5. 功能账本 vs 代码

对照 `docs/PRODUCT_TREE.md` §四（数量不是 KPI）。

| # | 账本 | 屏幕 | 代码事实 | 账本缺口 |
| --- | --- | --- | --- | --- |
| 1 | 材料上传与 Block 预览 | `/materials/new` | 有 | 无 |
| 2 | 材料库 | `/materials` | 有 | 无 |
| 3 | 证据标注 | `/materials/:id` | 有；`resolve_span` 验证门 | 无 |
| 4 | 绑定与人工关联 | `/materials/:id` | 有 | 无 |
| 5 | AI 预检 | `/materials/:id` | 代码完成；**真实 LLM 人工验收未做** | 状态「已有」偏乐观：实现有，验收无 |
| 6 | 评分矩阵（真实数据） | 材料报告页 | **无**。评委可见矩阵在 `/report` mock | I6 |
| 7 | 缺失证据（带检索范围） | 材料报告页 | mock finding 有；真数据无。详情页零关联只写「尚未关联引用」，不带 Block 范围 | I6 |
| 8 | Evidence Drawer | 材料报告页 | **部分**：详情页 `goToBlock` + `#block-*`；报告页无 Drawer，引用不可点回原文 | I6 |
| 9–12 | 矛盾 / Grill / 修复 / Diff | I7 页 | 无（mock 里有 conflict/overclaim，不可当能力） | 不做 I6 |

首页不是报告中心。5 秒测试（PRODUCT_TREE §七）当前失败：陌生人会看到「参赛材料的 CI」+ MOCK 覆盖率，说不出「按标准预审材料、点回原文」。

---

## 6. 必须保留的工程风险：Workbench fetch stub

**文件：** `frontend/scripts/check-materials-nav.mjs:58`

```js
const workbench = await context('/src/views/WorkbenchView.vue', '/', async () => jsonResponse({}))
```

**现状：** `WorkbenchView.vue` 的 `setup` **不发 fetch**。`checkBackend` 只在点击「检查后端连接」时请求 `/api/v1/health`。因此 stub 返回 `{}` 从未被 setup 消费。断言只检查 SSR HTML 含 `href="/materials"` 与 `href="/materials/new"`（12 项里的第一项）。

**若 I6 把首页改成报告中心**（mount 时拉材料摘要 / 预审摘要）：

1. 该 stub 仍返回 **对象 `{}`，不是数组**。`setup` 若 `response.json()` 后 `.length` / `.map`，脚本会抛，12/12 变红——与产品改动无关，是检查脚本没跟上。
2. 即便改成 `jsonResponse([])`，若页面不再渲染那两个 Materials `href`，第一项断言也会失败。产品要求保留「开始预检」→ `/materials/new` 和材料库入口；检查脚本必须同步改 stub **和** 断言，不能只改页面。
3. `ProjectCard` 的 MOCK 主按钮 `/report` **不在** 这 12 项里。拿掉 mock 卡不会被当前脚本抓住；5 秒测试和措辞纪律要靠 **新的** check（源码禁止「已满足/已支撑/覆盖率/就绪度/Trust Layer」+ 列表装载）。

I6 计划书必须把「改 `check-materials-nav.mjs` 的 workbench fetch stub」写成与首页同一工作包的硬步骤。漏了就是假绿。

---

## 7. 独立判断：是否同意现有 Iteration 6 方向？

**同意方向，不同意拿 mock RunReport 冒充真报告。**

PRODUCT_TREE 五问把 I6 定为：评分矩阵 + 缺失发现 + Drawer + 首页报告化。这是对的。没有这片叶子，Iteration 5 的提案/验证门/溯源仍是暗管（只活在材料详情里），评委首页仍是 SnapSync 式 mock CI。

要改的不是「做不做 I6」，是 **怎么做才诚实**：

1. **不要** 把 `GET /api/v1/report` 的 `RunReport` 填上真材料。该模型强制 Project / MaterialVersion / Run / Claim，以及 `supported`、`rubric_coverage`、`submission_readiness`、`cross_document_conflict`、`overclaim`。I6 没有矛盾检测、没有覆盖裁决，填进去就是违宪。Mock 端点保留、继续标 MOCK，退出首页主路径。
2. **要** 一个 **小只读装配端点**（树干：新契约 + 新 GET，**不改既有表、不改既有端点语义**）：从已有 `materials` / `blocks` / `bindings` / `links` / `annotations` / rubric 文件 **计算** 每条 criterion 的已核证引用数；零引用则给出带范围的「当前范围尚未发现引用」（filename + Block 数）。无新 Finding 表、无 FTS、无 LLM。这是树干，必须单独计划书 + 用户批准后 DS 才能写。
3. **5 秒测试与 I7 错位：** §七要求陌生人说出「…准备答辩」。Grill 在 Iteration 7。I6 首页不得承诺答辩。建议 I6 验收口吻收窄为：「按评审标准预审材料，把每条要求点回原文」。完整 §七口吻放到 I7。对外价值句已写在 PRODUCT_TREE：「让重要材料中的每个关键结论，都能追溯到真实依据」。Trust Layer 不上首页。
4. **「缺失」不是搜索。** 清点 `criterion_evidence_links` 不是 FTS。解释必须写清：核对的是本材料 N 个 Block 上的已核证关联，不是「全世界没有证据」。门控词「缺失」只有在这条范围说明在场时才能用。
5. **I5 真实 LLM 验收不阻塞 I6 装配**（装配不读 LLM）。I5 仍是用户在 `backend/.env` 走通闭环；AI 不得代打用户 key。详情页人工验收（I3/I4B/Materials UX）仍待办，但不挡矩阵叶子。
6. **不做：** PDF/PPTX/DOCX、Project/Run 流水线、向量库、第二套设计系统、覆盖率芯片、分数、好友/设置/头像、赛后 Artifact Grounding。

---

## 8. 本报告之后（尚未开工）

| 顺序 | 谁 | 做什么 | 何时 |
| --- | --- | --- | --- |
| 现在 | 用户 | 批准或驳回本报告（含 I6 方向修正与「小只读装配端点」） | 本轮结束条件 |
| 批准后 | Architect（本角色） | **另交** Iteration 6 计划书（树干审批：契约字段、路径、装配算法、TDD、check 脚本含 §6 stub、不做清单、准入三问） | 第二份计划，不在本文件 |
| 计划冻结后 | DS（默认 implementer） | 按 I6 计划书施工；同时只有一个 current implementer | 用户指定 DS 或点名本会话施工之后 |
| 并行（用户） | 用户 | I5：`backend/.env` → 绑定 → 预检 → 裁决 → 重启仍在 | 不消耗用户 API key 做批量 |

未经批准：不写 I6 计划细节以外的代码，不改契约，不派第二施工者进同一工作树。

---

## 9. 请用户冻结的决策（本轮 frontier）

批准本报告即视为冻结下面四条；有一条要改，先说，不要让 DS 猜。

1. I6 方向修正（§7.1–7.6）是否采纳？
2. 矩阵走「小只读装配端点」（新 GET + 新契约，不改旧表/旧语义）——树干，正式计划书另交。是否允许进入下一份计划？
3. I6 首页 5 秒口吻是否收窄、答辩留给 I7？
4. 当前 implementer 仍为「无」（Architect 只出计划）。I6 开工时默认 DS，还是点名本会话？

---

## Risks / open（不在本报告解决）

- `docs/UI_SPEC.md` / `docs/PRODUCT.md` / mock 报告仍使用 Supported / coverage / readiness。新 UI 不得复制；旧 mock 页可留作结构演示。
- `frontend/package.json` 已有 `echarts` / `vue-echarts`，I6 不用。
- `data/rubrics/` Git 忽略；无标准文件则绑定列表为空——本地若已有校赛工作标准，那是机器私有，不进仓库。
- 盲审红线（校名/校徽/导师）提交前再扫；现在不是 I6 范围。
