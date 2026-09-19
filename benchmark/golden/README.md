# Golden 演示材料（产品体感，不是合成堆字）

1. 上传 `scheme.md`，绑定现有审查标准，打开报告：应出现关键陈述；同文件若只有一个 95% 则不一定有「待核对」。
2. 再上传 `test_report.md`。
3. 打开 `/compare`，选 scheme.md × test_report.md：应出现 **准确率 95% vs 89.7%**。空结果不是功能坏了——中英试卷那种文件没有同度量词冲突。
4. 不要用 `data_structure_exam_en.md` × `_zh.md` 演示对照。

## 30 秒现场演示

逐步点击脚本（含每步预期与兜底）见 [DEMO.md](DEMO.md)：Workbench →「开始核验」→ 上传 `scheme.md`（保存直达报告页）→ 必要时绑定 → cockpit 的「关键陈述 / 待处理」→ 上传 `test_report.md` →「与另一份材料对照」→ 95% vs 89.7% →「生成修复建议」。现场只用这一对文件。
