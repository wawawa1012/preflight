# 统一指标（9 Metrics）

> 每次运行都用同一把尺。所有计数只看用户可见行为，不看代码、不看 golden 答案。
> 措辞纪律与 `docs/PRODUCT_TREE.md` 第六节一致：本文件用"缺失/有矛盾"仅指"产品 UI 说出这些词"的事件，不是对材料的裁决。

## 1. TIME_TO_FIRST_VALUE（首次价值时间）

- 定义：从 scenario 起点（通常是首页）到用户看到第一条"与自己材料相关、可点回原文"的结论，秒表秒数。
- 测量：手机计时；起点截图 + 终点截图；四舍五入到 5 秒。
- 参考线：Zero-Patience/Judge 视角 ≤60 秒为好，>120 秒记弱；Contestant 深度 scenario 可放宽到 180 秒，但须在报告中注明 persona。
- 防作弊：终点必须是"点得回去的结论"，只看到"检查完成/通过"不算（那是 WAIT，不是 VALUE）。

## 2. SETUP_STEPS（上手步数）

- 定义：到"发起第一次检查"共点了几步（点击/输入/选择各算 1 步；登录/配 key/读教程的步数单独括号注明）。
- 测量：逐条列出（例：首页→开始→粘贴→选清单→检查 = 5 步）。
- 参考线：Judge 要求 ≤3 步到价值；First Review 通用线 ≤5 步；超了记 BLOCKED 候选。
- 防作弊：靠 API/改库跳过的步数不得减记；跳过即整轮作废。

## 3. BLOCKED_FLOWS（阻塞流次数）

- 定义：按 scenario 的 TASK 走，本该通但走不通的次数（找不到入口/点了没反应/报错无指引/需教程配 key）。
- 测量：每次记 `步骤 + 原话/截图 + 是否有下一步指引`。UI 卡住一律记 `USER FLOW BLOCKED`。
- 铁律：不得用 API/数据库/源码绕过后算成功；绕过即作废。
- 分级：致命阻塞（主线断了）→ Gate 不通过；边缘阻塞（支线）→ 有条件通过 + 必改。

## 4. DEAD_ENDS（死胡同次数）

- 定义：没报错、但用户不知道下一步干什么的次数（报告看了不知道改哪、对比看了更晕、追问太水备不了答）。
- 测量：每次记 `位置 + 用户原话（"我不知道改哪"） + 缺什么（一句话）`。
- 与 BLOCKED 的区别：BLOCKED 是"路断了"，DEAD_END 是"路还在，但我不想走了"（Zero-Patience 离场多属此类）。

## 5. TRUST_FAILURES（信任失败次数，一票否决项）

- 定义：产品说得比它真正知道得更多的次数。见一次记一次，抄系统原话（一字不改）+ 点回原文的验证结果。
- 至少含以下类型（命中任一即记）：
  1. 禁用词：已满足 / 已支撑 / 覆盖率% / 分数预测 / ✅❌ 满足芯片。
  2. 引用失真：依据点回去对不上（张冠李戴/截断改意/原文没有）。
  3. 范围外断言：没说清范围（查了哪份、多少内容）就下"无问题/通过"结论。
  4. 版本混淆：旧结论冒充新版本/新清单结论且无标注。
  5. 人机混淆：AI 提议显示为已确认；无效/弃权项消失且计数照涨。
  6. 缺三件套的结论：凡下结论（尤其「缺失/有矛盾」）却答不上"搜了多大范围？为什么这样判？点哪里看原文？"。
- 分级：致命（2/4/5 中编造与混淆）→ Gate 直接不通过；严重（1/6）→ 有条件通过 + 必须改措辞；同一轮 ≥3 次轻微也升级为严重。
- 诚实豁免：系统说"未评估/当前范围尚未发现引用（+范围说明）/待核对" = 诚实，不记失败（能力没做但话没说满）。

## 6. INTERNAL_CONCEPT_LEAKS（内部概念泄露次数）

