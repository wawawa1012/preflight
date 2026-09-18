# Progress log

## 2026-09-18 — I6.1：空预检像查过了（正交计数，不改契约）

详情与报告用提案列表 + 已确认关联并排展示：尚未预检 / 预检完成·当前材料尚未发现候选引用（含范围）/ 已发现 N 条待审核 / 已确认关联 N 条。报告前端组合 GET agent-proposals。标注降级为一句说明。未改 contracts/storage/llm。

## 2026-09-18 — Iteration 5.1：Proposal Quality（弃权 + 措辞 + benchmark harness，实现完成，待用户 live benchmark）

提交：

- `2667492` fix: add material exit on preflight report（报告页顶栏「返回材料」+ 未绑定/失败卡片 Workbench 出口，禁止 history.back）
- `9ce2508` feat: log preflight llm timing without contract change（preflight.llm INFO：model/prompt_version/block_count/prompt_chars/elapsed_ms/candidate_count；usage 存在才记 token）
- `dcc3565` test: add neg-java and pos-metrics preflight fixtures（benchmark/cases + scripts/run_preflight_benchmark.py，默认 stub 不打网）
- `e419c4c` feat: raise preflight prompt to v2 with abstention（`p5-criterion-preflight-v2`：直接依据 vs 练习题/教程不算证据；空数组正常且优于牵强；未设 temperature）
- `28414f5` fix: distinguish citation validity from relevance in proposal ui（徽章「原文引用有效」；有 completed 历史默认展示、按钮「重新预检」；空候选文案「空结果正常」）
- `7417ff4` fix: say confirmed links not verified support on report（「已确认关联 N 条」+ 引用行「原文已校验」；SCOPE_TMPL 同步；字段 verified_citation_count 不改名）
- `d5ca232` chore: keep local plan notes untracked（.hermes/ 撤出跟踪并 gitignore）

验证输出（本机 Windows，PowerShell）：

```
cd backend
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
...
Ran 99 tests in 2.160s
OK
```

```
.\backend\.venv\Scripts\python.exe -X utf8 scripts\run_preflight_benchmark.py --mode=stub
{"case": "neg_java", "passed_count": 0, "candidate_count": 0}
{"case": "pos_metrics", "passed_count": 1, "candidate_count": 1}
exit: 0
```

```
.\backend\.venv\Scripts\python.exe -X utf8 scripts\check_contracts.py
PASS: schema freshness, fixture structure/references, quote checks, evidence annotation checks, criterion link checks, proposal checks, preflight report checks, negative cases
exit: 0
```

```
npm.cmd --prefix frontend run build
dist/assets/index-kTmqemx1.css  197.79 kB │ gzip:  26.11 kB
dist/assets/index-DrtnGdDW.js   392.41 kB │ gzip: 123.62 kB
✓ built in 3.09s
build exit: 0
```

```
cd frontend
node scripts/check-materials-nav.mjs   -> SUMMARY: 15/15 passed
node scripts/check-preview-race.mjs    -> SUMMARY: 23/23 passed
node scripts/check-evidence-annotation.mjs -> SUMMARY: 14/14 passed
node scripts/check-rubric-link.mjs     -> SUMMARY: 24/24 passed
node scripts/check-agent-proposal.mjs  -> SUMMARY: 25/25 passed
node scripts/check-preflight-report.mjs -> SUMMARY: 20/20 passed
```

已知限制与说明：

- live baseline 待用户跑 `scripts/run_preflight_benchmark.py --mode=live`（DS 不代打用户 key）；live 不进 unittest / CI。
- 全文 blocks 导致假阳性仍是假设，本切片先用 prompt v2 约束，不上检索/预过滤/向量库。
- 空结果仍可能慢（仍 1 次 LLM 调用）；不做并发/cache。
- `verified_citation_count` 为历史字段名，含义是人已确认关联数；仅改显示措辞。

## 2026-09-18 — Iteration 6：报告中心 + 真实评分矩阵 + Evidence Drawer（实现完成，待人工验收）

完成：

