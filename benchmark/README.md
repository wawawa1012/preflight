# 预检质量 benchmark（test-only，禁止放真实赛事全文或私有材料）

- `--mode=stub`（默认）：不打网，走解析与验证门回归。neg_java 期望 0 候选；pos_metrics 期望精确命中「准确率达到 95%」。打印 JSON 并退出 0 即通过。
- `--mode=live`：读取 `backend/.env`，每个 criterion 调用一次真实 LLM；打印 prompt_chars / block_count / elapsed_ms / passed_count / quotes，结果写入 `benchmark/results/`（已 gitignore）。
- live 由用户手动运行（DS 不代打 API key）：`.\backend\.venv\Scripts\python.exe -X utf8 scripts\run_preflight_benchmark.py --mode=live`
- 默认 unittest 与 CI 只跑 stub；live baseline 数据不进仓库。
