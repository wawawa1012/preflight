# Preflight

参赛材料的 CI。当前仅 Phase 0：唯一蓝图、核心契约、可启动前后端空壳。
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

打开 http://127.0.0.1:5173，点击“检查后端连接”。API 文档：http://127.0.0.1:8000/docs。
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
backend/app/        FastAPI health 和 Pydantic contracts；无业务 pipeline
contracts/         JSON Schema、人工 fixture
docs/              冻结蓝图与阶段计划
scripts/           契约导出和 fixture 检查
benchmark/cases/   后续八套 case（当前占位）
data/              本地材料、数据库、缓存（Git 忽略）
```

只有 GET /api/v1/health 已实现。契约中的业务对象/接口是后续实现目标；没有文档解析、检索、模型调用或比赛评分。
依赖锁：frontend/package-lock.json、backend/requirements.txt；requirements.in 表示直接依赖范围。