- 工作包 A：docs/PRODUCT_TREE.md 五问第 5 条改为 Controlled Breadth / 树冠优先（小时级 slice、I6–I14 候选顺序、I13/I14 到点重新过准入三问）；账本插入 Claim Inspector（未开始）并把原 9–12 对齐 I8–I11；§七改为分阶段 5 秒测试（I6 半句 + Grill 迭代（预计 I9）全句）；§八写入 MASTER_PLAN 冻结口径；AGENTS.md 去掉历史 Phase 0 句、更新措辞纪律。
- 工作包 B：契约 MaterialPreflightCitation / MaterialPreflightMissing / MaterialPreflightCriterionRow / MaterialPreflightReport / MaterialPreflightSummary；ContractBundle 显式含 CriterionRow；fixture + check_contracts 新检查（零引用行必须带范围句、explanation 含文件名与 Block 数、缺 missing 负例被拒）；schema/TS 导出。
- 工作包 C：只读装配 backend/app/preflight_report.py（assemble_report / assemble_summaries）；未绑定抛 RubricNotBound，材料不存在返回 None；零引用行生成「当前范围尚未发现引用」+ 范围句；不写库、不产生 supported/coverage。
- 工作包 D：GET /api/v1/preflight-summaries、GET /api/v1/materials/{id}/preflight-report（未知材料 404 material_not_found、未绑定 409 rubric_not_bound，沿用既有 handler；未改既有表与端点语义）。
- 工作包 E：/materials/:materialId/report 报告页 + EvidenceDrawer（USlideover；Array.from 对齐 Unicode code point 高亮）+ 详情页「查看预审报告」入口 + check-preflight-report.mjs（16 项）。
- 工作包 F：Workbench 改为报告中心（预审摘要列表：已绑定 rev / 已核证引用 N 条 / 当前范围尚未发现引用 M 项；开始预检与材料库入口；Mock 报告降为页脚低权重「结构演示（Mock）」；检查后端连接标注开发诊断）；check-materials-nav stub 改为按 URL 返回数组并扩到 15 项。
- 工作包 G：CONTRACTS（两个 GET、409、装配语义）/ UI_SPEC（报告页与报告中心）/ MILESTONES / PRODUCT_TREE 账本 / README / CHANGELOG。

自检证据：

- backend unittest：96 例通过（88 存量 + 4 装配 + 4 API）。
- check_contracts.py：PASS（含 preflight report checks 与负例）。
- npm.cmd run build：exit 0。
- check 脚本：check-materials-nav 15/15、check-preview-race 23/23、check-evidence-annotation 14/14、check-rubric-link 24/24、check-agent-proposal 19/19、check-preflight-report 16/16。

已知限制：

- assemble_summaries 对每份材料逐个读取 binding/links（N+1）；当前材料规模可接受，未加缓存表/索引，规模上来再优化。
- 报告只覆盖当前单一 Markdown 材料模型；不生成 Finding、不写库、不做满足判定，也没有跨材料/数字矛盾检查。

## 2026-09-18 — 治理与定位：产品树宪法 v1.1（文档，无代码变更）

- 新建 docs/PRODUCT_TREE.md：定位升级为"AI 时代可信声明预审（Trust Layer）"（比赛材料预审为第一个垂直模板；架构定位≠当前能力，当前仅 Markdown）；产品树五问；树干→叶子映射（SnapSync"暗管"禁令）；显式功能账本（防暗管记录，数量不是 KPI）；准入三问与算力治理（树干串行/树冠并行）；能力分级事实性词表（门控词+Finding 三问）；5 秒测试；赛后 Artifact Grounding 未来方向。
- AGENTS.md 增补"算力与并行施工治理"节；显式拒绝清单（社交/设置中心/打分模拟等）。
- MILESTONES：Iteration 6 方向与 5 秒测试验收标准；治理模型（Grok=Principal Architect/Product Lead，DS=默认施工，GLM=只读 reviewer；Grok 首轮任务=handoff verification）；时间线澄清（10/7 冻结、10/10 校赛节点、10/15 20:00 省赛报名截止，以官方通知为准）。

## 2026-09-16 — Iteration 5：单 criterion AI 预检与提案裁决（实现完成，待人工验收）

完成：

