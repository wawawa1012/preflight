# 边做边学：约 30% 学习 / 70% 施工

每个新技术点先说明用途，理解 2–4 个概念，做 20–60 分钟任务，随后回到项目；不先刷完整课程。

## 今天第一课：JSON 契约与前后端边界（45 分钟）

为什么：让前端能先用假数据完成界面，后端随后返回同样的数据形状。
只需理解：对象/数组、ID 引用、HTTP 请求/响应、schema 校验。
暂不学：泛型技巧、复杂状态管理、RAG、提示词框架。

1. 10 分钟：按 README 启动前后端，打开 /docs 和首页，点击“检查后端连接”。
2. 15 分钟：读 contracts/fixtures/report.json，从 Finding 的 evidence_ids 找到 Evidence，再找 Block 和 Document；用纸画出这条链。
3. 10 分钟：把 fixture 复制到临时文件，尝试额外字段或非法 severity，理解 Pydantic 为什么拒绝；不要改已冻结 fixture。
4. 10 分钟：向自己解释“为什么 95% 的原文引用有效，仍可能是 unsupported/conflict”。

完成标准：能说出 filename/locator 来自程序，引用真实不等于主张有充分支持；勾选修复不等于 resolved。

## 接下来按需学习

| 技术 | 为什么需要 | 概念 | 暂不学 | 最小任务 |
| --- | --- | --- | --- | --- |
| Vue SFC/Router | 把报告拆成可读页面 | props、ref、事件、路由 | SSR/Nuxt 服务端 | 30 分钟：列表点击更新选中项 |
| Nuxt UI/Tailwind | 统一视觉和交互 | UApp、组件 props、utility class | 自建设计系统 | 20 分钟：调整一张 Card 间距 |
| Pinia | 页面共享选择状态 | store、state、action | 插件/持久化 | 25 分钟：保留选中项目 |
| FastAPI/Pydantic | HTTP 数据边界 | endpoint、模型、422 | ORM/异步优化 | 30 分钟：在 /docs 查看 health schema |
| Block/Span | 证据可追溯 | 不可变文本、locator、offset | OCR | 40 分钟：手工核对三段 quote |
| FTS5 | 找候选证据 | tokenizer、BM25、邻域 | 向量库 | 45 分钟：比较中文检索样例 |
| 结构化 LLM | 模型结果可验证 | schema、校验、cache、replay | Agent 框架 | 45 分钟：识别三种坏输出 |
| Diff/Benchmark | 证明修复有效 | fingerprint、TP/FP/FN、基线 | 统计论文全套 | 45 分钟：人工算一个 case 的 F1 |

Nuxt UI 纯 Vue 接入参考：https://ui.nuxt.com/docs/getting-started/installation/vue
