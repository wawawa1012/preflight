# 八套完整 project case

此文为协议，当前没有测评结果。八套跑通再考虑扩大。
每套 1 rubric、1 PPTX、1 report、1 test report（文档可用文本 PDF/DOCX），8–12 criteria；保留植入前后版本和人工 gold。

## Case 分配

| Case | 主要植入 | 对照难点 |
| --- | --- | --- |
| 01 | missing evidence | 有主张无测试支持 |
| 02 | unsupported number | 数字看似精确但无来源 |
| 03 | numeric conflict | 95% vs 89.7%，同评测条件 |
| 04 | version residue | 新旧版本/日期混杂 |
| 05 | overclaim | “所有场景”但仅小样本 |
| 06 | weak evidence | 只有设计说明、无验证 |
| 07 | 混合缺陷 | 中文同义改写，召回压力 |
| 08 | 修复版本 + 干净对照 | 不同数据集数值不可误判冲突 |

每套都包含正常 supported 项，不把所有材料都标成缺陷。case01–02 调试，03–08 在提示词冻结后评估；同时报告全八套和留出六套，避免把调参集当泛化成绩。

## 三臂

B0 Single LLM：一次完整上下文输入；B1 普通 RAG：相同 parser + FTS5 检索后一次裁决，无 Preflight Claim/Verify 机制；B2 Preflight：完整固定 DAG。
同 provider/model/temperature、相同文件和 rubric、相同输出字段、同一外部评分脚本。记录 prompt 和 token 上限；B0 上下文超限明确报告，不隐性截断。
B1 与 B2 共享检索预算以隔离机制差异；B2 多次调用的额外 token、延迟和费用必须报告。
live 冷缓存计时；cache/replay 单列，不充当实时模型测评。每例保留原始输出、校验失败、参数、model、prompt hash、运行时间。

## Gold 与指标

人工 gold：case_id、criterion_id、缺陷类别、主张/指标主题、可比条件、正确 block/span、预期 resolved 指纹。每例人工复核来源和标签。
Citation validity = 实际有效引用数 / 所有输出引用数；空引用为 N/A，同时报告引用总量，防止无引用得满分。
Unsupported claim 和 conflict 分别匹配 gold（criterion + 主张主题/比较条件），一对一计 TP/FP/FN，重复报警为 FP。
P=TP/(TP+FP)，R=TP/(TP+FN)，F1=2TP/(2TP+FP+FN)。分母零标 N/A；报告 micro 汇总与每 case 结果。
Rubric coverage 报产品 supported/total，同时与 gold supported 项核对，避免过度判 supported 人为提升覆盖率。
附带端到端 latency、LLM token、按记录的供应商单价计算成本；没有价格数据则只报 tokens。
失效引用不能算正确检出；未完成 case 单列失败，不能从汇总悄悄剔除。

## 增强闸门

中文/同义改写 recall 明显不足才对照 embedding；独立 verifier 只有相同案例提升 P/R 或引用真实性且成本可接受才保留。
八套仅演示级内部实验，不宣称研究级普适有效性。