- 契约：AgentProposal / ProposalCandidate / AgentProposalCreate / ProposalCandidateReject / ProposalAcceptance；proposed_by 扩为 ["human","agent"]；EvidenceAnnotationCreate 移除 proposed_by（防客户端伪造溯源）；合成 fixture + 负例（invalid 必带码、accept 回填一致性、篡改被拒）。
- LLM 适配层 backend/app/llm.py：PREFLIGHT_LLM_* 环境变量 + backend/.env 手写解析；PROMPT_VERSION=p5-criterion-preflight-v1；prompt 上限 24000 字符（超出 400 material_too_large，绝不静默截断）；严格 JSON 解析（未知字段/缺字段拒绝）；错误分类 503/502/504/502；唯一新依赖 openai==3.14.1。
- 存储：agent_proposals（raw_response 审计列不进契约）+ proposal_candidates（material 索引）；验证门（block 属于材料 + resolve_span）标记 passed/invalid+机器码；accept 单事务：候选校验→语义查重→span 复算→物化 annotation+link（provenance=agent）→回写候选；reject 记录可选原因。
- API：POST/GET 提案、GET 单提案、accept/reject 五个端点 + 400/409/502/503/504 handler；失败也落库（status=failed），201 仅限 completed。
- UI：criterion 行 AI 预检 + 候选面板（验证徽章、invalid 不可接受、accept/reject、失败错误码）；human/agent 溯源徽章；busy 互斥；未绑定时预检被 guard 阻止。
- 文档：CONTRACTS（Proposal 层语义 + Agent Integration Note 重写）、UI_SPEC、MILESTONES、README（env 配置）。

自检证据：

- backend unittest：88 例通过（新增 27：llm 解析/配置/上限/错误映射、验证门、accept 注入失败原子性、语义查重、invalid/已裁决、reject、跨材料隔离、级联）。
- 契约管线 export/npm contracts/check_contracts PASS。
- frontend build 通过；check-materials-nav 12/12、check-preview-race 23/23、check-evidence-annotation 14/14、check-rubric-link 24/24、check-agent-proposal 19/19。
- 隔离 stub 冒烟（本地 OpenAI 兼容 stub + 独立实例，无真实 key）：建材料→绑定→预检 201（passed + invalid quote_not_found）→accept 物化 agent→重复 accept 409 candidate_already_reviewed→reject→重启后提案/裁决/关联保留→停 stub 后预检 502 且失败提案落库；19/19。
- 真实 LLM 调用由用户填 backend/.env 后人工验收。

待办：

- 人工验收（含真实兼容服务一次调用）。

## 2026-09-16 — Iteration 4：Evidence→Criterion 人工关联（Phase A 已验收；Phase B 待验收）

完成：

