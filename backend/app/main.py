from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Literal

from .contracts import ApiError, MarkdownPreview, RunReport
from .markdown_preview import MAX_BYTES, PreviewRejected, build_preview
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


# 临时预览：只在内存中处理一次请求，不保存文件；用后关闭上传缓冲。
@app.post("/api/v1/preview/markdown", response_model=MarkdownPreview)
async def preview_markdown(file: UploadFile = File(...)) -> MarkdownPreview:
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    return build_preview(file.filename or "", data)


@app.exception_handler(PreviewRejected)
async def preview_rejected(request: Request, exc: PreviewRejected) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())
