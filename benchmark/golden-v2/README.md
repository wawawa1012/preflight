# Golden v2：2026 AIC 省赛材料终审 Pack

真人演示、确定性回归、Agent 评估共用的一套本科软件项目材料。人物、社团、数据均为虚构，与真实赛事无关。

## 文件

- `project_proposal_v1.md`：技术方案初稿（Review label：技术方案 · 初稿）
- `evaluation_report.md`：九月扩大测试报告（Review label：性能测试报告）
- `defense_script.md`：终审答辩讲稿（Review label：答辩讲稿）
- `project_proposal_v2.md`：技术方案修改版（Review label：技术方案 · 修改版）
- `review_standard.md`：人类可读审查标准（显示名：2026 AIC 作品审查标准）
- `review_standard.json`：同标准的 JSON 转录，格式对齐 `data/rubrics/*.json`（`{id, revision, title, source_note, criteria[]}`）
- `oracle.md`：标准答案与评估口径（EVIDENCE / CONSISTENCY / STATEMENT / GRILL / REPAIR / DIFF / SEMANTIC）

## Review 搭建（手工，三分钟）

1. 新建 Review，标题“2026 AIC 省赛材料终审”，绑定 `review_standard.json` 的标准（id `rubric_aic2026_review` rev 1）。
2. 依次上传四份材料并改 label：初稿→“技术方案 · 初稿”，报告→“性能测试报告”，讲稿→“答辩讲稿”，修改版→“技术方案 · 修改版”。
3. 演示顺序：初稿报告页（2 条待核对）→ 初稿 × 测试报告对照（2 条）→ 初稿 → 修改版 Diff（已解决 / 仍存在 / 新增各 1）→ 修改版 × 测试报告对照（仅剩 1 条，召回率已干净）。

## 故事线（一句话）

三个本科生做校园推文校对工具，初稿数字口径混乱，九月实测打脸，修改版改了一半留了一半。评委（或模型）要做的就是把数字和表述一个一个对上条件。

## 评估入口

- deterministic regression：`oracle.md` 第八节断言表（statement 计数、Finding 指纹、C6 阴性对照）。
- live model eval：`oracle.md` 第四、五节（GRILL intent 匹配、REPAIR 不选边纪律）。
- 真人 demo：本文件上一节搭建步骤，全程约三分钟，每一步都有预期输出。
