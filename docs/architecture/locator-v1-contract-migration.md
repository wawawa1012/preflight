# Locator v1：契约与迁移增量（checkpoint）

状态：定向 checkpoint（供 Codex review）；本文是本次施工的契约与迁移说明，实现增量随后提交。
范围：Locator 完整持久化、统一 SourceRef 验证、真实 span、下行定位适配、TXT/DOCX 接入边界。
不在范围：rebind history、DB 优化、persisted Finding、Composite Evidence、Assessment、OCR、agent framework。

## 1. 来源身份与定位协议（冻结）

1. 旧 Locator 字段保持原义：`kind ∈ {page, slide, paragraph, line}` 时 `index` 仍是原 1 基位置，`end_index`、`block_index` 语义不变。
2. Markdown / TXT：`kind="line"`，`index` 是原文件真实行号（1 基）；空行不生成 Block 但计入 `line_count`；不做行号伪造。
3. DOCX 正文段落：`kind="paragraph"`，`index` 是正文段落序号（1 基）。
4. DOCX 普通表格单元格：新增 `kind="table_cell"`：
   - `index` = 1 基 table 序号（该表在正文中的出现顺序）；
   - `row_index`、`cell_index` = 1 基行/列（单元格）结构序号；
   - `paragraph_index` = 1 基「单元格内段落」序号；
   - `block_index` 保留既有含义（同一来源单位内的块分组序号；行/段落为 1，不承载表格结构）。
   - 非表格 Block 的 `row_index` / `cell_index` / `paragraph_index` 一律 `null`。
5. 正文顺序由 `Block.ordinal` 表示（B2 `body_ordinal`），排序、下钻、prompt 都不得用 `line_number` 排序。
6. 非行格式的 `line_number` / `line_count` 必须为 `null`，不得填 0 或伪造成行号。历史 Markdown wire 值不变。

## 2. SourceRef 统一验证

`SourceRef`：`material_id`、`block_id`、`start`、`end`、`quote`（span 为 Unicode code point 半开区间）。

服务端规则（`evidence.resolve_source_ref`，HTTP / 下游共用同一实现）：

1. 位置权威是服务端：Locator 由服务端从 Block 解析；客户端/模型只能提交 `block_id` + `quote`（+ 可选精确 `start`/`end`）。
2. 材料归属：`block_id` 必须属于目标 `material_id`，否则 404 `block_not_found`（HTTP 路径不泄露跨材料 block 的存在性）。
3. quote-only（旧请求）：保留第一次 occurrence 匹配的兼容行为；未命中 400 `quote_not_found`。
4. 显式 span：`start`/`end` 必须同时提供；`0 <= start < end <= len(text)` 且 `text[start:end] == quote` 逐字复验。复验失败 400 `span_mismatch`，**绝不静默退回第一次匹配**。重复文本允许用显式 span 选择第二次及以后的 occurrence。
5. 显式 span 指向的位置服务端照实保存；读取时必须仍满足 `text[start:end] == quote`（Block 文本不可变，故失效即数据损坏，读取路径报 `span_mismatch`）。
6. 旧已确认 annotation / link / binding / revision 不改变位置与身份：迁移只回填 Locator 字段，不改 `start`/`end`/`quote`/ID。

## 3. 契约增量（contracts.py）

新增：

- `Locator`：新增可选 `row_index` / `cell_index` / `paragraph_index`；`kind` 增加 `table_cell`。旧请求/响应字段名与含义不变。
- `SourceRef`：material_id、block_id、start、end、quote；进入 `ContractBundle`，供文档与下游引用。
- `SourcePreview`：通用预览响应（filename、format、size_bytes、sha256、`line_count: int|null`、`parser_version`、blocks）；保留旧 `MarkdownPreview` 与 `POST /api/v1/preview/markdown` 不动。
- `SavedMaterial`：新增 `format`（`md|txt|docx`）、`parser_version: str|null`；`line_count` 变为 `int|null`（旧 md 值不变，docx 为 null）。
- `MaterialSummary`：新增 `format`（列表不返回 blocks）。
- `EditableSource.format`：由 `"md"` 扩为 `"md"|"txt"`；DOCX 不提供 editable-source（明确拒绝）。

字段语义变化（非新增）：

- `DetectedStatement.line_number` / `ConsistencyCitation.line_number` / `CoachSource.line_number` / `MaterialPreflightCitation.line_number`：`int` → `int|null`（非行来源为 null），并新增 `locator: Locator`。
- `GrillQuestion`：新增程序生成的 `locator: Locator`（quote/block/start/end 不变）。
- `EvidenceAnnotationCreate` / `CoachSourceRef`：新增可选 `start`/`end`，用于精确 occurrence；两者必须同时出现（否则 400 `invalid_request`）。

兼容原则：Markdown/TXT 的值与旧 wire 完全一致；新增字段只增不改；`line_number` 仅在非行来源为 null。

## 4. 持久化与迁移（storage.py）

新列：

