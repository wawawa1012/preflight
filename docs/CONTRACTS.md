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
- `resolved` 只表示「修改后本次规则未再检出同一 finding identity」，不代表事实已正确、风险已解决或修改一定有效；POST /api/v1/diffs 返回的 FindingSetDiffResponse.note 固定给出该口径。
- FindingSetDiffRequest / FindingSetDiffResponse 与 Run-based VersionDiff 是三个独立 contract identity：前者比较两份材料的同材料数值 Finding 指纹集合，后者是 Phase 0 冻结、尚未实现的 Run 版本差；在 ContractBundle 与生成 TS 中分别导出，不得混用。

## API 冻结边界

已实现：GET /api/v1/health、GET /api/v1/report（Iteration 1 只读 mock）、POST /api/v1/preview/markdown（临时预览）、POST /api/v1/materials 与 GET /api/v1/materials、/api/v1/materials/{id}、/api/v1/materials/recent（Iteration 2B 持久化）、DELETE /api/v1/materials/{id}（行内删除确认 + FK 级联清理）、POST /api/v1/evidence-annotations 与 GET /api/v1/materials/{id}/evidence-annotations、/api/v1/evidence-annotations/{id}（Iteration 3 证据层）、GET /api/v1/rubrics 与材料绑定 / 人工关联（Iteration 4）、单 criterion Agent 提案（Iteration 5）、材料级只读预审装配（Iteration 6）、关键陈述扫描（Iteration 7）、同材料数值一致性（Iteration 8）。以下业务接口是后续目标，不能当作可用服务。

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| GET /api/v1/health | 无 | {status: "ok", contract_version: "0.1.0"}（已实现） |
| GET /api/v1/report | 无 | RunReport（已实现，只读 mock） |
| POST /api/v1/preview/markdown | multipart：file（仅 .md，UTF-8，≤1 MiB） | MarkdownPreview（已实现，临时预览，不保存；错误返回 400 + ApiError） |
| POST /api/v1/materials | multipart：file（同上，服务端重新解析） | SavedMaterial，201（已实现，原子写入 SQLite） |
| GET /api/v1/materials | 无 | MaterialSummary[]（已实现，摘要列表，按 created_at 倒序，不含 blocks） |
| GET /api/v1/materials/{id} | 无 | SavedMaterial；未知 ID 返回 404 + ApiError |
| GET /api/v1/materials/recent | 无 | SavedMaterial；无记录返回 404 + ApiError（工程能力，当前 UI 不消费） |
| DELETE /api/v1/materials/{id} | 无 | 204；未知 ID 返回 404 + ApiError；blocks、证据标注、绑定、关联、提案由 FK 级联删除 |
| POST /api/v1/evidence-annotations | {block_id, quote, note?} | EvidenceAnnotation，201；quote 未命中 400 quote_not_found、未知 block 404 block_not_found、缺字段 400 invalid_request |
| GET /api/v1/materials/{id}/evidence-annotations | 无 | EvidenceAnnotation[]（未知材料 404 material_not_found） |
| GET /api/v1/evidence-annotations/{id} | 无 | EvidenceAnnotation（未知 404 annotation_not_found） |
| DELETE /api/v1/materials/{id}/evidence-annotations/{annotation_id} | 无 | 204；不存在或跨材料 404 annotation_not_found；其关联由 FK 级联清除 |
| GET /api/v1/rubrics | 无 | Rubric[]（只读文件仓 data/rubrics/*.json；可为空） |
| GET /api/v1/materials/{id}/rubric-binding | 无 | RubricBinding 或 null；未知材料 404 material_not_found |
| PUT /api/v1/materials/{id}/rubric-binding | {rubric_id, rubric_revision} | 201 新建 / 200 幂等返回已有；未知 rubric 404 rubric_not_found；换绑 409 binding_conflict |
| GET /api/v1/materials/{id}/criterion-evidence-links | 无 | CriterionEvidenceLink[]；未知材料 404 material_not_found |
| POST /api/v1/materials/{id}/criterion-evidence-links | {annotation_id, criterion_id, rationale} | 201；annotation 不存在/跨材料 404 annotation_not_found；未知 criterion 404 criterion_not_found；未绑定 409 rubric_not_bound；重复 409 duplicate_link；span 复验失败 400 span_mismatch；空白 rationale 400 invalid_request |
| DELETE /api/v1/materials/{id}/criterion-evidence-links/{link_id} | 无 | 204；不存在 404 link_not_found |
| POST /api/v1/materials/{id}/agent-proposals | {criterion_id} | AgentProposal，201；404 material/criterion、409 rubric_not_bound、400 material_too_large、503 llm_unconfigured、502 llm_unavailable、504 llm_timeout、502 llm_invalid_response |
| GET /api/v1/materials/{id}/agent-proposals?criterion_id= | 无 | AgentProposal[]（新到旧；失败提案 status=failed 也在列表） |
| GET /api/v1/agent-proposals/{id} | 无 | AgentProposal；未知 404 proposal_not_found |
| POST /api/v1/materials/{id}/proposal-candidates/{cid}/accept | 无 | ProposalAcceptance，201；未知 404 candidate_not_found；未过验证门 400 invalid_candidate；已裁决 409 candidate_already_reviewed；语义重复 409 duplicate_link；span 失效 400 span_mismatch |
| POST /api/v1/materials/{id}/proposal-candidates/{cid}/reject | {reason?} | ProposalCandidate，200；未知 404 candidate_not_found；已裁决 409 candidate_already_reviewed |
| GET /api/v1/preflight-summaries | 无 | MaterialPreflightSummary[]（只读装配；未绑定材料 bound=false） |
| GET /api/v1/materials/{id}/preflight-report | 无 | MaterialPreflightReport；未知材料 404 material_not_found；未绑定 409 rubric_not_bound |
| GET /api/v1/materials/{id}/statement-signals | 无 | DetectedStatement[]（Iteration 7 确定性扫描；未知材料 404 material_not_found；空数组合法） |
| GET /api/v1/materials/{id}/consistency-findings | 无 | ConsistencyFinding[]（Iteration 8 同材料数值对照；未知材料 404 material_not_found；空数组合法） |
| POST /api/v1/diffs | FindingSetDiffRequest（修改前后两个材料 id） | FindingSetDiffResponse（resolved/unchanged/new + note）；同 id 400 same_material；缺一 404 material_not_found；不落库 |
| POST /api/v1/rubrics/draft | {text, source_type?, source_name?} | RubricDraft（模型整理的要求草稿；source_type=rubric_json 时确定性转写、不调模型；未配置 503 llm_unconfigured；坏响应 502 llm_invalid_response；结构化 JSON 非法 400 invalid_rubric_source） |
| POST /api/v1/rubrics | RubricPublish（criteria + confirmed=true） | Rubric，201；id/order/空白校验失败 400 invalid_rubric；plain_text/markdown 来源的评分语义 provenance 复验失败同样 400；每次发布生成全新 identity，绝不覆盖旧文件 |
| DELETE /api/v1/reviews/{id} | 无 | 204；未知 404 review_not_found；只删 Review 与成员关系，不删 Material、不删材料内容与其他历史 |
| PUT /api/v1/reviews/{id}/materials/{material_id} | {label?, position?} | ReviewMaterialEntry，201 新建 / 200 更新；首次加入时未绑定材料在同一事务内完成首次 binding（绑定本 Review 的标准版本）；已绑定不同版本 409 binding_conflict（不自动换绑、不覆盖历史绑定） |
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
MaterialSummary 是列表摘要（id、filename、created_at、block_count），不包含 blocks；文件类型由 filename 后缀展示。DELETE /api/v1/materials/{id} 单事务删除材料本体：blocks、evidence_annotations、material_rubric_bindings、criterion_evidence_links、agent_proposals、proposal_candidates 由 FK CASCADE 清理；recent_material 指针没有 CASCADE，删除前先改指到仍存在的最近材料（没有则清空），所以它不是“最近材料”悬空来源。已删除的材料不再出现在 GET /api/v1/materials、GET /api/v1/preflight-summaries 与任何按 id 的读取路径上。
EvidenceAnnotation 是 Iteration 3 最小证据层：source 复用冻结 Span（block_id/start/end/quote），服务端用纯函数 resolve_span(text, quote) 校验后才能写入（精确子串、Unicode 代码点索引、重复取第一次出现）；未命中返回 400 quote_not_found，同一事务回滚，库中不存在无效引用。material_id 由服务端从 blocks 行派生，不接受客户端提交；evidence_annotations 对 materials/blocks 双外键（FK CASCADE）。本迭代只表示“引用了真实原文”，尚无 relation/citation_valid，不与 Claim/Finding 关联。
Rubric 是只读标准仓：data/rubrics/*.json 在启动时全量校验，非法文件或重复 (rubric_id, revision) 直接拒绝启动（fail-fast，空目录合法）；Criterion ID 固定写在文件里；新版本 = 新文件，旧文件永不改动。scripts/validate_rubrics.py 复用同一加载器做预检。当前不内置任何官方评分标准。
RubricBinding 每份材料最多一条、不换绑（错误换绑 409 binding_conflict）。
CriterionEvidenceLink 是 adjudication 层：只表示“人判断这条引用与某项评分要求相关”，可增删，rationale 必填；不表示证据充分、不产生 Supported/coverage/readiness，不与 Claim/Finding 关联。material_id 与 rubric 版本由服务端派生（来自 annotation 与 binding），span 在写入前复验（store 内 block_text[start:end] == quote），失效即 400 span_mismatch。
AgentProposal / ProposalCandidate 是单 criterion 预检层：LLM 只提出候选（block_id + quote + rationale + risk_note），服务端用 resolve_span 做验证门（block 必须属于该材料、quote 必须命中原文），标记 passed / invalid + 机器码；invalid 候选不能 accept。accept 由人触发，单事务物化 annotation 与 link（proposed_by="agent"）并回写候选 created ids；reject 记录可选原因。提案只是“待裁决候选”，不是结论，不产生 Supported/coverage。失败（未配置/超时/上游错误/非法响应/prompt 超限）同样落库 status=failed 并返回对应错误码；prompt 超限绝不静默截断。proposed_by 枚举扩为 ["human","agent"]；EvidenceAnnotationCreate 不再接受 proposed_by（HTTP 路径固定 "human"，accept 物化固定 "agent"）。
MaterialPreflightReport / MaterialPreflightSummary 是 Iteration 6 的只读装配：从现有 material_rubric_bindings、evidence_annotations、criterion_evidence_links 计算每条 criterion 的已确认关联；零引用行携带 missing 范围句（searched_filename + searched_block_count + explanation，措辞必须是「当前范围尚未发现引用」且说明范围）。它不是 Run、不是 CriterionAssessment、不填充 supported/coverage、不写库；未绑定返回 409 rubric_not_bound，未知材料 404 material_not_found。blocks 仅内联快照供 Drawer 使用，不新建检索 API。字段名 verified_citation_count 为历史遗留，含义是“人已确认关联数”，不是支持判定。
DetectedStatement 是 Iteration 7 的关键陈述信号：确定性纯函数 inspect_statements(blocks) 现算（零 IO、不调 LLM、不写库）；quote == text[start:end]（Unicode code point 索引），signal ∈ numeric|percentage|comparative|absolute；同段重叠匹配按 比例 > 绝对化 > 比较 > 数字 去重，全局上限 20。数字仅在带单位或带上下文（达到/准确/延迟等）时才计入；它只标出「值得核对的句子」，不判真假、不产生 Finding，也不代表风险成立。
ConsistencyFinding / ConsistencyCitation 是 Iteration 8 的同材料数值一致性：输入是 I7 的 DetectedStatement[]，纯函数 find_numeric_findings(statements, blocks) 现算（零 IO、不调 LLM、不落库，不新增表；blocks 只用于复验 span 与读取数值前后的上下文）。宁漏勿错：只有同一度量词 + 同一单位 + 不同数值才标 kind=numeric_inconsistency；同一度量词但单位写法不一致，或没有共同度量词、只有同一量纲单位 + 不同数值时降级为 kind=needs_review；其余不报（同值、单条无对照、不同度量词、span 复验不过、非量纲单位如「个/条/次」）。度量词取数值前连接词剥离后的汉字串（「准确率降低到 90%」→「准确率」），长度 ≥ 3 的写法按后缀归并（「系统准确率」→「准确率」），长度 2 的词不归并，避免把「模型延迟」与「系统延迟」误配。每条 citation 都可在 Block 原文复验 quote == text[start:end]，供报告页点回 Drawer；explanation 自带范围（扫过多少 Block、多少条关键陈述），searched_block_count / searched_statement_count / statement_scan_limit 同步给出（statement_scan_limit 是每份材料的关键陈述提取上限：单材料 Finding 的 count ≤ limit；跨材料 Finding 的 count 是两侧之和，可能大于 limit。两者相等只表示达到上限、可能还有未提取信号，绝不表示已检查全文）。它不判断外部真实性、不做裁决、不给分。
CrossCompare（POST /api/v1/comparisons）在同一规则上做 unit-aware 候选形成（cross 路径以 (数值, 单位) 判重，裸数值去重不得吞掉单位差异）：先按材料拆出各自的归一化 (数值, 单位) 集合，两侧集合完全相同（顺序不同、95 vs 95.0、百分比写法等价、单位别名）时不生成跨材料数值差异 Finding；部分重合或单位不可安全比较（如 95 ms vs 95 秒，裸数值相同）降级 needs_review；只有同一度量词、可比较单位、双方数值集合无交集才报 numeric_inconsistency。单材料 finder 保持历史语义（同数值不同单位不报），同一材料自身的 consistency-findings 不受影响。
RubricDraft / RubricPublish / CriterionDraft（Criteria Builder）：普通用户粘贴要求原文（plain_text / markdown）或结构化 Rubric JSON（rubric_json），得到可编辑草稿；草稿不是正式标准。CriterionDraft 在 Criterion 之上增加 order（草稿期排序，publish 校验 id/order 唯一并按 order 排序）。Criterion 的 max_score / weight / rubric_levels / scoring_anchors 与 Rubric 的 aggregation_rule 表示源标准真实写出的评分语义：缺失一律 null。plain_text / markdown 来源的评分语义必须带局部 provenance——Criterion.scoring_sources 列出逐字原文片段（Rubric.aggregation_rule_source 同义），程序用 resolve_span 复验片段真实存在，并要求 max_score/weight/档位 score 以独立数字 token 出现在片段中（20 不得命中 120），档位 label 与 description、scoring_anchors 也必须能在片段中逐字定位；支持不了的字段草稿阶段丢弃，publish 阶段拒绝（confirmed=true 不能豁免，人工确认不能洗白 imported source 里虚构的评分规则）。rubric_json 由代码确定性转写（结构化原文即权威，评分语义原样保留）；manual 来源的用户自撰评分规则合法，不要求存在于外部文档。模型不可用时用户仍可手工填 criteria 直接发布。每次 publish 生成新的 (rubric_id, revision=1) 文件并先写临时文件再原子改名，旧文件永不改写；Rubric 保留 source_text / source_type / source_name / aggregation_rule_source / model_assisted 溯源；已建立 Review/绑定的 rubric/revision 不变。
Review 领域：PATCH /api/v1/reviews/{id} 只改 title（ReviewUpdate extra=forbid）；DELETE /api/v1/reviews/{id} 只删 Review 本体与 review_materials（FK CASCADE），绝不删除 Material 或材料内容；PUT 成员首次加入时完成未绑定材料的首次 binding——普通用户不需要理解 binding，Wizard 只表达「这些材料 + 这个标准」。explicit binding 与 auto first-binding 共用同一 connection-aware guard：材料所属全部 Review 的标准版本必须与将绑定的版本一致；历史遗留的「已属于 Review A、却未绑定」材料在加入不同标准的 Review B 时 409 binding_conflict，整事务回滚（保持未绑定、A membership 不变、B membership 不创建）。已绑定相同版本幂等允许；已绑定其他版本 409，不自动换绑。

## Agent Integration Note

Agent 接入点收敛为 Proposal 层（Iteration 5）：LLM 只能提交候选（AgentProposal / ProposalCandidate），不得直接写 evidence_annotations 或 criterion_evidence_links；物化只能由人通过 accept 触发，且必须先通过 resolve_span 验证门与语义查重。proposed_by 枚举已扩为 ["human","agent"]，DB 已有列；未来扩展（多模型、重跑、更多 criterion）在 Proposal 层进行，不得绕过验证门与人工裁决。provider/model/prompt_version 与失败原因全部落库审计；失败也保留提案（status=failed）。

API 返回 RunReport 内联 blocks 足够支持 MVP Drawer，不创建复杂检索 API。分页和大文件优化等有真实负载再加。

## 生成与验收

仓库根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -X utf8 scripts/export_contracts.py
npm.cmd --prefix frontend run contracts
.\backend\.venv\Scripts\python.exe -X utf8 scripts/check_contracts.py
```

fixtures 是人工写定的契约示例，非解析产物、非真实 AIC 结果。D1 扩展完整三幕 mock，不实现生产 diff。
