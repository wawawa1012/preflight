# ADR：Locator 端口与多格式解析最小扩展

- 状态：Proposed（只读思考产物；本文件不实施任何代码改动）
- 分支：think-locator · 基准：main @ 72ff3b9
- 依据：docs/ARCHITECTURE.md「Deferred hardening：Format-specific Locator」、backend/app/contracts.py（Locator/Block/Span）、backend/app/markdown_preview.py、backend/app/storage.py、frontend/src/components/EvidenceDrawer.vue

## 一、端口三句话（Locator 的对外接口）

1. Locator 是 Block 在原始文件中的唯一位置事实，只由解析器生成、由代码维护；LLM 只允许引用既有 block_id 和原文 quote，永不生成或改写 locator（ARCHITECTURE.md 冻结）。
2. Locator 的端口就是四个字段：`kind`（容器类型）+ `index`（从 1 开始的容器号）+ `end_index`（可选，容器区间的末号，首刀恒 null）+ `block_index`（同容器内第几块，从 1 开始）；UI 与 DTO 只读这四个字段，不解析字符串。
3. 新增格式只扩展 `kind` 枚举与解析器规则，不新增第二套位置字段；「行号」只属于 `kind="line"`，不得出现在非 line 格式的用户文案里。

冻结前提（本轮不再讨论）：Block 不永远是行；句一律用 Span（code point 半开区间）表达；文件 MB ≠ prompt 字符；LLM 不造 locator。

## 二、格式 × 解析单元表

| 格式 | Block 单元（解析器决定） | Locator.kind | index | end_index（首刀） | block_index | 本赛季 |
| --- | --- | --- | --- | --- | --- | --- |
| md | 一个非空行（现状） | `line` | 原始行号（1 起） | 恒 null | 恒 1 | ✅ 已实现 |
| pptx | slide 内一个文本段（按 shape 遍历出来的段落） | `slide` | 幻灯片号（1 起） | null（跨页对象以后再用） | 同 slide 内段序（1 起） | ❌ 本周冻结不解析 |
| pdf | page 内一个文本段（版面块） | `page` | 页码（1 起） | null | 页内段序（1 起） | ❌ 本周冻结不解析 |
| docx | 一个段落 | `paragraph` | 段落号（1 起） | null（将来 run 级再定义） | 重复段落消歧用（1 起） | ❌ 未排期 |
| xlsx | 未设计 | 未定 | 未定 | 未定 | 未定 | 非本赛季，不做 |

`end_index` 的既定用途是「容器区间」（如跨页段 起页..末页）；首刀一律 null，不提前发明用法。

## 三、PDF 页-段-句：只选一个 —— Block=段 + 句=Span（不扩 Locator）

**决策：Block = page 内的一个文本段；句不建结构，用 Span 表达。**

- 定位链：`kind="page"` + `index=页码` + `block_index=段序` 已经够「点回原文」；句级高亮由 Span 的 `[start, end)` 提供，Drawer 已经按 Span 渲染（EvidenceDrawer 用 Array.from 对齐 code point）。
- 解析规则（未来实施时）：PyMuPDF 版面块 → 段；段内硬换行折叠为空格后写入 Block.text（Block.text 仍是唯一事实源）；Span 索引基于折叠后的段文本；不在 Block 层切句。
- 被拒方案「扩 Locator（新增 sentence/paragraph 字段或拆新 kind）」：契约、JSON Schema、TS 生成物、三个 line_number DTO 全要跟动，收益只是把 Span 已有的能力换个位置存；违反开闭与最小改动。
- 已知代价：多栏/表格的段序会偏离人类阅读顺序；首刀接受，并在 Drawer 显示「第 N 页 · 第 M 段」让偏差可见。

## 四、SQLite 最小加法（不改表语义、不新增表）

现状：`blocks(line_number INTEGER NOT NULL, block_index INTEGER NOT NULL, ...)`；`materials.line_count`；写入见 storage.py:231 一带。

最小迁移（真正接第二种格式时才执行，本 ADR 不执行）：

```sql
ALTER TABLE blocks ADD COLUMN locator_kind TEXT NOT NULL DEFAULT 'line';
ALTER TABLE blocks ADD COLUMN locator_end_index INTEGER;
```

