# Preflight

参赛材料的 CI。当前已实现 Report mock、Markdown 临时预览与材料保存/恢复；进度见 [docs/MILESTONES.md](docs/MILESTONES.md)。
唯一仓库：`F:\project\Preflight`。从 [Master Plan](docs/MASTER_PLAN.md) 开始；施工规则见 [AGENTS.md](AGENTS.md)。

## Windows 原生启动

已验证环境：Node 24、Python 3.11、Git。分别打开两个 PowerShell 终端，不需要 WSL，也不需要激活虚拟环境。

后端：

```powershell
cd F:\project\Preflight\backend
python -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd F:\project\Preflight\frontend
npm.cmd ci
npm.cmd run dev
```

打开 http://127.0.0.1:5173，点击“检查后端连接”。Materials 卡提供“添加材料”（/materials/new：上传 .md 查看 Block 与原始行号，保存后写入本地 SQLite data/preflight.db 并跳转到材料页）与“查看材料库”（/materials：列表，点击进入 /materials/:id，刷新或重启后端后仍可读取）。旧 /preview 兼容重定向到 /materials/new。API 文档：http://127.0.0.1:8000/docs。
Ctrl+C 停止对应服务。端口被占用时先检查已有服务，不强制结束未知进程。
npm.cmd 避免 PowerShell 执行策略阻止 npm.ps1；Python -X utf8 避免 Windows GBK 读取 UTF-8 配置失败。

## 检查

```powershell
cd F:\project\Preflight
.\backend\.venv\Scripts\python.exe -X utf8 scripts/export_contracts.py
npm.cmd --prefix frontend run contracts
.\backend\.venv\Scripts\python.exe -X utf8 scripts/check_contracts.py
npm.cmd --prefix frontend run build
```

## 目录

```text
frontend/src/       Vue 空壳；views、router、types、components、stores、services
backend/app/        FastAPI：health、report mock、Markdown 预览/保存、SQLite 持久化、Pydantic contracts
contracts/         JSON Schema、人工 fixture
docs/              冻结蓝图与阶段计划
scripts/           契约导出和 fixture 检查
benchmark/cases/   后续八套 case（当前占位）
data/              本地材料、数据库、缓存（Git 忽略）
```

已实现：GET /api/v1/health、GET /api/v1/report（只读 mock）、POST /api/v1/preview/markdown（临时预览，不保存）、POST /api/v1/materials（保存材料）、GET /api/v1/materials（摘要列表）、GET /api/v1/materials/{id} 与 GET /api/v1/materials/recent（读取；未知 ID/无记录返回 404 + ApiError）、证据标注（POST/GET/DELETE）、GET /api/v1/rubrics（只读标准仓）与材料绑定 / 人工关联（POST/GET/DELETE）。契约中的其余业务接口是后续实现目标；没有检索、模型调用或比赛评分。
数据：SQLite 位于 data/preflight.db（Git 忽略），业务表为 materials → blocks，加 evidence_annotations、material_rubric_bindings、criterion_evidence_links；评分标准只读文件放在 data/rubrics/*.json（Git 忽略，目录保留 .gitkeep），启动时校验、非法即拒绝启动，预检命令：`.\backend\.venv\Scripts\python.exe -X utf8 scripts/validate_rubrics.py`。当前仓内无官方标准，GET /api/v1/rubrics 返回空列表，UI 显示“尚未配置评分标准”。
依赖锁：frontend/package-lock.json、backend/requirements.txt；requirements.in 表示直接依赖范围。
