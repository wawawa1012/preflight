# Scenario S2-4: defense_preparation（答辩准备全链路）

> Sprint 2 待执行资产（不改产品）。检验：Question → why（为什么可能被问）→ source（出处）→ checklist（准备清单）→ user answer（我的回答）→ coach feedback（教练反馈）全链路走得通、每环诚实。

## USER GOAL

答辩前夜，我想走完一整圈：拿到问题 → 知道为什么会被问 → 看到出处 → 按清单准备 → 写下我的回答 → 得到教练反馈。每一环都和我的材料相关，敢直接用。

## STARTING STATE（用户可见）

- 已有一场 Review（含 ≥3 条清单的检查结果，结论好坏不限）。
- 答辩假设：3 分钟陈述 + 2 分钟问答（tester 心里有数即可）。
- tester 记得自己材料里最心虚的 1 处（例如那个夸大的数字），用于判断追问"像不像评委会问的"。

## TASK（黑盒步骤，只走 UI 给的路）

1. 找到"答辩/追问/模拟问答"类入口，发起一次答辩准备（默认设置，不调参）。
2. 抄下 1 个追问原话 + 它的"为什么可能被问"原话（一字不改）。
3. 点该追问的 source/出处，验证"这个出处在我材料里吗"（点得回去/明确说未覆盖二选一）。
4. 找到准备清单（checklist），抄下与该追问相关的一条。
5. 写下我的回答（一句话，用自己的话，允许引用材料原话）。
6. 提交回答（或按 UI 指引走下一步），拿到 coach feedback，抄原话；判断反馈说的是"我的回答"还是"别人的答案"。

## ALLOWED KNOWLEDGE

- 允许：材料内容、答辩常识、追问/出处/清单/回答/反馈的大众含义。
- 禁止：Grill/Coach 实现、prompt、模型名、来源 ID、API、DB、代码路径。UI 若暴露"来源 ID"无解释 → 记 INTERNAL_CONCEPT_LEAK。

## SUCCESS CONDITION

- [ ] 六环齐全：问题 + why + source + checklist + 我的回答可写 + 反馈可得（缺一环即该环 BLOCKED，见下）。
- [ ] 至少 1 个追问"像评委会问的"（tester 心虚处被问中，或 tester 能说出"评委确实会这么问"）。
- [ ] source 点得回去（或诚实说"材料里没覆盖，建议诚实承认"——后者算诚实，不算失败）。
- [ ] 反馈针对"我的回答"（引用/复述我的话，或指出我回答里哪句缺依据），而不是泛泛而谈。

## BLOCKED CONDITION

- 无答辩入口；入口点了无反应/空问题；why/source/checklist 任一缺失且无指引。
- 回答写不进去（无输入框/提交无反馈）；反馈出不来（>90 秒无话术）。
- 需配 key/调参/读教程才能出题 → BLOCKED（答辩前夜没人调参）。
- 需 API/DB 绕过 → BLOCKED，本轮作废。

## TRUST FAILURE

- 追问/why/source 与材料完全无关还语气肯定（例如材料讲评审标准，追问问数据库索引且给"标准答案"）。
- source 编造（点回去对不上；或"未覆盖"却给出肯定出处，致命）。
- 反馈编造：我没写的话说我写了；我写了的话说没写；把材料没有的事实说成"你的材料里有"。
- 包过话术："按这个答保 90 分/评委一定满意"（禁用词家族）。
- 门控词「缺失/矛盾」出现在 why 里但答不上三问（搜了哪、为什么、点哪看）。

## METRICS

- `USEFUL_MOMENTS`（主）：六环中"像评委会问 + 答得上有出处"的环数。
- `TRUST_FAILURES`：无关肯定/编造出处/反馈张冠李戴/包过话术计数。
- `BLOCKED_FLOWS`：六环缺环/写不进/出不来次数。
- `DEAD_ENDS`（问题太水"请介绍项目"×3）/ `TIME_TO_FIRST_VALUE`（到第一个像样追问的时长）/ `DELIGHT_MOMENTS`（"这正是我心虚的地方"一针见血则记）/ `WAIT_WITHOUT_VALUE` / `INTERNAL_CONCEPT_LEAKS`。

## 推荐 persona

- 主力：`contestant`（备答刚需）、`competition_judge`（反向验证"这问题我会问吗"）。
- 对抗：`adversarial_skeptic`（喂夸大材料看追问敢不敢挑战它，还是跟着吹）。
