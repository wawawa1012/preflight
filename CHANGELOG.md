# Progress log

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
