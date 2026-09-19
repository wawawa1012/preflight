# Agent Specialization Contract

2026-09-19 · audited base `2d52124` · backend-only hardening

**实际结构：三个使用同一 provider/client 的受限模型角色 + 两个确定性检查器。**
没有自主 Agent 对话、动态工具选择或 LLM Coordinator。本轮不改公开契约、端点、DB schema、frontend。
角色差异已体现在上下文、返回类型、来源权限及执行后的验证门；语义质量仍需人工与 live evaluation。

## 准入三问

| 现有屏幕入口 | 可执行验收 | demo 时间 |
| --- | --- | --- |
| 材料详情 / criterion 预检候选 | 跨窗来源无法进入候选；伪造 quote 不可接受 | 20 秒 |
| 报告 / 修复建议 | 只处理可重新生成的一条 Finding；直接选数值被拒 | 15 秒 |
| Grill | 选择 source ID，由代码回填原文坐标；无来源零调用 | 25 秒 |

不新增屏幕。本地 stub 演示应显式标注为验证门演示，不是模型质量测评。

## 真实结构

```mermaid
flowchart TD
    UI[用户显式操作 / FastAPI 确定性路由] --> E[criterion + 完整 Block 分窗]
    E --> EL[Evidence Auditor / shared LLM client]
    EL --> EG[当前窗口 block ID 门 → storage quote 验证]
    EG --> P[候选 passed 或 invalid / 尚未人工裁决]
    P --> H[人工接受 → 再验证 → annotation + criterion link]
    B[持久化 Block / 服务端 Locator] --> E
    B --> S[Statement Inspector / regex / 最多20条]
    S --> C[Consistency Inspector / 数值 单位 度量词匹配]
    UI --> R[用户选一条数值 Finding]
    R --> RG[原文复验 + 从当前 Block 重新生成 Finding]
    B --> RG
    RG --> RL[Repair Editor / shared LLM client]
    RL --> RV[严格结构 + 长度 + 有限数字词法门]
    RV --> RO[建议文本 / 不写材料]
    S --> G[验证来源池 / statements 最多8条 + findings citations]
    C --> G
    G --> GL[Challenge Examiner / shared LLM client / 只返回 source ID]
    GL --> GV[允许 ID + 原文再验证 / 代码回填 quote和span]
    GV --> GO[追问 / 不写材料]
```

## 审计：叙事与源码的差别

| 角色 / 实际入口 | 修改前实际行为 | 本轮落实 |
| --- | --- | --- |
| Evidence：`main.create_agent_proposal` → `llm.propose_candidates` | criterion + bounded windows；严格 JSON；storage 验证全材料中的 quote；空候选合法。没有校验候选属于产生它的窗口 | 合并前限制 block ID 在当窗内；越界丢弃，保留 raw response 和日志；quote 仍交既有 storage 验证；prompt v2.5 |
| Repair：`main.create_repair_suggestion` → `repair_suggest.suggest_repair` | 输入只支持 `ConsistencyFinding`；复验引用，但信任客户端解释/度量/数值元数据；输出只查 JSON/200字 | 从 Block 重新生成 Finding；用服务端解释；新增数值/部分明确选值表达被拒；action 限40字 |
| Challenge：`main.create_grill` → `grill.generate_grill` | finding + 前8条 statement；模型输出全部坐标；只要是全文真实子串即可通过；无来源仍调用 | 已验证来源池；模型只给 source_id；程序恢复坐标，未知 ID 丢弃；无来源零调用；有限泛化问题拦截 |

`llm.complete` 仍是唯一 provider 适配器；模型没有文件、SQL、HTTP 等自主工具权限。
Evidence 的写入由固定应用流程完成，模型本身不能 accept。Repair/Grill 无写入路径。

## Evidence Auditor