- 契约：RubricBinding / RubricBindingCreate / CriterionEvidenceLink / CriterionEvidenceLinkCreate（rationale 非空校验），四键入 ContractBundle；合成 fixture + check_contracts 负例（引用一致、篡改 span 被拒）。
- 只读 rubric 文件仓 backend/app/rubric_store.py：启动时加载 data/rubrics/*.json，逐份用冻结 Rubric 模型校验；非法/重复 (id, revision) fail-fast 拒绝启动；空目录合法；Criterion ID 写在文件里；新增 scripts/validate_rubrics.py 预检。当前 data/rubrics 为空 → GET /api/v1/rubrics 返回 []。
- 存储：material_rubric_bindings（材料唯一绑定，幂等 / 换绑冲突）、criterion_evidence_links（material_id/annotation_id 双外键 CASCADE、UNIQUE(annotation_id, criterion_id, rubric_revision)、material 索引）；create_link 单事务：annotation 身份 → 绑定 → span 复验 → 查重 → 插入。
- API：GET /api/v1/rubrics、材料绑定 GET/PUT、关联 GET/POST/DELETE、annotation DELETE；错误映射 404 *_not_found / 409 rubric_not_bound·duplicate_link·binding_conflict / 400 span_mismatch·invalid_request。
- UI（MaterialDetailView，无新路由）：评分标准区（未绑定列表或“尚未配置评分标准”；已绑定 Criterion 列表 + 关联引用 + 查看原文 + 移除关联）；证据列表加关联（Criterion + rationale 表单）与删除（确认）；BlockList 增加 annotatedCounts 徽章/高亮与 #block-* 锚点定位（找不到明确提示）；操作互斥沿用 preview race 纪律。
- 文档：CONTRACTS（两层区分 + Agent note 扩展）、UI_SPEC、MILESTONES、README。

自检证据：

- backend unittest：61 例通过（新增 23：rubric 仓加载/fail-fast/幂等、绑定幂等与换绑 409、跨材料/未知 criterion/篡改 span/重复/级联/跨连接/隔离、API 错误码与 handler）。
- 契约管线 export/npm contracts/check_contracts PASS。
- frontend build 通过；check-materials-nav 12/12、check-preview-race 23/23、check-evidence-annotation 14/14、新增 check-rubric-link 24/24。
- 隔离冒烟（复制 backend 到临时目录 + 合成标准 + 独立 DB，端口 8010）：建材料 → 绑定 201 → 幂等 200 → 换绑 409 → 关联 201 → 重复 409 → 重启后绑定/关联保留 → 篡改 span 400 → 移除关联 204/404 → 删除标注 204 且关联清空、材料与 Block 完整 → 重复删除 404；17/17。另实际观察到非法 rubric 文件导致启动被拒（fail-fast）。

状态：

- Phase A 已由用户验收通过并收口提交；Phase B 等待用户确认评分原文后逐字转录、预检与保真核对。

### Phase B：转录确认稿并加载（实现完成，待人工验收）

- 逐字转录团队负责人 2026-09-17 确认的工作标准到 data/rubrics/aic2026-school-working-rev1.json（UTF-8 无 BOM，实测首字节 7B-0A-20）；仅 source_note 按用户指示更新为“已逐条确认”的 provenance 表述，三条 criterion 与确认稿逐字一致。该文件位于 Git 忽略的 data/rubrics/，不进仓库。
- 预检输出（exit 0）：`OK rubric_aic2026_school_working rev1 criteria=3 title=AIC 2026 校赛工作标准（子集 · 工作草案，非官方）`
- 重启后端后 GET /api/v1/rubrics 返回 1 条：id=rubric_aic2026_school_working、rev1、3 criteria；未绑定材料的 rubric-binding 返回 null（空态正确）。
- UX 修补：未绑定标准时“关联”按钮禁用并带 title 提示“绑定评分标准后可关联”。
- 无契约变更（未改 schema/TS）；frontend build 通过，check-rubric-link 24/24、check-evidence-annotation 14/14 无回归。

状态：

- Phase B 实现完成，待人工验收；取得官方评审细则后将转录为新文件，不覆盖本版本。

## 2026-09-16 — Iteration 3：Evidence Layer MVP（实现完成，待人工验收）

完成：

- 契约：EvidenceAnnotation / EvidenceAnnotationCreate（source 复用冻结 Span；proposed_by: Literal["human"] 为 Agent 版本化扩展点）；中文 fixture + check_contracts 负例（篡改 quote 被拒）。
- 验证门：backend/app/evidence.py 纯函数 resolve_span(text, quote)——精确子串、Unicode 代码点索引、重复取第一次；未命中抛 QuoteNotFound → 400 quote_not_found。
- 存储：evidence_annotations 表，materials/blocks 双外键（FK CASCADE）；material_id 由服务端从 block 行派生；quote 校验与插入同一事务，未命中不留下任何行。
- API：POST /api/v1/evidence-annotations（201）、GET /api/v1/materials/{id}/evidence-annotations、GET /api/v1/evidence-annotations/{id}；RequestValidationError → 400 invalid_request；错误统一 ApiError 机器可读码。
- UI：MaterialDetailView 证据区（标注列表显示 quote + line + note；Block 行内表单 quote 预填整块可改窄 + 可选 note；保存互斥沿用 preview race 纪律）；BlockList 新增可选 cite 槽，preview 流不传、行为不变；无新路由，Workbench 导航不变量保持。
- 检查脚本：frontend/scripts/check-evidence-annotation.mjs（SSR 渲染 + setup 行为级：quote 预填、保存互斥、quote_not_found 不落列表、cite 槽差异）。

自检证据：

- backend unittest：38 例通过（新增 14：代码点/首末整块/重复、未命中无残行、未知 block/material/annotation 404、FK 级联、跨连接、按材料隔离）。
- 契约管线：export_contracts.py / npm.cmd run contracts / check_contracts.py 通过。
- frontend build/typecheck 通过；check-materials-nav 12/12、check-preview-race 23/23、check-evidence-annotation 14/14。
- 冒烟（真实 HTTP）：建材料 201 → 合法标注 201（span 5..14、material_id 由服务端派生）→ 非法 quote 400 quote_not_found → 未知 block 404 → 缺字段 400 invalid_request → 列表/详情一致 → 未知 annotation/material 404；9/9 通过。冒烟后已恢复数据库备份（未在材料库留下测试记录）。

待办：

- 人工验收通过后提交最终收口。

## 2026-09-16 — Materials IA 重做：Hub 与 Add Workflow（实现完成，待人工验收）

背景：上一版 Materials UX Slice 浏览器验收失败（/materials 与 /preview 形成导航 loop、宽屏大面积空白、/preview 初始态像工程表单、路由暴露实现概念），本轮按冻结 IA 重做。

完成：

- 正式 IA：/materials（Hub）、/materials/new（添加工作流）、/materials/:materialId（详情）；/preview 只做兼容重定向，不再是平级导航目标。
- /materials：页头明确“evidence sources”定位，主 CTA 添加材料；主区紧凑行列表改为整行 RouterLink（hover/focus-visible）；右侧单个克制概览面板（已保存数量、总 Block 数、最近保存、支持格式，全部由列表响应前端计算，无后端 KPI）；空态为居中一句说明 + 主按钮。
- /materials/new：未选文件时页面中央是任务区——步骤条（上传 → 校验并预览 → 保存）+ “Locator 由确定性程序生成”说明 + 可点击/可拖入的 drop zone；选中后“生成预览”成为唯一主按钮；生成预览后上传表单整体退场，顶部面包屑 + 低权重“更换文件”。
- 抽取 MaterialHeader 组件（sticky 身份头：filename、状态徽章、截断 meta、动作位）；/materials/new 预览态与 /materials/:materialId 详情共用，保存动作滚动全程可达。
- Workbench Materials 卡按钮指向 /materials/new 与 /materials；其余不动。
- 三个 Materials 页面统一补低权重 `← Workbench` 出口（/materials、/materials/new 两种状态、/materials/:id 两种状态），UI_SPEC 记入全局 invariant：二级工作区必须有显式回 Workbench 入口。
- 检查脚本 check-preview-race.mjs 同步到新视图与路由，新增 IA 静态断言（正式路由、重定向、无平级 preview、无 localStorage）。
- 新增 check-materials-nav.mjs：SSR 渲染断言三个页面的 Workbench 出口与页内导航，并用真实 fetch stub 验证列表/详情/404 状态。
- 文档：UI_SPEC 路由表补当前已实现 Materials IA；README 更新入口说明。

自检证据：

- frontend build/typecheck 通过；check-materials-nav 12/12；check-preview-race 23/23。
- backend unittest 24 例通过；contract check PASS。
- 未执行真实浏览器视觉/点击验收（本环境无浏览器自动化）。

待办：

- 人工验收通过后提交收口。

## 2026-09-16 — Materials UX Slice（浏览器验收失败，已被 IA 重做取代）

验收结论：/materials 与 /preview 形成 UX loop、宽屏利用不足、/preview 初始态像工程测试表单、路由暴露实现概念。本轮实现被“Materials IA 重做”取代，以下记录保留作历史。

完成：

- /preview 只保留未持久化上传工作台：删除页面级 amber 横幅，状态与保存按钮移入 sticky Material header。
- 保存成功用 router.replace 进入 /materials/:materialId；Saved Material 页面不含选择文件/临时警告/保存按钮，badge 为绿色“已保存”，显示本地保存时间与截断 sha256。
- 新增 /materials 列表页与 GET /api/v1/materials（MaterialSummary：id、filename、created_at、block_count，按时间倒序，不含 blocks）。
- 从正式 UI 移除“读取最近保存的材料”；后端 recent 接口与指针保留为工程能力。
- Workbench 的“材料预览（临时）”卡改为 Materials 入口（上传新材料 / 已保存材料），不显示假数量。
- 抽取最小共享 BlockList 组件与本地时间格式化工具；Block Locator/ordinal 展示未回归。
- 文档：README、CONTRACTS 更新。

自检证据：

- backend unittest：24 例通过（新增列表顺序/计数测试）。
- HTTP 只读验收：列表字段、倒序、详情一致、404、preview/report 回归 10/10（未新增材料，保留人工验收的 2 份材料）。
- frontend build/typecheck 通过；race/state 检查 19/19（含保存后跳转、保存失败不跳转）；contract check PASS。

## 2026-09-16 — Iteration 2B（实现完成，待人工重启验收）

完成：

- SQLite 持久化模块 backend/app/storage.py：materials → blocks（外键 + 唯一 ordinal）与单行 recent_material 指针；参数化 SQL；每连接启用 PRAGMA foreign_keys；保存与指针更新同一事务，无 INSERT OR REPLACE。
- 接口：POST /api/v1/materials（服务端重新校验并重新解析上传文件，返回 201 + SavedMaterial）、GET /api/v1/materials/{id}、GET /api/v1/materials/recent；未知 ID/无记录返回 404 + ApiError。
- 契约：SavedMaterial 加入 contracts.py / JSON Schema / TS 类型。
- 前端：预览页新增“保存材料”与“读取最近保存的材料”，区分临时/已保存状态；不依赖 localStorage。
- 文档：README、CONTRACTS、MILESTONES 更新。

自检证据：

- backend unittest：20 例通过（含真实原子性测试：Block 写入中途制造 IntegrityError 后材料/Block/指针均不残留；外键约束实际生效）。
- 真实 HTTP E2E：保存/按 ID 读取/新身份/recent/404/400/失败不标已保存 11/11；停止并重启后端后 recent 与旧材料仍一致 3/3。
- frontend build/typecheck 通过；2A 竞态检查脚本 9/9；contract check PASS。

待办：

- 人工重启验收通过后做本轮完成提交与进度收口；当前实现未 commit。

## 2026-09-15 — Phase 0

完成：

- 根据用户更正，唯一施工仓库为 F:\project\Preflight；初始化 main。
- Master Plan、六份指定 docs、AGENTS、CONTRACTS、README 和目录占位。
- Pydantic v2 契约 → JSON Schema → TypeScript 类型；人工引用/冲突/缺失示例，明确非真实解析结果。
- Vue 3/Vite/TS/Nuxt UI v4 纯 Vue 空壳，Router/Pinia 注册，Lucide 依赖，vue-echarts 预留。
- FastAPI health 空壳，Vite /api 代理。无业务解析、RAG、LLM 或 RubricMatrix。
- 锁定 npm / Python 依赖；Windows UTF-8 启动说明。

验收证据：

- npm run build：Vite production build 和 vue-tsc 均通过。
- check_contracts.py：schema 未漂移、fixture 结构/ID/引用通过，篡改 quote、无效 block_id、未知字段被拒绝。
- SQLite 内存库 CREATE VIRTUAL TABLE USING fts5 成功，无业务数据库创建。
- uvicorn 实际启动；GET :8000/api/v1/health → ok；GET :8000/openapi.json → Preflight。
- Vite 实际启动；GET :5173/ → 200 且存在前端入口；GET :5173/api/v1/health → ok。

限制与后续：

- 浏览器工具无法验证管理员安全策略，阻止访问 localhost；未绕过。未完成人工视觉/点击验收；D1 由实际浏览器确认。
- npm audit：1 low，Nuxt UI → @nuxt/fonts → fontless → esbuild 0.27.7，GHSA-g7r4-m6w7-qqqr；普通 audit fix 无法在现有范围内消除。没有强制跨范围覆盖传递依赖；后续跟进上游修复。服务只绑定 127.0.0.1。
- D:\Projects\Preflight 曾按原 Prompt 创建空 Git，用户更正时尚无项目文件；没有在 D: 继续施工。
- 正式 AIC rubric 和旧 Agent plan 未提供；不虚构权重，不声称已审阅旧方案。
- 下一阶段以 MILESTONES 的 D1 清单为准；本轮到此停止，不继续业务实现。
