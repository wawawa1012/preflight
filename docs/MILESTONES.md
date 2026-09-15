# 时间线与阶段验收

| 日期 | 交付 | 验收 |
| --- | --- | --- |
| 9/15–9/16 | Phase 0：蓝图、Git、契约、scaffold | 两端启动、contract 校验、首次 commit |
| 9/17–9/21 | Mock 前端完整路径 | 三幕可演示；重点 Report/Rubric Studio/Versions；全部 mock 标签 |
| 9/22–9/25 | 文档/Block/Locator/Rubric | 四格式可定位，拒绝扫描件，中文检索基础验收 |
| 9/26–9/30 | Claim/Evidence/Conflict/Risk | 95 vs 89.7 双引用；引用失效被拒绝 |
| 10/1–10/3 | Repair/Re-run/Diff/Replay | 不可变版本，三类差异，replay miss 不联网 |
| 10/4–10/5 | 八套 benchmark | 三臂可重跑、有 gold 和失败记录 |
| 10/6–10/7 | UI polish + 材料 + demo video | dogfooding、完整演示、Feature Freeze |
| 10/8–10/10 | buffer | 仅 bug、材料、视频、彩排；无新增功能 |

每阶段结束：检查 → 更新 CHANGELOG → Git commit。未验收不记完成。

## 接下来 D1（下一施工日，9/16 起）

1. 30–45 分钟：用户从 README 独立启动两端，读懂 JSON 引用链。
2. 补三幕 mock：同一演示 Rubric，before 有缺证据/数字冲突，after 有 resolved/new/unchanged；明确标注非官方评分标准。
3. 建立八页面路由和共享导航空布局，约定 mock service 返回现有 RunReport；暂不接后端业务。
4. Report 从矩阵行到 Evidence Drawer 的静态交互先走通；再做 Studio 表单与 Versions 对比。D1 先完成最小引用点击，不要求当天做完八页面。
5. 验收：95% 和 89.7% 点击分别打开正确文件/位置/原文；Missing 显示范围；刷新无白屏；build 通过。
6. 更新进度并提交。正式 AIC rubric 原文和用户实际参赛材料待录入，不阻塞 mock。

## 保底顺序

三幕闭环 > 引用真实性 > 可重跑八套 > 视觉装饰。时间不足先裁图表、复杂配置、便利交互，不裁验证和版本证据。