- `materials`：`format TEXT NOT NULL DEFAULT 'md'`、`parser_version TEXT NULL`、`source_bytes BLOB NULL`；`line_count` 允许 NULL（DOCX）。
- `blocks`：`kind TEXT NOT NULL`、`locator_index INTEGER NOT NULL`（原 `line_number` 改名；`index` 是 SQLite 保留字，列名用 `locator_index`，契约字段仍是 `index`）、`end_index INTEGER NULL`、`row_index/cell_index/paragraph_index INTEGER NULL`、`block_index INTEGER NOT NULL`（保留）。
- `source_bytes`：新上传原文件字节与 material/blocks 同一事务写入；历史 Markdown 缺失原始字节保持 NULL（不伪造）；旧 editable-source 继续按已承诺的 LF/空行规则从 blocks 重建。

迁移：

- 版本号用 `PRAGMA user_version`（本次 `SCHEMA_VERSION = 1`），`schema_migrations` 不需要；版本单调、可重复执行（已到版本即 no-op）。
- legacy（user_version=0 且存在旧 `blocks.line_number`）在同一事务中重建 `blocks`/`materials`：`CREATE new → INSERT SELECT（line_number→index、kind='line'、format='md'、parser_version=NULL、source_bytes=NULL）→ DROP old → RENAME`；Block ID、material ID、annotation span、link、revision、binding 全部原样保留。
- FK 处理：重建在 `PRAGMA foreign_keys=OFF` 下进行（该 pragma 不能在事务内切换），事务提交前执行 `PRAGMA foreign_key_check`，有违规即回滚；提交后再恢复 `foreign_keys=ON`。子表只引用 `blocks(id)`/`materials(id)`，ID 不变故引用不悬空。
- 失败回滚：重建 + `user_version` 更新在同一事务；任一步失败由 `with connection` 整体 rollback，旧表与旧版本号原样保留，不留半迁移。目标表名先建临时名、成功后才 RENAME，DROP 也只针对旧表。
- 全新库：直接按新 schema 建表并写版本号，不走重建路径。

## 5. 解析接入边界（B2 接口）

- B2 交付纯 `SourceNode`（不依赖公共 contracts）：`kind`、`text`、`body_ordinal` 与结构坐标（`line_index` / `paragraph_index` / `table_index`+`row_index`+`cell_index`+`cell_paragraph_index`）。
- 实际消费接口（B2 `codex/next-parsers`，提交 8a0cacc/0eb2183）：`app.txt_adapter.parse_txt(data) -> ParsedSource`、`app.docx_adapter.parse_docx(data) -> ParsedSource`；`ParsedSource(format/parser_version/nodes/line_count)`，纯函数、不导入 contracts/storage、不做 IO。本 Pod 不改 B2 文件。
- 由本 Pod 转换：`body_ordinal` 零基连续直接作为 `Block.ordinal`（不重排、不重新编号），`line_index→index`、`paragraph_index→index`、`table_index/row_index/cell_index/cell_paragraph_index→index/row_index/cell_index/paragraph_index`；坐标缺失或非连续即 400 `invalid_source_node`。DOCX 真实全链已用 B2 合成 fixtures 打通（preview→save→Evidence annotation/link）。
- 旧 `POST /api/v1/preview/markdown` 入口保留；`POST /api/v1/preview` 按扩展名通用预览；`POST /api/v1/materials` 按格式解析后原子保存。
- TXT：真实逐行定位、完整 revision loop（LF 归一化 + 空行回填，格式保持 `txt`）。
- DOCX：首版上传 → 保存 → Evidence → Reader；`editable-source` 与 revision 明确 400 `format_not_editable`（不承诺原格式编辑）。
- 单块超 prompt 上限：`prompt_planner` 现有行为（带 block_id 抛 `PromptTooLarge`）保持：明确失败、不截断。
- 接口问题（若 B2 实际交付与上述不符）：只提出接口问题，不改 B2 文件；解析器拒绝的 DOCX 结构原码透出，不静默展开、不伪造 Block。

## 6. 错误语义（新增/沿用）

| 场景 | HTTP | code |
| --- | --- | --- |
| 显式 span 与 quote/边界不符 | 400 | `span_mismatch` |
| quote-only 未命中原文 | 400 | `quote_not_found` |
| start/end 只给一个 | 400 | `invalid_request` |
| block 不属于该材料 / 不存在 | 404 | `block_not_found` |
| DOCX editable-source 或 revision | 400 | `format_not_editable` |
| 不支持的扩展名 | 400 | `invalid_extension` |
| 解析拒绝（B2 parser） | 400 | `invalid_encoding` / `invalid_zip` / `invalid_xml` / `invalid_docx` / `unsupported_structure` / `archive_too_large` |
| SourceNode 坐标缺失/body_ordinal 非连续 | 400 | `invalid_source_node` |

## 7. 验收清单（定向）

- 旧库迁移、重复迁移、失败回滚、`foreign_key_check` 完整性。
- 历史 Markdown 引用、parent/child revision、binding 不回归。
- 非行 locator 保存→读取不变；`line_number` 不伪造（null）。
- 中文及非 BMP（emoji/增补平面）code-point span 正确。
- 同块第二次 quote 可精确选择并复验；错材料/越界/quote mismatch 被拒绝。
- 所有直接消费行号的下游路径完成适配（Statement/Consistency/citation/report/Grill/Coach/Repair/prompt）。
- TXT revision 保留空行；DOCX 无原格式编辑承诺。
- schema.json / generated TS / fixtures / docs 与实际 API 同步。
- deterministic/mock/live 分别记录；live 未跑必须写明。
