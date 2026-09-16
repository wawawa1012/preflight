# JSON contracts v0.1.0

结构唯一源：backend/app/contracts.py → contracts/schema.json → frontend/src/types/contracts.ts。
JSON Schema 负责结构约束；下列跨对象语义由后续业务验证器执行。Phase 0 的 check_contracts.py 只验证 fixture，不是生产 pipeline。
所有 JSON 使用 snake_case；ID 是不透明字符串，前端不解析；null 是未提供/未评估，不等于零。新增/破坏性字段变更必须更新版本和两端生成产物。

## 核心关系

Project → MaterialVersion → Document → Block → Locator。
Rubric(revision) → Criterion；Claim.source 是 Span；Evidence.source 是 Span，关联 criterion 和可选 claim。
Finding 关联 criterion、claims、evidence；Repair/ReviewQuestion 关联 finding。
Run 固定引用材料版本与 rubric revision；RunReport 是 UI 读取的完整快照。VersionDiff 引用两个 Run。
logical_key 跨版本标识同一逻辑文件；document_id/block_id 属于不可变版本，不能用旧 ID 指向新文本。

## 不变量

- 所有 ID 引用必须在当前快照内存在；历史 diff 的 before 引用属于 before report。
- PDF page、PPTX slide、DOCX paragraph、MD line 均从 1 开始；block.ordinal 从 0 开始。
- Span 的 start/end 是 Unicode code point 索引、半开区间；0 <= start < end <= len(text)，text[start:end] == quote。JS 处理索引需 Array.from(text)，不能直接用 UTF-16 slice。
- citation_valid 由代码生成；失效引用不得进入 supported、有效证据统计或结论展示。
- cross_document_conflict 必须有至少两个不同文档的真实引用，并确认可比条件；模型不能填 locator。
- missing_evidence 可有空 evidence_ids，但必须有 criterion 和 searched_document_ids；不能证明“全世界不存在证据”。
- Run completed 才能展示最终 metrics；failed/queued/running 显示 not_evaluated，coverage=null。
- 每个 criterion 有且仅有一项 assessment；优先级 conflict > critical > missing > weak > supported，未完成时 not_evaluated。
- 修复完成只记录 done，不修改 Finding。Diff 仅同项目、同 rubric revision、completed Run 可比。
- fingerprint 后续用规则生成：criterion_id + risk kind + 规范化主张主题/比较指标及条件 + 排序后的 logical_key，排除页码、quote 和变化数值。重复主题加稳定上下文消歧。
- 相同 fingerprint 为 unchanged（可比较前后详情）；仅旧为 resolved，仅新为 new。不可比时 entries=[]，reason 必填。

## API 冻结边界

已实现：GET /api/v1/health、GET /api/v1/report（Iteration 1 只读 mock）。以下业务接口是后续目标，不能当作可用服务。

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| GET /api/v1/health | 无 | {status: "ok", contract_version: "0.1.0"}（已实现） |
| GET /api/v1/report | 无 | RunReport（已实现，只读 mock） |
| GET /api/v1/projects | 无 | Project[] |
| POST /api/v1/projects | {name} | Project，201 |
| GET /api/v1/projects/:id/rubric | 无 | Rubric |
| PUT /api/v1/projects/:id/rubric | Rubric（revision 为期望旧版本） | 新 revision Rubric，过期返回 409 |
| POST /api/v1/projects/:id/versions | multipart：label、files[] | MaterialVersion，201 |
| GET /api/v1/versions/:id/documents | 无 | Document[] |
| POST /api/v1/projects/:id/runs | RunRequest | Run，202 |
| GET /api/v1/runs/:id | 无 | Run |
| GET /api/v1/runs/:id/report | 无 | RunReport，未完成返回 409 |
| PATCH /api/v1/runs/:id/repairs/:repair_id | {status: "todo"或"done"} | Repair |
| GET /api/v1/projects/:id/diff?before=…&after=… | run IDs | VersionDiff |

业务错误统一 ApiError {code,message,details}；400 输入、404 不存在、409 状态冲突、422 校验、500 内部错误。业务阶段安装 FastAPI 异常处理器；当前健康空壳尚未实现错误统一。
API 返回 RunReport 内联 blocks 足够支持 MVP Drawer，不创建复杂检索 API。分页和大文件优化等有真实负载再加。

## 生成与验收

仓库根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -X utf8 scripts/export_contracts.py
npm.cmd --prefix frontend run contracts
.\backend\.venv\Scripts\python.exe -X utf8 scripts/check_contracts.py
```

fixtures 是人工写定的契约示例，非解析产物、非真实 AIC 结果。D1 扩展完整三幕 mock，不实现生产 diff。