- 定义：UI 把内部工程词裸抛给用户的次数。词表：Block / Span / Locator / Criterion schema / Binding / Finding / SourceRef / rubric_id / rev（无解释时）/ schema / quote_not_found / API / 堆栈 / prompt / 模型名。
- 测量：每次记 `位置 + 原词 + 有无大白话解释`。有解释（"版本 rev N = 你用的第 N 版要求"）则不记。
- 定级：单独出现且结论诚实 → 只记 LEAK（必改文案，不否决 Gate）；伴随错误结论 → 升级为 TRUST_FAILURE。

## 7. WAIT_WITHOUT_VALUE（无价值等待）

- 定义：转圈/加载/排队中用户不知道"在等什么、还要等多久、等完有什么"的秒数。
- 测量：分段掐表（例：检查等待 75 秒，其中 60 秒无进度话术 → 记 60 秒）。
- 参考线：>20 秒无话术（Zero-Patience/Judge）即记一次；>90 秒无话术（任何 persona）即候选 BLOCKED。
- 减分豁免：有诚实话术（"首次检查约需 60 秒，正在逐条核对第 2/5 条"）→ 秒数减半记录，并在 DELIGHT 候选注明。

## 8. USEFUL_MOMENTS（有用瞬间数）

- 定义：用户拿到一个"可行动、点得回去、说得对"的瞬间。例：找到 1 个真扣分点 + 改法 + 出处；追问像评委会问且答得上有出处；对比讲清 1 条变化。
- 测量：逐条列 `原话 + 出处（点回原文的位置） + 为什么有用（一句话）`。自吹（"很好"）不算，必须能复述出行动。
- 在 Skeptic 轮中记为"诚实时刻"（弃权/标无效/说未评估各算 1 个）。

## 9. DELIGHT_MOMENTS（惊喜瞬间数）

- 定义：超出预期的顺滑/诚实/聪明。例：第一次点回原文高亮动画；空材料诚实说"没什么可查，不给结论"；对比一目了然；等待话术诚实又具体。
- 测量：逐条列 `瞬间 + 原话/截图 + persona 反应（一句话）`。Delight 不抵 Trust Failure（再惊喜也不能洗撒谎）。
- Judge 专用：wow = DELIGHT ≥1 且 TIME_TO_FIRST_VALUE ≤120 秒。

## 记录格式（每次运行粘贴此表）

| 指标 | 数值 | 证据（截图/原话/位置） |
|------|------|------------------------|
| TIME_TO_FIRST_VALUE | __秒 | |
| SETUP_STEPS | __步（清单：） | |
| BLOCKED_FLOWS | __次 | |
| DEAD_ENDS | __次 | |
| TRUST_FAILURES | __次（分级：致命__/严重__） | |
| INTERNAL_CONCEPT_LEAKS | __次 | |
| WAIT_WITHOUT_VALUE | __秒 | |
| USEFUL_MOMENTS | __个（清单：） | |
| DELIGHT_MOMENTS | __个（清单：） | |
| contamination（是否用了源码知识） | true/false | 如 true 说明并作废/重跑 |

## persona × 指标权重速查

| persona | 主指标 | 一票否决 |
|---------|--------|----------|
| zero_patience_user | TIME / SETUP / DEAD_END / WAIT / DELIGHT | TRUST 1 次即失败离场 |
| contestant | USEFUL / TRUST / BLOCKED / TIME | 建议撒谎/改后谎报解决 |
| enterprise_reviewer | TRUST / LEAK / BLOCKED / USEFUL(追溯数) | 范围外断言/版本混淆/人机混淆 |
| paper_author_reviewer | TRUST / USEFUL / LEAK / DEAD_END | 条件吞没/过度背书/编造印证 |
| competition_judge | TIME / WAIT / DELIGHT / BLOCKED | 分数背书/点回对不上 |
| adversarial_skeptic | TRUST / LEAK / BLOCKED | 任一致命陷阱命中 |
