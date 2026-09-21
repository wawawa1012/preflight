# Locator v1 消费说明（面向 Kimi / F1）

来源：分支 `codex/next-locator`，base `5f12236`。契约唯一源仍是 `backend/app/contracts.py`；
`schema.json` / `frontend/src/types/contracts.ts` / `docs/CONTRACTS.md` 已同步重导出。
Markdown/TXT 的旧 wire 值与旧展示不变；新增字段只增不改，非行来源的 `line_number` 变为可空。

## 1. 精确字段差异（generated TS）

| 类型 | 变化 |
| --- | --- |
| `Locator` | `kind` 增加 `"table_cell"`；新增可选 `row_index` / `cell_index` / `paragraph_index`（`number \| null`，默认省略）；旧字段含义不变 |
| `SourcePreview`（新） | `document_id, filename, format("md"\|"txt"\|"docx"), size_bytes, sha256, line_count?: number\|null, parser_version?: string\|null, blocks: Block[]` |
| `SourceRef`（新） | `material_id, block_id, start, end, quote`（半开 code point span，`end > start`） |
| `SavedMaterial` | 新增 `format`（必填）与 `parser_version?: string\|null`；`line_count` 变为可空 |
| `MaterialSummary` | 新增 `format`（必填） |
| `EvidenceAnnotationCreate` | 新增可选 `start` / `end`（必须同时提供；显式 span 精确选中 occurrence，失败 400 `span_mismatch`） |
| `DetectedStatement` / `ConsistencyCitation` / `CoachSource` / `MaterialPreflightCitation` | 新增 `locator: Locator`；`line_number` 变为可空（`int \| null`） |
| `GrillQuestion` | 新增程序回填 `locator: Locator`（模型不能提供） |
| `CoachSourceRef` | 新增可选 `start` / `end`（必须同时提供） |
| `EditableSource` | `format` 由 `"md"` 扩为 `"md" \| "txt"` |

JSON Schema 侧：`Locator.kind.enum` 含 `table_cell`；`ConsistencyCitation.line_number.anyOf` 含 `null`；`ContractBundle` 新增 `source_preview` 与 `source_ref`。

## 2. 展示规则（必须遵守）

1. 位置一律以 `locator` 为准；`line_number` 为 `null` 时**不得**渲染成行号（也不能拿 `locator.index` 当行号）。
2. `kind="line"` → `第 {index} 行`（与历史一致）。
3. `kind="paragraph"` → `第 {index} 段`。
4. `kind="table_cell"` → `表格 {index} · 第 {row_index} 行 · 第 {cell_index} 列 · 第 {paragraph_index} 段`。
5. `kind="page" | "slide"` → 与历史一致。
6. TXT 与 MD 一样用真实行；DOCX 无 editable-source / revision（400 `format_not_editable`）。

## 3. 消费示例

```ts
function locatorText(loc: Locator): string {
  if (loc.kind === "line") return `第 ${loc.index} 行`
  if (loc.kind === "paragraph") return `第 ${loc.index} 段`
  if (loc.kind === "table_cell")
    return `表格 ${loc.index} · 第 ${loc.row_index} 行 · 第 ${loc.cell_index} 列 · 第 ${loc.paragraph_index} 段`
  if (loc.kind === "page") return `第 ${loc.index} 页`
  return `第 ${loc.index} 页`
}
// 引用渲染：citation.locator 有值就用 locatorText(citation.locator)，
// citation.line_number 仅在没有 locator 的旧快照上兜底，且为 null 时不显示。
```

新增/变化端点：

```jsonc
// POST /api/v1/preview  （multipart: file，.md/.txt/.docx，≤1 MiB）
// 200 SourcePreview；非支持后缀 400 invalid_extension；DOCX 暂 400 parser_unavailable
{ "document_id": "preview", "filename": "notes.txt", "format": "txt",
  "line_count": 3, "parser_version": "line-v1",
  "blocks": [{ "id": "preview-block-0", "ordinal": 0, "text": "第一行",
               "locator": { "kind": "line", "index": 1, "end_index": null, "block_index": 1 } }] }
```

```jsonc
// POST /api/v1/evidence-annotations —— 旧请求（quote-only，第一次 occurrence，兼容）
{ "block_id": "mat_x-blk-0", "quote": "重复片段", "note": "可选" }
// 新请求（显式 span 精确选第二次 occurrence；必须同时给 start/end）
{ "block_id": "mat_x-blk-0", "quote": "重复片段", "start": 6, "end": 10 }
// 400 span_mismatch：显式 span 与 quote/边界不符（不会静默退回第一次匹配）
// 400 quote_not_found：quote-only 未命中；400 invalid_request：start/end 只给一个
```

```jsonc
// GET /api/v1/materials/{id} —— DOCX（无行号，不伪造 line_count）
{ "id": "mat_x", "filename": "report.docx", "format": "docx",
  "parser_version": "b2-source-nodes-v1", "line_count": null, "blocks": [
    { "ordinal": 0, "text": "正文一", "locator": { "kind": "paragraph", "index": 1, "end_index": null, "block_index": 1 } },
    { "ordinal": 1, "text": "单元格", "locator": { "kind": "table_cell", "index": 2, "row_index": 3, "cell_index": 4,
      "paragraph_index": 5, "end_index": null, "block_index": 1 } } ] }
```

## 4. 本轮不动的 wire

- `POST /api/v1/preview/markdown` 与 `MarkdownPreview` 完全不变（仍只支持 `.md`）。
- MD/TXT 的 `line` locator、`line_number`、`line_count` 值与历史一致。
- 所有评分/一致性问题判定算法、Proposal 验证门、Review/binding invariant 未改；只改变定位字段与排序/展示来源。
- `CONTRACTS.md` 中 Locator 语义与错误码已更新，以其为准。

## 5. 未完成 / 待 B2

- DOCX 真实解析等待 B2 `app.source_adapters.read_source_nodes(filename, data)`；本轮只有 mock adapter 的确定性转换测试，未跑真实 DOCX 全链。
- 前端本轮只重新生成了 `frontend/src/types/contracts.ts`；页面按上表适配由 frontend pod 负责（未手工改任何消费者）。
