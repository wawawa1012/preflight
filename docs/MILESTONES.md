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

## Agent specialization hardening（2026-09-19，独立 worktree）

后端角色边界加固与离线benchmark实现；未合并、未做live模型质量验收。Evidence限制当窗来源，Repair复验/重建数值Finding，Grill改为选择服务端来源ID；公开契约与DB schema不变。
详见 [角色合同与能力缺口](architecture/agent-specialization.md)。Repair非数值Finding、语义相关性/中立性评估仍未完成，不据此把产品全部标为已验收。

## 进度备注（2026-09-16）

- Phase 0、Iteration 1（report mock）、Iteration 2A（Markdown 预览）已完成并提交；2A 竞态修复已收口（8e42335）。
- Iteration 2B（Markdown 保存与恢复，SQLite）：已验收并提交（48ec6f6）。
- Materials UX Slice 浏览器验收失败（导航 loop、宽屏空白、初始态像工程表单）；已按冻结 IA 重做为 /materials Hub、/materials/new 工作流、/preview 兼容重定向，实现完成，待人工验收。
- Iteration 3（Evidence Layer MVP）：实现完成并分步提交（fa548b1..2aec98b），待人工验收。
- Iteration 4 Phase A（Evidence→Criterion 人工关联 + 只读 rubric 文件仓）：Phase A 已验收并收口提交。
- Iteration 4 Phase B（转录确认稿并加载）：实现完成，待人工验收；取得官方评审细则后转录为新文件，不覆盖本版本。
- Iteration 5（单 criterion 真实 AI 预检 + 提案裁决，对应 9/20–9/22）：实现完成，待人工验收；真实 LLM 调用需用户在 backend/.env 填入兼容服务配置后人工验收。
- Iteration 5.1（Proposal Quality：prompt v2 允许诚实弃权 + 引用有效≠相关措辞 + benchmark harness）：实现完成，待用户跑 live benchmark（scripts/run_preflight_benchmark.py --mode=live，由用户手动；stub 已进回归）。
- Iteration 6（报告中心 + 真实评分矩阵 + 带范围的「当前范围尚未发现引用」+ Evidence Drawer）：实现完成，待人工验收；只读装配端点已批准并上线（两个 GET，不改既有表与端点语义）。
- 产品树治理生效（2026-09-18）：docs/PRODUCT_TREE.md 为功能取舍最高准则（准入三问/树干串行/树冠并行/事实性状态词表）。
- Iteration 6 方向已定：真实评分矩阵报告（替换 mock）+ 缺失证据发现 + Evidence Drawer + Workbench 报告中心化；验收标准含"5 秒测试"（见 PRODUCT_TREE.md 第七节）。
- 定位升级与交接（2026-09-18）：产品定位升级为"AI 时代可信声明预审（Trust Layer）"，比赛材料预审为第一个垂直模板（见 PRODUCT_TREE.md 定位节与垂直场景节；对外表述用价值句，Trust Layer 仅内部 North Star）。治理模型：Grok 任 Principal Architect / Product Lead（方向、规划、架构裁决、最终 review），DS 为默认施工 implementer，用户指定的工作包可由 Grok 亲自施工；任意时刻同一工作树只有一个 current implementer；GLM 转只读 reviewer。Grok 第一轮任务 = handoff verification（核对 HEAD/status/真实测试基线/页面路由/账本差距，并独立给出对 Iteration 6 方向的判断），验证通过并经用户批准后才开工。
- 时间线澄清（节点以官方通知为准）：10/7 内部 Feature Freeze；10/8–10 bugfix / 校赛材料 / Demo；10/10 校赛完成节点；10/15 20:00 省赛报名/缴费截止（不是作品开发截止）；省赛阶段安排依赛事通知。
- 空页填满切片（2026-09-18）：DELETE /api/v1/materials/{id} + /materials 行内 UModal 删除确认 + Workbench 与 /materials 行「k/n 条要求已有关联」+ /materials/new 拖拽区缩短；实现完成，待人工验收。
- 7.1b（2026-09-18）：「最新预检」列表只渲染待审核候选（passed+unreviewed 且尚未与该 criterion 建过同一 block+quote 关联）；已关联候选不再出卡片，已裁决/无效候选同样退场，验证门结果留一行机器码；实现完成，待人工验收；提交 29dd98c，check-agent-proposal 85/85，build 通过。
- Iteration 7.1（材料详情易用性：已关联候选显示「已关联」禁接受/拒绝、每条 Criterion「接受本条全部原文有效」批量接受、「证据」与全文 Block 默认折叠）：实现完成，待人工验收；提交 166288f，前端脚本 80/25/14/37/23 全绿，build 通过。
- Iteration 7.2（主操作收口 + 措辞）：每条 Criterion 主按钮改「确认这 N 条依据」（=批量接受）、单条接受/拒绝降为次要样式、Workbench 与 /materials 改「已确认依据 k / n 项」；提交 6285d40，已合入 main。
- I8（同材料数值一致性「待核对问题」）：GET consistency-findings + 报告页「待核对问题」点回 Drawer；提交 0c8d581，已合入 main。
- Locator v1（2026-09-21，分支 codex/next-locator，base 5f12236）：完整 Locator 持久化 + `user_version=1` 迁移 + 统一 SourceRef 复验（显式 span 可精确选择 occurrence）+ 下游 locator 适配 + TXT 全链；DOCX 真实解析等待 B2 `app.source_adapters.read_source_nodes`。定向验证：backend 451 tests OK、contract export/check PASS、TestClient smoke PASS；live 未跑。checkpoint eec27d4，实现提交见 CHANGELOG。

## 保底顺序

三幕闭环 > 引用真实性 > 可重跑八套 > 视觉装饰。时间不足先裁图表、复杂配置、便利交互，不裁验证和版本证据。
