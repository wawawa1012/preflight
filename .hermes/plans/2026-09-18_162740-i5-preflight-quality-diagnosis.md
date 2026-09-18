# I5/I6 AI 预检质量诊断（只判断，不施工）

角色：Principal Architect。禁止改代码、禁止 commit、禁止因此打 patch。批准前不生成 DS 施工单。

测量范围：HEAD `8e4c62d`（I6 已落地）+ 工作区 `llm.py` 无 diff。未提交：`frontend/src/views/MaterialReportView.vue` 成功态顶栏加「返回材料」（+4 行）。`backend/app/llm.py` **没有** reviewer 越权的 v2 / max-8 / temperature=0；那些改动未进入本工作区，**建议不要保留、不要补做**，除非本诊断批准后按下面序列重做。

无法在本回合做真实 LLM 计时（会消费用户 key）。延迟数字以用户观察「20 多秒」为准；代码只能证明请求次数与输入规模，不能拆网络 vs 推理。回归基准必须补测量，不能用猜的 20s 当门禁。

---

## 1. Incident severity

| ID | 现象 | 级别 | 是否产品事故 |
| --- | --- | --- | --- |
| P0-precision | 无关 Java 练习题仍产出大量「相关」候选 | **P0** | 是。验证门只证「这句话在原文里」，不证「和评分要求有关」。预检叶子在评委面前会像乱找。 |
| P0-determinism | 同材料同 criterion 连点两次结果不同 | **P0**（产品语义） / P1（实现） | 是「每次预检=新一次提议」但 UI 没说；再叠加模型非确定性。 |
| P0-latency | 无匹配也要等 ~20s | **P1 偏 P0 体感** | 单次 1 个 LLM 调用、全量 blocks；无匹配并不更便宜。 |
| P1-nav | 报告页回不到材料 | **P1** | 真报告路由已有 `materialId`；成功态顶栏缺按钮。不是缺 Run 系统。 |

未批准的 llm.py v2：**本工作区不存在**。不要当已修复。

---

## 2. Current pipeline reconstruction

实测路径（`backend/app/llm.py`、`main.py:254-302`、`storage.py:543-573`、`MaterialDetailView.vue:421-436`、`preflight_report.py` 装配）：

```
人在 /materials/:id 对「一条」criterion 点「AI 预检」
  → POST /api/v1/materials/{id}/agent-proposals  {criterion_id}
  → 取该材料全部 blocks + 绑定 rubric 中那一条 Criterion
  → llm.build_messages：SYSTEM + 全文 blocks（每行 `[id] line N: text`）
  → llm.complete：恰好 1 次 chat.completions.create
        未设 temperature / seed；response_format=json_object
        timeout 默认 60s
  → parse_candidates：只校验 JSON 形状；空数组合法
  → 每个候选 resolve_span(block.text, quote)
        命中 → validation_status=passed
        block 不属材料 → block_not_found
        quote 不是子串 → quote_not_found
  → 落库 AgentProposal（新 id，无缓存、无去重）
  → UI 列出候选；passed 才可 accept
  → accept 单事务物化 annotation + criterion_evidence_link（proposed_by=agent）
  → I6 GET .../preflight-report 只数 **已接受的 link**，不读未裁决提案
```

### 每一层验证了什么 / 没验证什么

| 层 | 验证了 | 没验证 |
| --- | --- | --- |
| Prompt `p5-criterion-preflight-v1` | 只用给定 blocks；quote 须是精确子串；「不判断是否满足」 | **是否真相关**；**可否空结果**；applicability / no-evidence |
| LLM | 生成 JSON 候选 | 任何确定性、相关性阈值 |
| `parse_candidates` | 字段集合、非空 rationale | 相关强度；条数上限 |
| `resolve_span` 门 | quote 是该 Block 原文子串（Unicode 代码点） | 与 criterion 的关系 |
| UI 提案面板 | 展示 passed/invalid；invalid 不能接受 | 不把「可能相关」降级为弱候选 |
| accept | 再查重 + span 复验 | 相关性 |
| I6 报告 | 已核证关联计数 + 零关联范围句 | **不看** 未接受提案。盲接受会把假阳性写进「已核证引用 N 条」 |

