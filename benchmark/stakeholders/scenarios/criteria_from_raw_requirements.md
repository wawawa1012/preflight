# Scenario: Criteria From Raw Requirements（从原始要求生成检查清单）

> 覆盖"材料 × 标准"通用模型（PRODUCT_TREE.md 二点五节）：换一份要求文件，检查清单跟着变。检验"标准不是写死的，我能带来自己的要求"。

## USER GOAL

我手里有一段 raw 要求文字（例如老师发的 5 条评审要点 / JD 的 4 条任职要求，纯文本即可），我想把它变成一份检查清单，然后用它查我的材料——全程我不用学"schema"，只用粘贴和点选。

## STARTING STATE

- 有一段 raw 要求文字（tester 手写 3–5 条，每条一句话，例如"方案须说明数据来源""经历须有量化结果"；不复用 golden，不提前调格式）。
- 有一份自己的 1 页材料（同上）。
- 产品首页可见。tester 不知道"标准文件格式/版本库"等概念（装作不知道）。

## TASK

1. 找到"换要求/自定义清单/绑定标准"类入口（按 UI 实际文字；找不到记 BLOCKED）。
2. 把 raw 文字交上去（粘贴/上传/导入三选一，只走 UI 给的路；若 UI 要求"按格式填"，抄下格式要求原话）。
3. 确认清单生成了：说出"现在是几条要求、每条是什么"（与 raw 对照，是否多/少/改意）。
4. 用这份清单查自己的材料一次。
5. 说出：这次是按我这份要求查的吗？哪里能看出来（版本号/标题/条数三者至少其一）？

## ALLOWED KNOWLEDGE

- 允许：raw 文字原文、自己的材料内容、"清单/要求/绑定"的大众含义。
- 禁止：Rubric JSON / Criterion schema / rubric_id / revision 锚定实现 / API / 数据库 / 导入脚本 / 代码路径。UI 若要求"填 JSON / schema 字段"且无大白话引导 → 记 INTERNAL_CONCEPT_LEAK + BLOCKED（普通用户到此即走）。

## SUCCESS CONDITION

- [ ] raw 文字交得上去（粘贴或上传，不要求手写 JSON）。
- [ ] 生成的清单与 raw 对得上（条数一致、每条无改意；多/少/改意需明确提示并可改，否则不算成功）。
- [ ] 用新清单的检查跑起来了，且报告能看出"按这份清单查的"（标题/条数/版本三者至少其一）。
- [ ] 全程无"让我学 schema/填字段/读契约文档"（有则 BLOCKED，见下）。

## BLOCKED CONDITION

- 无自定义清单入口；入口点了要配文件格式/调接口；粘贴后无反馈/报错且无下一步。
- 清单生成后不可改（多了一条删不掉、改意了纠不回来）。
- 新清单无法用于检查（只能看不能选、选了还是按旧清单跑）。
- 需 API/数据库/手写 JSON/读源码绕过 → BLOCKED，本轮作废。

## TRUST FAILURE

- 清单与 raw 严重不符（漏条/编条/改意）却不提示，检查还照跑（"按错卷子打分"，致命）。
- 报告标"按新清单查的"，实际还是旧清单的条目（挂羊头卖狗肉，致命）。
- 出现禁用词：已满足/已支撑/覆盖率%/分数/✅❌（自定义场景下同样禁用）。
- 版本混乱：换了清单但结论不标"按哪个清单/哪一版"，旧结论冒充新清单结论。

## METRICS

- `BLOCKED_FLOWS`（主）：自定义链路卡住几次（普通用户到 schema 即走，此处必严）。
- `INTERNAL_CONCEPT_LEAKS`（主）：schema/JSON/字段名裸奔计数。
- `USEFUL_MOMENTS`：清单保真条数（与 raw 对得上的条数）。
- `TRUST_FAILURES`：错卷子跑/挂羊头卖狗肉计数（一票否决级）。
- `SETUP_STEPS` / `TIME_TO_FIRST_VALUE` / `DEAD_ENDS` / `WAIT_WITHOUT_VALUE` / `DELIGHT_MOMENTS`：通用记法（Delight 例：粘贴 5 条秒变清单且可改）。

## 推荐 persona 组合

- 主力：`enterprise_reviewer`（"换标准版本"刚需）、`paper_author_reviewer`（"换投稿要求"视角）。
- 对抗：`adversarial_skeptic` S4 变体（换清单后看旧结论标不标版本）。
- 零耐心抽查：`zero_patience_user`（"让我填 JSON 即走"——2 次点击规则在此 scenario 最严）。