- `index` 复用既有 `line_number` 列：`kind="line"` 时它就是行号；不做 rename（rename 会冲击现有查询、fixtures 与检查脚本），把列名当历史遗留，在 contracts 注释里点名。
- `end_index` 现在恒 null，先给列、不给语义；等跨页对象出现再写。
- `materials.line_count` 对非 line 格式无意义：首刀按「Block 数」占位写入，摘要文案继续显示「N 个 Block」，不改 DTO。
- 明确不做：新表、新索引、FTS5、批插优化、WAL；全部留给有真实负载时另开计划。

## 五、50MB PPT 从哪一段先炸（按发生顺序）

1. **上传门（现状即炸点）**：`markdown_preview.MAX_BYTES = 1 MiB`，且只接受 `.md`；50MB `.pptx` 在 `/preview` 直接 400 `file_too_large` / `invalid_extension`。第一炸点、也是目前唯一必须存在的炸点。
2. **保存路径**：预览 + 保存各上传一次原文件（trust boundary 现状）；单事务逐条 INSERT；`GET /materials/{id}` 整份 blocks 内联 JSON。放开大小而不做这些改造，会先于解析器崩。
3. **prompt 字符上限**：`MAX_PROMPT_CHARS = 24000`（字符，不是字节，也不是 MB）。50MB 文本远超上限 → PromptTooLarge 明确失败；这正是「文件 MB ≠ prompt 字符」的体现。
4. **解析器自身**：python-pptx 解包与媒体内存占用，反而排在最后——因为前面已经拦住。

结论：PPT 支持若只放开上传门，会得到「能上传、预检必炸」的假功能；上传门、保存事务/内联响应、prompt 选块策略必须同刀处理。本 ADR 全部不做。

## 六、现有 line_number DTO 点名（第二种格式落地时必须迁移）

| 位置 | 字段 | 说明 |
| --- | --- | --- |
| backend/app/contracts.py:331 `MaterialPreflightCitation` | `line_number` | 报告引用行 |
| backend/app/contracts.py:383 `DetectedStatement` | `line_number` | 关键陈述行 |
| backend/app/contracts.py:394 `ConsistencyCitation` | `line_number` | I8 一致性引用行 |
| frontend/src/types/contracts.ts | `LineNumber` / `LineNumber1` / `LineNumber2` | 上述三者的生成别名 |
| frontend/src/views/MaterialReportView.vue:26,96-97 | `highlight.line_number` | 打开 Drawer 的入参 |
| frontend/src/components/EvidenceDrawer.vue:6,41 | `DrawerHighlight.line_number` + 标题「原文 · 第 N 行」 | 用户可见文案 |

口径：这些字段只代表「当前材料的 line locator 索引」。接入第二种格式时必须改为 `locator_index` + 携带 `kind`（或整段传 Locator），并让 Drawer 标题按 kind 切换（页/段/行）；不许对 pptx 显示「第 N 行」。本 ADR 不修改任何一处。

## 七、不做清单

- 本周不解析 PPT/PDF，不安装 python-pptx / PyMuPDF；不碰 xlsx。
- 不扩 Locator 字段与枚举（本 ADR 已选 Block=段 + 句=Span）。
- 不建 FTS5/BM25；不建 Claim 表 / Review 表；不新增任何表。
- 不改 Block 切分规则、不引入 multi-span；不改 Markdown line 语义与现有端点。
- 不做 50MB 上传、分片、后台队列、解析缓存。
- 不让 LLM 参与 locator 生成；不迁移/重命名 `line_number`（留给第二种格式落地时一次性做）。
- 本分支只提交本文件。

## 八、下一刀准入三问（以 PPTX 为首个格式扩展为例）

1. **屏幕入口**：`/materials/new` 上传 `.pptx` 后，详情/报告 Block 列表按 slide 分组，Drawer 标题「原文 · 第 N 页 · 第 M 段」。
2. **验收标准（可运行）**：合成 pptx fixture 的解析器单测（slide 数、段落实体、`text[start:end] == quote`）+ `export_contracts` / `check_contracts` 通过（`kind="slide"` 过现有 Schema）+ 上传→保存→预检 e2e 脚本；50MB 仍稳定返回 400 拒绝。
3. **demo 秒数**：3–5 分钟 demo 中约 20 秒（上传 PPT → 定位 slide 段落 → Drawer 高亮 → 触发一条预检）。

前置条件：先执行本 ADR 第四节 SQLite 最小加法与第六节 DTO 迁移；任一项答不上或前置未过，回退到 Controlled Breadth 重新切片，不得直接开解析器。