结论：用户看到的「大量相关」发生在 **Proposal 层**。报告层默认不放大，除非人点了接受。验证门按设计就过滤不了「真实但无关」。

---

## 3. Root cause hypotheses（按证据）

1. **Prompt 正向性偏置（证据充分）**  
   SYSTEM：`只做一件事：从给定 blocks 原文中找出可能与该评分要求相关的原文片段。`  
   任务是「找出」，相关标准是「可能相关」，且明确「不判断要求是否满足」。没有「没有直接对应则返回 `{"candidates":[]}`」。  
   解析层 **允许** 空数组（`test_empty_candidates_list_is_valid`），prompt **没要求** 模型使用它。

2. **全量喂入（证据充分）**  
   `propose_candidates(criterion, material.blocks)` 每次把该材料全部 Block 塞进 user。Java 题库里总能抠出「实现 / 算法 / 应用」等字，被「可能相关」咬住。

3. **验证门能力边界（证据充分，不是 bug 而是缺口）**  
   `passed` = 原文存在。CONTRACTS 从 Iteration 3 起就是这个门。不能当 relevance 用。

4. **无 temperature/seed（证据充分）**  
   `complete()` 只传 `model, messages, response_format`。OpenAI 兼容默认温度通常 >0。同输入两次不同是预期，不是存储损坏。

5. **无 reuse 语义（证据充分）**  
   每次 POST 新 `ap_*`。UI `latestProposalFor` 取列表第一条。连点=两次独立采样。产品没说「预检」是 Re-run 还是查看上次。

6. **延迟（代码充分，20s 未在本机复测）**  
   每次点击 = 1 次 LLM；criterion 之间不并行（一次只跑用户点的那条）；无 cache。无匹配仍要跑完生成。SQLite 写入相对可忽略。拆网络/推理需要在 `complete()` 打点，尚未存在。

7. **报告导航（证据充分，用户路径写宽了）**  
   「查看预审报告」在 HEAD 指向 `/materials/:id/report`，**不是** `/report`。`/report` 是 Iteration 1 mock。真报告 `route.params.materialId` 已知。HEAD 成功态顶栏只有 Workbench；404/未绑定卡片已有回材料。工作区未提交 diff 已在顶栏加「返回材料」——形状正确，**未批准，本诊断不继续改**。

---

## 4. Prompt bug vs pipeline / product semantics

| 类型 | 内容 |
| --- | --- |
| Prompt bug / 缺口 | 「找出可能相关」+ 未授权空结果；无 applicability |
| Pipeline 缺口（有意） | 验证门不管相关性；一次一 criterion 全量 blocks；无 cache |
| Product semantics 缺口 | 「AI 预检」未定义为「新采样」vs「看上次」；UI 用「N 个候选」暗示找到了货 |
| 非 bug | 空 JSON 可解析；不静默截断（超 24000 直接 400）；I6 报告不读未接受提案 |
| 不要当成根因 | 未落地的 v2 prompt；「必须上 FTS」；缺完整 Run 系统 |

---

## 5. Precision 修复方案（只方案）

目标：无关材料上多数 criterion 得到 **0 条 passed 候选**，相关材料仍能提出真 quote。不能靠「最多 8 条」——那只是砍条数，不提高相关。

**最小正确（local）：**

- Prompt（升 `PROMPT_VERSION`，例如 `p5-criterion-preflight-v2`，**新写，不采用未批准稿**）：
  - 明确：没有直接对应则 `{"candidates":[]}`，这是合法且期望的。
  - 相关 = 该片段能作为该 requirement 的可定位依据，不是词面沾边。
  - 仍禁止判断「已满足」。
- UI：完成文案区分 `passed` / `invalid` / 空；空 →「当前范围尚未发现引用」，不要「预检完成：12 个候选」。
- 不要在验证门发明 AI 相关性分数。门继续只管 quote。
- 不要为 precision 改 I6 报告契约。报告继续只数接受后的 link。
- 未批准的「最多 8 条」：**拒绝**。压 recall。

