# Sprint 2 RC1 Contract Checkpoint — Response Coach v1 + Grill Preparation

2026-09-20 · backend-only · 状态：RC1（待 Backend QA）；frontend pod 可据此实现 adapter，不必等整个 backend 功能完成。

范围：A. Response Coach v1；B. Challenge/Grill 可行动准备数据；C. 最小 source-validation contract。
不包含：Action Inbox UI、progressive queue、Review IA、DOCX、Locator、Assessment、Finding persistence、任何持久化。

## 1. 端点总览

| 方法/路径 | 请求 | 响应 | 持久化 |
| --- | --- | --- | --- |
| POST /api/v1/grill | `GrillRequest` `{material_id}` | `GrillQuestion[]`（新增 `trigger`/`preparation`） | 无（session-only） |
| POST /api/v1/response-coach | `ResponseCoachRequest` | `ResponseCoachResponse` | 无（answer/feedback/会话历史都留在前端 session store） |

两个端点都不写库、不新增表；Coach 失败不影响已有 Question/Source/preparation（它们来自 `/grill`，与 Coach 是独立请求）。

## 2. Response Coach request

```json
{
  "material_id": "mat_...",
  "question": "95% 基于什么样本？",
  "user_answer": "我们在 240 份文档上做了测试，系统准确率达到 95%。",
  "source_refs": [{"block_id": "mat_...-blk-0", "quote": "95%"}],
  "review_id": "rev_... / null"
}
```

- `question` ≤ 300 字符；`user_answer` ≤ 4000 字符；两者不能为空白。
- `source_refs` ≤ 8 条，可选；每条必须能在该 material 的 Block 原文逐字复验，否则 400 `source_ref_mismatch`。
- `review_id` 可选。提供时服务端校验 Review 存在且 material 是成员，并只把 Review 标题 + rubric 标题 + criterion 标题（有界）放进 prompt；requirement 正文不进入 prompt。

## 3. Response Coach response

```json
{
  "material_id": "mat_...",
  "status": "coached | abstain | insufficient_context",
  "abstain_reason": null,
  "answered_aspects": ["回答了准确率数值"],
  "supported_claims": [{"text": "系统准确率达到 95%", "note": "来源直接给出 95%", "source_ids": ["s1"]}],
  "unsupported_claims": [{"text": "在 240 份文档上做了测试", "note": "材料未给出样本量与测试集", "source_ids": []}],
  "missing_conditions": ["样本量"],
  "follow_up_questions": ["如果被问样本量，准备怎么回答？"],
  "source_ids": ["s1"],
  "sources": [{"source_id": "s1", "block_id": "mat_...-blk-0", "line_number": 1, "quote": "95%", "start": 9, "end": 12, "basis": "关键陈述信号：percentage（未经真假判断）"}],
  "overall_note": "数值有来源，但测试条件仍需说明。"
}
```

语义与上限：

- 只评价 `user_answer` 已经写出的内容；不代写答案、不补充材料外事实、不给分、不评选「最佳回答」、不预测真实评委反应。
- `supported_claims[].source_ids` 只能来自本次服务端来源池；程序回填 `sources` 的 quote/block/坐标（模型不能提供坐标）。
- `unsupported_claims` 表示「当前提供的来源未能支持」，不是「现实世界为假」；`source_ids` 恒为 `[]`。
- 模型给出的 claim `text` 必须是 `user_answer` 的逐字片段，否则整条丢弃（不展示用户没说过的话）。
- 模型引用未知 source_id 的 supported claim 会降级到 `unsupported_claims`，`note` 为机器说明。
- 上限：answered_aspects 6、supported/unsupported claims 各 6、missing_conditions 8、follow_up_questions 5、每条文本 ≤ 120/200 字符、overall_note ≤ 400。
- `insufficient_context`：材料没有可用已提取来源且未选择来源时，确定性返回，**不调用模型**。
- `abstain`：模型判断回答与追问无关或信息不足；给出 `abstain_reason`。

## 4. Source semantics（沿用 Grill/Evidence 纪律）

- 来源池 = 服务端确定性来源（findings citations 前 12 条 + 前 8 条关键陈述，带局部上下文） + 用户 `source_refs`（逐字复验）。
- `s1...` 是**本请求内**的临时选择 ID，不落库、不是稳定 deep link。
- 模型输出只能含 source_id；`quote/block_id/start/end/line_number` 全部由代码回填。
- 未知 source_id：supported claim 降级为 unsupported（不修、不猜）。
- 请求里的 `source_refs` 复验失败：整请求 400 `source_ref_mismatch`（材料是事实源）。

## 5. Error codes

| 场景 | HTTP | code |
| --- | --- | --- |
| body 缺字段/空白/超长 | 400 | `invalid_request` |
| material 不存在 | 404 | `material_not_found` |
| review_id 不存在 | 404 | `review_not_found` |
| review 绑定的 rubric 版本不可用 | 404 | `rubric_not_found` |
| material 不是 review 成员 | 400 | `review_material_mismatch` |
| source_refs 无法逐字复验 | 400 | `source_ref_mismatch` |
| prompt 超限 | 400 | `material_too_large` |
| 未配置 LLM | 503 | `llm_unconfigured` |
| 上游不可用 | 502 | `llm_unavailable` |
| 超时 | 504 | `llm_timeout` |
| 响应不合 schema（含重复 key/未知字段/超长） | 502 | `llm_invalid_response` |

失败语义：Coach 的 5xx 只影响本次 Coach 调用；用户仍可继续查看问题、来源与 preparation checklist，并继续编辑材料。

## 6. Grill preparation shape

```json
{
  "prompt": "95% 与 90% 的测试条件分别是什么？",
  "quote": "95%",
  "block_id": "mat_...-blk-0",
  "start": 9,
  "end": 12,
  "trigger": "numeric_discrepancy",
  "why": "同一度量词在材料中出现多个数值，可能被问数值口径与差异原因。",
  "preparation": ["测试条件（数据集、环境、时间窗口）", "样本量", "指标定义与计算口径", "最终采用哪一处数值及理由"]
}
```

- `trigger` ∈ `numeric_discrepancy | numeric_statement | comparative | absolute | generic`，由来源（finding kind / statement signal）确定性映射。
- `why` 是「为什么可能被问」的人话映射（≤120 字符），只描述来源特征，不暴露 `numeric_inconsistency`/`needs_review`/source_id 等内部机器码。
- `preparation` 是程序生成的确定性清单（3–6 条），不是答案、不是结论，也不表示真实评委会问；无法分类时给 `generic` 有限清单。
- 模型不能提供 `trigger`/`why`/`preparation`：解析器只接受 `prompt/source_id`，额外字段整次 502。
- 未改 `prompt/quote/block_id/start/end` 的既有语义与坐标回填。

## 7. 前端适配要点

1. 调用 `/api/v1/grill` 拿问题与 checklist，直接渲染 `preparation`，无需额外 LLM 请求。
2. 用户写回答后调用 `/api/v1/response-coach`；把问题对应的 `quote/block_id` 作为 `source_refs` 传入（可选）。
3. Coach 请求是同步单次调用；有限并发与 stale-response guard 由 frontend pod 负责，backend 不需要队列/SSE/后台任务。
4. 任何 Coach 错误都只影响该卡片；不要清空问题/来源/checklist。
