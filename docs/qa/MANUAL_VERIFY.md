# 你来点的验证（5–8 分钟）

两份合成材料在仓库里，不含真实赛事原文。

| 文件 | 用途 |
| --- | --- |
| `benchmark/cases/neg_java/material.md` | 应少出或不出候选（练习题不是项目依据） |
| `benchmark/cases/pos_metrics/material.md` | 应能提出「准确率达到 95%」这类原文 |

## 0. 重启后端

改过 `backend/app/llm.py` 后必须重启 uvicorn，否则仍会 `MissingSessionID`。

## 1. 未绑定也能进报告

1. 打开任意未绑定材料（截图那种即可）。
2. 右上应同时有 **查看预审报告** 和 **Workbench**。
3. 点「查看预审报告」→ 文案「尚未绑定评分标准」，且有 **返回材料**、**去绑定**、**Workbench**。
4. 「返回材料」回到该材料详情，不是回首页。

## 2. 负例（Neg-Java）

1. `/materials/new` 上传 `benchmark/cases/neg_java/material.md`，保存。
2. 绑定你已有的校赛工作标准。
3. 对每条 Criterion 点「AI 预检」（或「重新预检」）。
4. 期望：空候选（「没有提出候选」）或只有你一眼能否掉的牵强项。不要把练习题当证据接受。

若仍立刻 `llm_unavailable` 且正文含 `x-opencode-session`：把完整报错留下，下一步才考虑 `response_format`。

## 3. 正例（Pos-metrics）

1. 上传 `benchmark/cases/pos_metrics/material.md`，绑定同一标准。
2. 预检「技术实现 / 指标」类条目。
3. 期望：至少一条 **原文引用有效**，quote 能对上「准确率达到 95%」。
4. 接受一条 → 打开预审报告 → 「已确认关联 N 条」，点引用 Drawer 到原文行。

## 不要做

不要把这两份文件改成真实参赛稿再提交进 git。`data/rubrics/*.json` 继续 gitignore。