**下一步才考虑（叶子先证明 prompt 不够）：**  
criterion 关键词对 Block 的确定性预过滤（方案 D），召回不足再用 FTS5（E）。现在上 FTS 是新树干，且同义召回差会误杀。

---

## 6. Determinism / cache 语义（产品先于技术）

应允许变：新一次「预检」的 LLM 采样（模型漂移、provider）。  
必须稳：同一 `proposal_id` 的落库内容；accept 物化；I6 报告对同一 link 集合。

**推荐语义（不要永久缓存当默认）：**

- 每次点击「AI 预检」= **显式新 Run**（新 `ap_*`），保留审计轨迹，兼容未来 VersionDiff（diff 的是两次 completed proposal / 两次材料版本，不是覆盖一行）。
- 面板默认展示 **该 criterion 最新一条**；若已有 completed 且人没要重跑，提供「查看上次」避免误点烧 20s。
- 可选 cache key（**复用须人点「用上次」或 TTL 短**，禁止静默永久）：  
  `sha256(material) + rubric_id + revision + criterion_id + provider + model + prompt_version`  
  不含 temperature 采样的「保证相同」——只保证「同配置可复用上次」。
- `temperature=0`：降低同配置抖动，**不能**保证跨 provider/版本幂等，不能当 precision 修复。可与 prompt v2 分两个 commit。
- 不设 seed（兼容提供商不一）。

---

## 7. Latency 方案比较（不实施）

约束：不降 recall、不静默截断、无向量库/新框架、优先 local。  
现状：1 次预检 = 1 次 LLM × 全量 blocks；多 criterion 是人串行点，不是服务端扇出。

| 方案 | latency | precision | determinism | 复杂度 | 裁决 |
| --- | --- | --- | --- | --- | --- |
| A 有界并发 | 多 criterion 墙钟下降；**单次仍 ~20s**；费用×N | 不变 | 不变 | 中（现 UI 一次一条，收益接近 0） | **现在不做**。明确：并发只是同时打多个 20s 请求。 |
| B 结果 cache | 重复点击近 0 | 不变 | 复用则稳、新采样则否 | 低-中 | **短 TTL / 显式复用**，禁止默认永久。 |
| C 请求去重 | 连点防双飞 | 不变 | 同 B | 低 | **做**。in-flight 同 key 合路。 |
| D 轻量预过滤（词面/必证关键词 ∩ blocks） | 零重叠可跳过 LLM → 无匹配变快 | 过严伤 recall | 过滤层确定 | 低 | **prompt 之后** 若无关用例仍全量慢再做；跳过必须在 UI 写清「未调用模型，词面无重叠」。 |
| E FTS5/BM25 | 可能少送 Block | 同义易漏（MASTER_PLAN 已警告中文） | 索引确定 | 中，新树干 | **现在不做**。 |
| F prompt 本地改 | 空结果仍要等生成，latency 几乎不变 | **主修 precision** | 略好（空更常出现） | 极低 | **先做**。不要指望它把 20s 变 2s。 |
| G `complete()` 打点 + 响应里带 `prompt_chars`/`elapsed_ms`（仅日志或失败提案 details） | 不加速 | 不变 | 不变 | 极低 | **先做**，否则以后还在猜。 |
| 静默截断 / 最多 8 条当加速 | 略降生成量 | 伤 recall | — | — | **禁止**。 |

「无匹配也慢」= 当前全量扫描 + 必须等 LLM 说空。要让无匹配变快，只能 D（跳过）或 B（复用），不是改 prompt 空数组。

---

## 8. Report navigation 最小正确方案

- **真报告** `/materials/:materialId/report`：scope 已在 URL。最小修复=成功态顶栏「返回材料」→ `/materials/:id`，保留 Workbench。刷新/深链仍成立。不要 `history.back()`。
- 未绑定卡片补 Workbench 出口（I6 计划不变量；HEAD 未绑定卡没有）。
- **Mock** `/report`：没有 material。不要从详情链过去。若用户点了页脚「结构演示（Mock）」，那是另一页，只回 Workbench 合理。
- 不要为此发明 Run/Project。