- **Objective:** 一条 criterion 下提出直接依据候选；precision 优先于 recall。
- **Inputs:** criterion 的 id/title/requirement/required_evidence + 当前完整 Block 窗口；24,000 字符上限；整块不拆，超大单块报错；按序扫描全部窗口。
- **Can:** 提出 `block_id/quote/rationale/risk_note`；返回空数组。
- **Cannot:** 判断满足要求、生成可信坐标、跨窗口选源、替用户确认关联、改材料。主题相关并不自动构成直接依据。
- **Abstain when:** 没有直接依据时模型应留空；越界候选代码丢弃。非法结构重试一次仍错则整次失败，不把部分扫描伪装为完成。
- **Source authority:** 只能提议精确 quote；坐标由 `resolve_span` 生成。`passed` 仅表示原文验证通过。
- **Validation:** 严格 JSON → 当窗 ID → 全材料 quote 精确匹配 → 人工 accept 时再次验证及原子写入。无效 quote 保留 invalid 状态供核查。
- **Primary metric:** 人工标注直接依据上的候选 precision、负例弃权率；另计 quote-invalid、越界拒绝、尾窗到达、人工接受/拒绝、成本。离线 stub 不计算模型 precision。

合并按 `(block_id, quote)` 去重，最终上限12；这是安全上限，不是质量排名。每窗最多3条、rationale 40汉字仍仅为 prompt 约束，解析器没有强制；不能把它们当程序保证。越界丢弃后的空结果不证明不存在依据。

## Repair Editor

- **Objective:** 给一条已有数值 Finding 的最小改稿方向；先核实，再统一或说明条件差异。
- **Inputs:** 仅一条重新生成的 `ConsistencyFinding`（kind/measure/values/服务端 explanation）及已验证的精确引用；不送整份材料、不送 rubric、其他 finding。
- **Can:** 建议核对来源、条件、统一口径或解释差异；返回 `suggestion/action`。
- **Cannot:** 自动改稿、指定哪个数字是真值、发明实验/认证、把风险写成事实结论。
- **Abstain when:** 无法从当前材料重新生成输入 Finding 时调用前拒绝（现有 `citation_mismatch`/400）；无空建议成功类型。输出不合规返回现有 `llm_invalid_response`/502。
- **Source authority:** 浏览器仅选择可再生的 Finding；不信任其 explanation/扫描计数。引用和问题关键字段必须匹配服务端结果。
- **Validation:** 原文 span → 重建 Finding → 严格两字段 JSON → suggestion ≤200/action ≤40字符 → 新数字字面值与部分明确选值表达拒绝。
- **Primary metric:** 人工评估最小修改率、可执行性、无新事实率、保持中立率；程序另计伪造 Finding 拒绝率/词法误拒率。

**范围限制：** 当前只有两种数值 Finding kind，至少两条 citation、两个 value。单句“95% 缺条件”“强陈述无引用”“行业首创”尚无相应输入类型和检测链。本轮不编造 `needs_review` 对象绕过这个限制。

词法门保守，可能误拒编号列表、数字格式变化、假设性建议；建议不复述数值。无法保证中文数字、隐含选边、非数字事实、最小改动语义。比如“已经获得权威认证”仍可能通过；benchmark 明确保留该反例。200字也不等于建议必然最小。

## Challenge Examiner

- **Objective:** 针对可追溯来源提出具体追问，允许少问和零条。
- **Inputs:** 确定性 findings 的 citations + 前8条 statements，经精确复验去重；每源包含 basis、quote，以及左右各最多100代码点的局部上下文。没有 criterion 上下文；不能宣称 rubric-aware questioning。
- **Can:** 内部 JSON `questions: [{prompt, source_id}]`；最多5条，每题≤200字符。
- **Cannot:** 提供 source coordinates/答案/修改建议/真假裁决；引用未进入允许池的材料片段。
- **Abstain when:** 空来源池直接 `[]`、不读模型配置/不调用模型；模型也可返回 `[]`；未知 ID 或无法再验的源逐题丢弃。
- **Source authority:** `s1...` 是本请求内的临时选择 ID，不落库、不是稳定 deep link。公开返回仍是 `{prompt, quote, block_id, start, end}`，所有来源字段来自代码。
- **Validation:** 准备来源时复验 → 严格内部 schema → ID 白名单 → 再验 Block slice → 回填公开结果；去除重复同题同源；有限拦截“请介绍项目创新点/技术方案”等精确泛问。
- **Primary metric:** 返回 citation 完整性、越界源拒绝、无来源调用数；语义层另用人工评审问题具体性、可回答性、虚构前提率及泛问率。

