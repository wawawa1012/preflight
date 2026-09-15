# 时间线与交付顺序

| 日期 | 交付 |
| --- | --- |
| 9/15 | Phase 0：蓝图、Git、契约、scaffold（已完成，commit e8e3308） |
| 9/16 | Report 通过 FastAPI 读取统一契约 Mock |
| 9/17–9/19 | 真实 Markdown → Block/Locator → 页面查看 |
| 9/20–9/22 | 单 criterion 真实 AI 预检 |
| 9/23–9/25 | Missing / 数字 Conflict / 修复重跑 / Diff |
| 9/26–9/28 | PPTX/PDF/DOCX、Rubric 编辑、cache/replay、UI 收敛 |
| 9/29–9/30 | 核心功能收口，停止新增功能 |
| 10/1–10/3 | benchmark、dogfooding、候选提交版、PPT/报告/视频 |
| 10/4–10/7 | 只修 bug、复现、彩排，不增加功能 |

每阶段结束：检查 → 更新 CHANGELOG → Git commit。未验收不记完成。

## 接下来：Iteration 1（9/16）

Report 通过 FastAPI 读取统一契约 Mock。具体切片和验收在当日任务中定义。

## 保底顺序

三幕闭环 > 引用真实性 > 可重跑八套 > 视觉装饰。时间不足先裁图表、复杂配置、便利交互，不裁验证和版本证据。
