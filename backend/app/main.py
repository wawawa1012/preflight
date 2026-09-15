from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal

from .contracts import RunReport
from .mock_report import MOCK_REPORT

app = FastAPI(title="Preflight", version="0.1.0")


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    contract_version: Literal["0.1.0"] = "0.1.0"


@app.get("/api/v1/health", response_model=Health)
def health() -> Health:
    return Health()


# 只读 mock：数据在 import 时已通过 RunReport 校验；当前不接解析、LLM 或数据库。
@app.get("/api/v1/report", response_model=RunReport)
def report() -> RunReport:
    return MOCK_REPORT
