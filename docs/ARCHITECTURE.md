# 架构冻结

## 拓扑

浏览器 Vue SPA → /api/v1 → 单 FastAPI 进程 → SQLite + 本地不可变材料文件。
开发时 Vite 代理 /api；不需要跨域放行。生产托管暂不设计。

前端 Vue 3/Vite/TypeScript/Nuxt UI v4（纯 Vue）/Vue Router/Pinia/vue-echarts；图标走 Nuxt UI 的 Lucide/Iconify。
Tailwind 是 Nuxt UI 样式依赖。json-schema-to-typescript 仅用于从契约生成类型，避免手写两份字段；成本为一个开发依赖，替代方案是手动同步，易漂移。
后端 Python 3.11+/FastAPI/Pydantic v2/标准库 sqlite3 + FTS5；后续解析依赖 PyMuPDF、python-pptx、python-docx。
此时只安装启动/契约所需依赖；解析器、LLM 适配器尚未实现。

## 固定 DAG（后续实施）

解析生成 Document/Block/Locator → Extract Claim → Retrieve 候选 → Adjudicate → Verify → Aggregate Report。
Repair 为用户动作；新材料版本触发新 Run；代码计算 VersionDiff。失败 Run 不产生完成报告，也不参与 Resolved 统计。
单进程、单活动 Run、简单持久化状态 + 轮询；重启时遗留 running 标记 failed，允许重新运行。无需任务队列系统。

## 事实与裁决

- Locator 只由解析程序产生；模型只选择已给定 block_id 和原文引用，不生成页码。
- Span 用原始 Block 文本中的 Unicode code point 半开区间 [start,end)，代码验证原文等于 quote。
- 引用有效只说明来源真实，不代表语义支持。支持关系由裁决提出，验证拒绝不存在/错位来源。
- 数字/日期比较、单位归一、coverage、aggregation、diff 全由代码处理。先确认指标、数据集、条件相同，才比较数值。
- FTS5/BM25 以 criterion/claim 为 query，限定当前版本文件并扩展相邻 block。中文召回单独验收。
- 上传名称不作为存储路径；生成 ID 存储，限制尺寸和扩展名，材料内容作为不可信数据送入模型。

## 可替换 LLM（尚未实现）

薄 provider：输入 messages + JSON schema + 模型配置，返回通过 Pydantic 校验的结果和 usage。
base_url/api_key/model 在服务端配置，业务逻辑不写模型名。优先 JSON schema structured output；不支持的供应商明确报能力不匹配或使用配置的 JSON 输出 + 本地校验，绝不默默接受文本。
有限重试一次结构修复；持续失败标记阶段失败。程序引用验证不可被模型覆盖。
cache key 包含输入材料 hash、rubric revision、stage/prompt/schema version、provider/base_url/model/参数；存储输出、校验结果、usage。
replay 仅精确缓存命中，miss 明确失败，不联网回退。mock 是人工 fixture，与 replay 分开。

## 每个后台对象的 UI 去处

| 产物 | 页面 |
| --- | --- |
| Project / MaterialVersion / Document | Workbench / Materials / Versions |
| Rubric / Criterion | Rubric Studio / Report |
| Block / Locator / Span | Evidence Drawer |
| Claim / Evidence | Evidence Card / Conflict Compare |
| Run / stage / error | Preflight Progress |
| Finding / Assessment / Metrics | Report / RubricMatrix |
| Repair / VersionDiff | Repair Checklist / Versions |
| ReviewQuestion | Review Questions |
| Benchmark 结果、限制 | Methodology / Benchmark |

## Deferred hardening（明确但不实现）

- Format-specific Locator：Markdown → line；PPTX → slide；DOCX → paragraph + heading/section context；PDF → page + textual span/section context。section 如 §3.1.2 是人类可读上下文，不作为唯一稳定定位键。当前 SQLite persistence 只支持 Markdown line Locator；接入其他格式前扩展，不在 2B 实现。
- Upload lifecycle：当前 preview/save 各上传一次原文件，用于维持 server-side trust boundary。未来只有实际文件规模/延迟证明有必要时，考虑 server-side staged upload / temporary upload token，消除重复上传，同时仍不信任客户端提交的 Block/Locator。
- Persistence performance：当前首先保证 correctness。后续先测 save latency、load latency、DB size、Block count scaling、lock contention；有数据后再决定 executemany / batch insert、additional indexes、WAL、sha256 dedup、FTS5。不在本轮实现这些优化。

## 依赖与范围

不引入 LangChain、LangGraph、CrewAI、AutoGen、MCP、Chroma/Pinecone/Weaviate、Redis、Celery、微服务、Kubernetes、知识图谱、插件系统、本地大模型、微调。
先验证小闭环再增加能力。依赖锁定在 package-lock.json 和 requirements.txt。

参考：[Nuxt UI 官方 Vue 安装](https://ui.nuxt.com/docs/getting-started/installation/vue)。
