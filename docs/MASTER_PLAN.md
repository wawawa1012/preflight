# Preflight 唯一 Master Plan

冻结：2026-09-15 · Phase 0 · Feature Freeze：2026-10-07。

## 决策优先级

用户后续明确指令 > 用户冻结 Prompt > 本计划 > 其他顾问建议。目录已更正为 F:\project\Preflight。
研究结束，不重新选赛道或重构技术栈。单人约三周交付省赛完整作品，以可定位证据和修复闭环为中心。

## 唯一执行路径

Rubric → Claim → Evidence → Finding/Risk → Repair → Re-run Diff。
先 mock 前端走通三幕，再接真实解析和固定 DAG，再修复对比/replay，最后八套 benchmark 和参赛材料。
本轮只交付工程基线；所有后续业务能力均是计划，不能写成已实现。

## 文档职责

| 文档 | 唯一职责 |
| --- | --- |
| PRODUCT.md | 用户、范围、黄金演示、非目标 |
| ARCHITECTURE.md | 技术、事实源、数据流和 UI 对应 |
| UI_SPEC.md | 页面、状态、证据交互、指标 |
| CONTRACTS.md | API、字段语义、版本和引用不变量 |
| BENCHMARK.md | 八套案例、三臂、公平性和指标 |
| MILESTONES.md | 日期、验收、D1 任务 |
| LEARNING_TRACK.md | 最小学习任务 |

## 已裁定的冲突与最小修正

未收到旧 Agent 方案，不能声称逐项审查。以下是冻结 Prompt 对可能路线的裁定：

- 多 Agent 自主调度 → 固定 DAG；独立 verifier 先拿 benchmark 证据。
- 向量优先 → SQLite FTS5/BM25 + 邻域；同义召回确实不足才考虑 embedding。
- 评委打分/聊天 → 证据风险报告 + 只读追问提纲。
- 大系统/全格式 → 单进程后端、本地 SQLite、四种文本格式。
- 后端先行 → 第一周 mock-first 前端；核心后台对象必须有 UI 去处。

需要显式澄清的技术边界：

1. 原路径与用户更正冲突 → 以后以 F: 为唯一仓库。D: 曾初始化空 Git，无项目文件，不作工作副本。
2. “点击必到证据”与 missing evidence 并非总能同时成立 → 缺失时显示 criterion、检索范围和缺失说明；有 Claim 时显示 Claim 原文，不虚构证据。
3. Nuxt UI 纯 Vue 需要 Tailwind CSS → 加入官方必需样式依赖，不引入另一套组件库或 Nuxt 应用框架。
4. DOCX 页码不稳定 → 原生段落定位；表格单元格使用确定的块顺序和段落遍历规则，解析阶段固化。不能模拟 Word 页码。
5. FTS5 默认分词对中文不理想 → 解析阶段验证 trigram 对中文长词的召回，短词用有界原文匹配补充；不因此加入向量库。
6. Rubric Coverage 与“找到任意文本”不同 → 只计已验证支持证据对应的 supported 项；保留分子/分母定义。

## Scope 闸门

不做 OCR、音视频、复杂图像、在线 PDF 编辑器、完整聊天、评委分数预测。不得为了宣传新增技术。
10/08–10/10 只修 bug、材料、视频和彩排。延期时先裁装饰、图表和非核心便利功能，保留三幕和证据真实性。
