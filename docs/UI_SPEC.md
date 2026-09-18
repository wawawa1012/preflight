# UI 冻结

成熟 B2B SaaS / developer tool，信息组织参考 Linear、Vercel、Sentry、GitHub Checks。
非纯黑 slate 背景，violet/indigo 品牌色；Supported emerald，Weak amber，Critical/Missing/Conflict red。
避免霓虹、大渐变、3D、粒子。颜色之外始终有文字状态；支持键盘焦点和 Drawer Esc 关闭/焦点返回。

## 页面与路线（计划，Phase 0 仅 / 空壳）

| 页面 | 计划路由 | 内容 |
| --- | --- | --- |
| Workbench | / | 报告中心：最近预检概览（每份材料的已确认关联数/当前范围尚未发现引用项数）+ 开始预检入口。5 秒测试（I6 半句）：这是一个按评审标准预审材料、把每条要求点回原文的工具 |
| Rubric Studio | /projects/:id/rubric | criterion 标题、要求、所需证据、revision；只做表单编辑 |
| Materials | /projects/:id/materials | 文件、版本、解析状态、拒绝原因 |
| Progress | /runs/:id | 阶段、错误、重试入口；无伪造百分比 |
| Report | /runs/:id/report | 指标、RubricMatrix、风险、证据和修复 |
| Versions | /projects/:id/versions | before/after 选择和三类差异 |
| Review Questions | /runs/:id/questions | 风险来源、为什么可能被问、应答提纲，无聊天框 |
| Methodology | /methodology | 三臂测评、样本量、限制和来源 |

当前已实现的 Materials 路由（项目作用域路由落地前的正式 IA）：

- /materials：Materials Hub。主区紧凑行列表（整行可点击进详情）；右侧单个概览面板，只显示由列表响应直接计算的真实数据（已保存数量、总 Block 数、最近保存时间、支持格式）；空态只有一句说明和一个主按钮。
- /materials/new：添加材料工作流。未选文件时是唯一任务区（步骤说明 + 点击/拖入选择区）；生成预览后上传表单退场，顶部面包屑 + 低权重“更换文件”，保存动作固定在 sticky Material Header。
- /materials/:materialId：已保存材料详情。F5/深链按 ID 从 API 恢复；emerald 已保存徽章、本地保存时间、截断 sha256；无上传控件、无临时状态、无保存按钮、不以完整 material ID 为视觉主体。证据区在 Block 列表上方：显示已保存标注（quote + line + note）；在任意 Block 行点击“标注”展开行内表单（quote 预填整块原文、可改窄，note 可选），保存后由服务端校验并进入列表。评分标准区：未绑定显示只读标准仓的可用列表（title、来源、revision）与“绑定”，空仓显示“尚未配置评分标准”；已绑定显示来源/版本与 Criterion 列表，每项下挂已关联引用（quote、rationale、“查看原文”、“移除关联”），无则“尚未关联引用”。证据列表每条标注可“关联”（选择绑定版本内的 Criterion + 必填 rationale）或“删除”（需确认，关联级联清除）。Block 行显示“已标注 N 条”徽章与浅色高亮；带 #block-* 打开或点“查看原文”会定位并短暂高亮，找不到时明确提示。每条 Criterion 下有“最新预检 + AI 预检”入口：结果面板列出候选（quote、line、rationale、risk_note），验证徽章区分“原文引用有效 / 无效：<code> / 待验证”；invalid 候选不能接受（按钮禁用 + 提示），accept 后物化为该 Criterion 下的引用并显示 agent 溯源徽章，reject 可附可选原因；失败提案显示错误码。已有 completed 提案时默认只展示历史，需点“重新预检”才再次发起，空候选显示“空结果正常”。措辞纪律：只允许“已关联/尚未关联/绑定/候选/接受/拒绝”，禁止把相关或候选表述为“已满足/已支撑/覆盖”；“原文引用有效”只表示引用在材料中。
- /materials/:materialId/report：材料预审报告（Iteration 6）。只读装配：每行一个 criterion，显示“已确认关联 N 条”或“当前范围尚未发现引用”+ 范围句（文件名与 Block 数）；有引用时列出 quote、行号、「原文已校验」、human/agent 溯源徽章与 rationale，点击引用打开 USlideover Drawer 定位到原文行并高亮 quote；无引用不提供假链接。未绑定 409 只显示“尚未绑定评分标准”与去绑定入口，不画空矩阵；404 与加载失败保留回 Workbench 出口（另有「返回材料」）。
- /preview：兼容重定向到 /materials/new，不再是平级导航目标。

全局 invariant：Secondary workspaces must always provide an explicit route back to Workbench; browser history is not product navigation.

## 三个重点页面

Report：顶部工程指标，主体 RubricMatrix（criterion、状态、证据数、风险数），选择行后看 Evidence Card / Repair Checklist。
Conflict Compare 两侧显示主张、各自文件/locator/quote；所有引用打开 Evidence Drawer 原文片段。
Missing 没有正向证据时显示要求、搜索过的文件和局限；Unsupported 能打开 Claim 原文。无证据不提供虚假链接。

Rubric Studio：显式保存 revision，已运行报告绑定旧 revision；不因修改表单悄悄覆盖历史。
Versions：只比较同项目、同 rubric revision、完成的 Run；不兼容时解释原因。Resolved/New/Unchanged 支持筛选与前后引用。
Repair 勾选是用户记录，显示“待重新验证”；重新 Run 才能证明风险消失。

## 工程指标定义

- Submission Readiness：not_evaluated / blocked / needs_review / ready。未完成→not_evaluated；存在 critical→blocked；有其他 finding 或非 supported criterion→needs_review；全部 supported 且无 finding→ready。不是比赛分数。
- Rubric Coverage：supported criteria / 全部 criteria；零 criteria 或 Run 未完成为 null，显示“未评估”。supported 必须有有效 supports 引用。
- Verified Evidence：通过定位与 quote 校验的 evidence 对象数量，不声称全部为支持证据。
- Critical Risks：severity=critical 的 finding 数。
- Resolved Risks：与可比较基线相比消失的 finding 数；无基线为 null。

loading / empty / error / rejected / not_evaluated 状态必须有文字说明。Mock/Replay 标签始终可见，不能伪装真实分析。
