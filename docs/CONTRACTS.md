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

已实现：GET /api/v1/health、GET /api/v1/report（Iteration 1 只读 mock）、POST /api/v1/preview/markdown（临时预览）、POST /api/v1/materials 与 GET /api/v1/materials、/api/v1/materials/{id}、/api/v1/materials/recent（Iteration 2B 持久化）、POST /api/v1/evidence-annotations 与 GET /api/v1/materials/{id}/evidence-annotations、/api/v1/evidence-annotations/{id}（Iteration 3 证据层）。以下业务接口是后续目标，不能当作可用服务。

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| GET /api/v1/health | 无 | {status: "ok", contract_version: "0.1.0"}（已实现） |
| GET /api/v1/report | 无 | RunReport（已实现，只读 mock） |
| POST /api/v1/preview/markdown | multipart：file（仅 .md，UTF-8，≤1 MiB） | MarkdownPreview（已实现，临时预览，不保存；错误返回 400 + ApiError） |
| POST /api/v1/materials | multipart：file（同上，服务端重新解析） | SavedMaterial，201（已实现，原子写入 SQLite） |
| GET /api/v1/materials | 无 | MaterialSummary[]（已实现，摘要列表，按 created_at 倒序，不含 blocks） |
| GET /api/v1/materials/{id} | 无 | SavedMaterial；未知 ID 返回 404 + ApiError |
| GET /api/v1/materials/recent | 无 | SavedMaterial；无记录返回 404 + ApiError（工程能力，当前 UI 不消费） |
| POST /api/v1/evidence-annotations | {block_id, quote, note?} | EvidenceAnnotation，201；quote 未命中 400 quote_not_found、未知 block 404 block_not_found、缺字段 400 invalid_request |
| GET /api/v1/materials/{id}/evidence-annotations | 无 | EvidenceAnnotation[]（未知材料 404 material_not_found） |
| GET /api/v1/evidence-annotations/{id} | 无 | EvidenceAnnotation（未知 404 annotation_not_found） |
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

业务错误统一 ApiError {code,message,details}；400 输入、404 不存在、409 状态冲突、422 校验、500 内部错误。预览接口按此返回 400，材料读取按此返回 404；其余业务接口后续统一。
MarkdownPreview 是临时预览响应：只含文件身份（document_id、filename、size_bytes、sha256）与 blocks，不构成 Document 或 MaterialVersion，不写入任何存储。每个非空行一个 Block：kind=line、index 为 1 开始的行号、end_index=null、block_index=1；ordinal 从 0 连续递增。空行严格定义为去掉 LF/CRLF 后长度为 0 的行：空行不生成 Block 但计入 line_count；只含空格或 Tab 的行不是空行，必须生成 Block。UTF-8 BOM 合法，BOM 不属于第一行的 Block text。
SavedMaterial 是 2B 的最小持久化实体：materials（id、filename、size_bytes、sha256、line_count、created_at）与 blocks（id、material_id 外键、ordinal、line_number、text、block_index）两张表，加一个单行 recent_material 指针；不使用 INSERT OR REPLACE。保存与指针更新在同一事务内完成。blocks[].document_id 指向材料 id（当前只有 Material → Block 两级，不是 Document/MaterialVersion，也不是已完成的 Run 或 VersionDiff）。Save 接口服务端重新校验并重新解析上传文件，不信任浏览器回传的 blocks/locator/sha256。
MaterialSummary 是列表摘要（id、filename、created_at、block_count），不包含 blocks；文件类型由 filename 后缀展示。
EvidenceAnnotation 是 Iteration 3 最小证据层：source 复用冻结 Span（block_id/start/end/quote），服务端用纯函数 resolve_span(text, quote) 校验后才能写入（精确子串、Unicode 代码点索引、重复取第一次出现）；未命中返回 400 quote_not_found，同一事务回滚，库中不存在无效引用。material_id 由服务端从 blocks 行派生，不接受客户端提交；evidence_annotations 对 materials/blocks 双外键（FK CASCADE）。本迭代只表示“引用了真实原文”，尚无 relation/citation_valid，不与 Claim/Finding 关联。

## Agent Integration Note

proposed_by: Literal["human"] = "human" 是预留的版本化扩展点（DB 已有列）：未来 Agent pipeline 只能通过同一 resolve_span 验证门提交标注、同样由服务端派生 material_id/span，不得绕过 quote 校验；到来时扩展该枚举并保持 ApiError 机器可读码不变。当前不实现任何 Agent 生成逻辑。

API 返回 RunReport 内联 blocks 足够支持 MVP Drawer，不创建复杂检索 API。分页和大文件优化等有真实负载再加。

## 生成与验收

仓库根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -X utf8 scripts/export_contracts.py
npm.cmd --prefix frontend run contracts
.\backend\.venv\Scripts\python.exe -X utf8 scripts/check_contracts.py
```

fixtures 是人工写定的契约示例，非解析产物、非真实 AIC 结果。D1 扩展完整三幕 mock，不实现生产 diff。