source 正确不代表问法相关或前提为真。泛问词法门不是语义分类器；同义改写可穿过。窗口不覆盖整篇材料：Statement Inspector 最多20条，prompt 单独 statement 最多8条；不得把零追问解释为材料没有风险。

## 两个 Inspector 与 Coordinator

- `claim_inspector.inspect_statements`：正则标记比例、绝对化、比较、数字；无网络、无模型，不创建可信 Claim，不判断真假。
- `consistency.find_numeric_findings`：复验 span、归一数值/单位、按有限度量词规则分组；无模型。不同数值是待核对问题，尚未验证同一 test-set / inference settings，不等于已证明矛盾。
- Coordinator 只有 FastAPI handler、窗口顺序循环、验证/持久化调用。这是确定性应用流程，没有第四个模型。

## 离线 benchmark 与判读

新增 `backend/tests/test_role_benchmark.py`，28个测试方法：18个角色场景、4个 differential、6个附加边界测试。
所有模型调用由 stub 替代；Evidence 跑真实 SQLite 临时库、生产验证和接受路径；Repair/Grill 跑生产入口。
**28/28 绿色表示回归断言成立，不是18个语义目标全部完成。** 不宣称测得实际模型质量。

| 场景 | 当前结果与测试性质 |
| --- | --- |
| E1 直接依据 | replay候选被验证，仍 unreviewed；没有自动建立 annotation |
| E2 弱相关 | 空结果 replay合法；真实但无关的quote仍会passed，已知语义缺口 |
| E3 Java考试 | 同E2；不能宣称代码能判断跨领域不相关 |
| E4 长文尾部 | 实际 planner多窗 + 逐窗入口；末窗到达且候选保留 |
| E5 伪造quote | 实际storage标invalid；accept拒绝 |
| E6 半句/强结论 | 改写成不存在的整句被拒；真实quote+夸大rationale仍过源验证，已知缺口 |
| R1 88/93 | 直接指定数值的示例被词法门拒；中立建议replay通过，非全语义保证 |
| R2 95%缺条件 | SCOPE GAP：无此Finding；拒绝伪造输入；尚不能完成此修复功能 |
| R3 缺引用 | SCOPE GAP，同上 |
| R4 行业首创 | SCOPE GAP，同上；目标应是补检索依据/弱化主张而非证明首创 |
| R5 最小改动 | 单Finding上下文隔离、长度和不写材料得到验证；最小改动质量仍需人工 |
| R6 造事实 | 新数字拒绝；非数字认证谎言可通过，明确 limitation |
| C1 数值问题 | 真实finding→来源池→replay问题→代码坐标；不评估模型自行出题质量 |
| C2 95% | 局部上下文保留“抽取准确率”；replay样本量问题；不提供答案 |
| C3 泛问 | 两种已知泛问被代码丢弃；同义泛问未被全面识别 |
| C4 无依据 | 零问题、零模型调用 |
| C5 伪坐标 | 模型返回旧坐标结构被拒；虚构source ID丢弃 |
| C6 源完整性 | 每个保留问题的quote等于真实Block切片，含emoji代码点 |

### Differential cases

| 同一材料事实 | Evidence动作 | Repair动作 | Challenge动作 | 实际验证 |
| --- | --- | --- | --- | --- |
| 95%抽取准确率 | criterion要求量化指标时给原文候选 | 未来应要求补样本/条件；当前无Finding | 追问样本与测试集 | D1：两角色输出/上下文隔离 + Repair范围缺口 |
| 88%与93%召回率 | 候选只引用报告中的数值，不选真值 | 先核对条件与来源，再统一或解释差异 | 追问两处条件/口径 | D2：完整三角色入口、不同上下文和输出contract |
| 行业首创 | 仅对“作者创新定位陈述”要求给候选，不能证明真的首创 | 未来应补检索依据或弱化 | 追问检索范围/依据 | D3：两角色 + Repair范围缺口 |
| 速度提升2倍 | 对“声称的性能变化”给原文候选 | 未来应补基线/测试条件 | 追问相对基线与条件 | D4：两角色 + Repair范围缺口 |

