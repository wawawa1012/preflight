# Progress log

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