工作区已有顶栏「返回材料」未提交 diff：方向对，等批准后作为独立 UI commit；本诊断不改、不回退、不扩大。

---

## 9. 推荐最小修复序列（批准后才施工；现在不是施工单）

按 commit 切，仍属 I5 质量叶子，不新开 I7 Claim Inspector。

1. **docs/measure**：`complete()` 记录 `prompt_chars`、`block_count`、墙钟（日志即可）。不改 prompt。
2. **ui-nav**：报告成功态 + 未绑定态回材料 / Workbench（可吸收当前未提交 4 行，review 后再提交）。
3. **prompt v2**：空结果合法且期望 + 收紧「可定位依据」；`PROMPT_VERSION` 升级；**temperature=0 单独 commit** 以便回滚。
4. **ui-copy**：预检完成文案按 passed/空/invalid 计数。
5. **reuse**：同 key in-flight 去重；已有最新 completed 时二次点击需确认「重新预检」或「查看上次」。
6. **stop**。用第 10 节回归数据再决定要不要 D。不要做 A/E/8 条上限/向量库。

---

## 10. 必须补的 regression benchmark（尚未有；先设计）

放 `benchmark/cases/`，**禁止**用用户真实比赛材料入库。合成 fixture，test-only。

**Neg-Java（压假阳性）**  
Material：纯 Java/数据结构练习题（排序、链表、模拟卷），无创新/部署/指标叙事。  
Rubric：合成「软件创新 / 技术实现 / 应用价值」三条（不要用仓外真实赛事全文进 git）。  
期望：每条 criterion `candidates` 里 `passed` = 0（允许 invalid）。  
门禁：假阳性 passed > 0 则失败。先人工跑 N=1 定基线，再自动化。

**Pos-metrics（防打死 recall）**  
Material：含「准确率 95%」类可定位句。  
Criterion：关键数字须有出处。  
期望：至少 1 条 passed，quote 为那句精确子串。

**Stab-N（稳定性）**  
对 Pos 与 Neg 各重复 N=3（用户 key，人工或隔离 stub）。记录：candidate 集合哈希、passed 数、是否空。  
temperature=0 后 Neg 应稳定为空；Pos quote 允许轻微 rationale 差异，**quote 集合应稳定**。

**Lat-break**  
每次 `complete()` 日志：`prompt_chars`、`block_count`、`elapsed_ms`、`candidate_count`。  
断言：1 次预检 request_count=1；超 `MAX_PROMPT_CHARS` 不得截断（已有 unittest）。  
不把「<20s」写成 CI 门禁（依赖 provider）。

测量脚本不要进默认 unittest（会打网）。独立 `scripts/` 或 benchmark runner，默认 skip。

---

## 11. 现在不要做

- 不要实施任何 patch（含吸收未提交 Vue 之前先批准）。
- 不要采用未批准 llm v2 / 最多 8 条。
- 不要 FTS5、向量库、LangChain、为导航做 Run 系统。
- 不要静默截断、不要为加速降 recall。
- 不要默认永久 cache。
- 不要把 I6 矩阵改成展示未接受提案（那会把假阳性送上评委主路径）。
- 不要开 I7 Claim Inspector 当本事故修复。
- 不要代用户打真实 API key 批量预检。

---

## 工作区备注（给批准人）

```
 M frontend/src/views/MaterialReportView.vue   # 成功态「返回材料」——与 §8 一致，未提交
?? .hermes/                                    # 计划文件
 backend/app/llm.py                            # 干净，仍是 p5-criterion-preflight-v1
```

---

## 请批准的 frontier（下轮才出 DS 施工单）

1. 是否按 §9 的 1→5 序列修，且 **先测量+prompt/UI，不上 FTS**？
2. 「AI 预检」是否定为「每次新采样」+「二次点击需确认」？
3. 未提交的「返回材料」是否作为 nav commit 保留？
4. Neg-Java / Pos-metrics 是否允许用合成 rubric（不把真实赛事全文提交进 git）？