这些结果证明调用边界不同，不证明stub中的优良回答来自真实模型。完整四组三角色语义benchmark还没有实现；在不新增领域契约的本轮边界下保持这项欠账。

6个额外测试覆盖：跨窗口真实quote越权、Repair客户端注入元数据、第9条未提供陈述的越权、Grill来源准备后的原文再验、Grill虚构问题前提的已知缺口、六种跨角色响应互换均被拒绝。

### 运行

在本 worktree 的 `backend` 下，用已安装依赖的 Python：

```powershell
& 'F:\project\Preflight\backend\.venv\Scripts\python.exe' -X utf8 -m unittest tests.test_role_benchmark -v
& 'F:\project\Preflight\backend\.venv\Scripts\python.exe' -X utf8 -m unittest discover -s tests
```

根目录契约校验：`& 'F:\project\Preflight\backend\.venv\Scripts\python.exe' -X utf8 scripts/check_contracts.py`。
验证命令与结果另记于 CHANGELOG；不把先前测试数当成未来提交保证。未运行frontend build；未调用真实provider。

已有 OPTIONAL live harness（本轮未执行）：根目录执行 `python scripts/run_preflight_benchmark.py --mode live`。
它会读取本checkout配置并产生费用，只覆盖既有Evidence案例，不覆盖三角色。结果落 `benchmark/results/`。
其exit code主要代表运行成功，不代表语义达标；质量需逐条核查原文、criterion、弃权和候选。不要把它作为普通suite的一部分。

## Deferred architecture debt / 尚未实现的保证

1. Evidence 的直接相关性、部分支持/过度结论、rationale真实性；Repair 非数字虚构/隐含选边/最小改动；Challenge 问题相关性/虚构前提/泛问同义改写，都仍主要靠prompt和人工，不是确定性保证。
2. Repair 缺少非数值 Finding 输入；扩展须单独设计/冻结契约，不能把单个 statement伪装成数值Finding。R2/R3/R4与三组完整differential待实现。
3. 三角色没有动态工具系统；能证明的是不同应用权限、context和validator，不是自主多Agent协商或不同训练模型。
4. Grill 没有criterion context，来源扫描有限；Evidence12候选按顺序截取，可能损失尾部候选；超大单Block仍整次拒绝。本轮不扩检索策略。
5. `llm.complete`日志沿用Evidence `PROMPT_VERSION`标签；Repair/Grill还没有独立prompt版本/运行记录。勿用该字段声称可审计三角色的精确prompt版本。未新增run表。
6. Repair词法门会误拒部分无害数值表达；Grill数值真实但问题中新增事实不受完整语义检查。应收集真实任务的小样本人工标注，再决定是否需要结构化修复动作或更严格提问协议；本轮不加领域对象。

## 60秒答辩口径

“Preflight用同一个模型承担三种受限任务。依据审计员只看一条要求与有限原文窗口，输出待人工裁决的引用候选；代码检查来源和原文。修复顾问只接收一条能够从原文重新生成的数值问题，给短建议，不能改材料，明确选数值的建议会被拦截。质询官只从程序准备的来源ID中选择，引用和坐标由程序回填，没有来源就不调用。数字扫描和一致性匹配是普通程序，不包装成Agent。我们用越界来源、伪造引用和角色差异用例验证这些边界。同时，引用真实不等于结论成立，语义相关性与建议质量仍需人工复核，离线stub通过也不是实际模型能力证明。”

## 开发者理解任务（30–45分钟）

掌握4个概念：调用上下文边界、request-local source ID、源验证与语义验证的区别、重建Finding而非信任客户端。
可略过OpenAI SDK内部与正则引擎实现。跟踪一次 `88%/93%` 的三条入口；把Grill stub的 `s1` 改成 `s999` 观察丢弃；把Repair建议换成“统一修改为93%”观察拒绝；最后解释为什么真实但无关的quote仍可能passed。
