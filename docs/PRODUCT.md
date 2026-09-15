# 产品冻结

Preflight：“参赛材料的 CI”。服务有明确评分标准的比赛/项目参赛者。
承诺：所有重要结论能追溯到真实材料的具体位置；缺失结论明确展示检索范围与限制。

## v1

- 文本型 PDF、PPTX、DOCX、Markdown；扫描件明确拒绝/提示不支持。
- 自定义 Rubric 手工结构化维护，不做万能评分标准解析。
- missing evidence、weak evidence、unsupported claim、cross-document conflict、overclaim。
- 修复清单、重新预检、Resolved/New/Unchanged 对比。
- 风险衍生只读答辩问题：为什么可能被问 + 应答提纲。

## 黄金演示验收

1. 某 criterion 有重要 Claim，但无支持证据：Missing/Unsupported，能查看主张原文和检索范围。
2. 同一指标、数据集、评测条件下 PPT 的 Accuracy 95% 与测试报告的 89.7%：双引用 Conflict。
3. 修改材料创建新版本，再 Run：原风险 Resolved，新风险 New，保留风险 Unchanged，风险总数下降。
4. 使用 Preflight 自己的 PPT、技术报告、测试报告、README 做 dogfooding；真实结果与演示 fixture 分开标识。

## 非目标

AI 替评委打分、模拟评委聊天、通用问答、万能 Agent 工作台、复杂编辑器和多模态解析均不做。
当前没有官方 AIC rubric 原文；不得捏造其评分细项或权重。D1 使用清楚标注的演示 Rubric，收到正式原文后再录入。
