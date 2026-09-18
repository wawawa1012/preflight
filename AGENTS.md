# Preflight 施工约定

- 唯一仓库：F:\project\Preflight（用户于 2026-09-15 更正原 Prompt 的 D: 路径）。
- 唯一蓝图入口：docs/MASTER_PLAN.md。原始冻结需求优先，用户后续明确修正优先于本文。
- 施工权（Preflight Development Operating Model v1）：任意时刻只能有一个 current implementer；可以显式在 AI 之间交接。Reviewer 默认只读。不得多个 AI 同时修改同一工作区。
- 当前进度以 docs/MILESTONES.md 为准；功能取舍以 docs/PRODUCT_TREE.md 为准。不要把历史「Phase 0」句读成当前施工范围。
- Vue 3 + Vite + TS + Nuxt UI v4 纯 Vue；禁止第二套设计系统。
- Python + FastAPI + Pydantic v2 + SQLite/FTS5；Windows 原生，不混用 WSL。
- 禁用 LangChain/LangGraph/CrewAI/AutoGen/MCP、向量数据库、Redis/Celery、微服务、K8s、知识图谱、自研插件、本地模型、微调。
- 新功能必须增强 Evidence Adjudication / Repair Loop；新框架需说明收益、成本、替代方案。
- 原文 Block/Span 是事实源；程序生成 Locator。LLM proposes, code disposes。
- 不预测比赛分数。不把 checklist 完成当成风险解决。不把 mock/replay 当成真实测评。
- contracts.py 是契约结构源；变更后导出 JSON Schema、TS，更新契约说明和 fixtures。
- 代码直白可读，关键位置简短注释；每个新技术点给 2–4 概念、可略过细节、20–60 分钟学习任务，然后继续实施。
- 每阶段更新 CHANGELOG 并 Git commit；提交前运行与变更相称的检查，避免提交密钥、用户材料、缓存和虚拟环境。

## 算力与并行施工治理（2026-09-18 增补）

- 功能取舍最高准则见 docs/PRODUCT_TREE.md：准入三问（屏幕入口／验收标准／demo 秒数）答不上即不做。
- 树干串行：contracts.py、storage、API 核心路径沿用单 implementer 模型；不改既有表与端点语义。
- 树冠并行：叶子页面、检查脚本、文档、benchmark 用例可拆成有界工作包并行，每包独立可验收、自带准入三问答案。
- 显式拒绝：好友/社交、设置中心、登录头像、无 demo 秒数的功能、打分模拟（✅❌ 或分数预测）。
- 措辞纪律：以 docs/PRODUCT_TREE.md 第六节为准。始终允许：已核证引用 N 条／已关联 N 条／已绑定 rev N／未评估／当前范围尚未发现引用（须说明范围）。门控词「缺失」「有矛盾」仅在对应检查已实现并执行后使用。禁用「已满足/已支撑」、覆盖率%、分数预测。

## Phase 0 验证

前端：在 frontend 执行 npm.cmd ci 和 npm.cmd run build。
后端：按 README 建 venv，启动 uvicorn，检查 /api/v1/health 与 /openapi.json。
契约：执行 scripts/export_contracts.py、frontend 的 npm.cmd run contracts、scripts/check_contracts.py。
