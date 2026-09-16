from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Literal

from . import storage
from .contracts import ApiError, MarkdownPreview, MaterialSummary, RunReport, SavedMaterial
from .markdown_preview import MAX_BYTES, PreviewRejected, build_preview
from .mock_report import MOCK_REPORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保 SQLite 表和 data 目录存在；不做迁移。
    storage.init_db()
    yield


app = FastAPI(title="Preflight", version="0.1.0", lifespan=lifespan)


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    contract_version: Literal["0.1.0"] = "0.1.0"


class LookupFailed(Exception):
    """读取不到材料；由处理器转成 404 + ApiError。"""

    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


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


# 保存材料：服务端重新校验并重新解析上传文件（不信任浏览器回传的 blocks），原子写入 SQLite。
@app.post("/api/v1/materials", response_model=SavedMaterial, status_code=201)
async def save_material(file: UploadFile = File(...)) -> SavedMaterial:
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    preview = build_preview(file.filename or "", data)
    return storage.save_material(preview)


# 注意：/recent 必须先于 /{material_id} 注册，否则会被当作 ID。
@app.get("/api/v1/materials", response_model=list[MaterialSummary])
def saved_materials() -> list[MaterialSummary]:
    # 列表摘要：不返回 blocks，避免列表接口携带全量内容。
    return storage.list_materials()


@app.get("/api/v1/materials/recent", response_model=SavedMaterial)
def recent_material() -> SavedMaterial:
    material = storage.get_recent_material()
    if material is None:
        raise LookupFailed("no_saved_material", "还没有保存过任何材料", ["先上传并保存一份 .md"])
    return material


@app.get("/api/v1/materials/{material_id}", response_model=SavedMaterial)
def material_by_id(material_id: str) -> SavedMaterial:
    material = storage.get_material(material_id)
    if material is None:
        raise LookupFailed("material_not_found", "找不到该材料", [f"id={material_id}"])
    return material


@app.exception_handler(PreviewRejected)
async def preview_rejected(request: Request, exc: PreviewRejected) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=400, content=error.model_dump())


@app.exception_handler(LookupFailed)
async def lookup_failed(request: Request, exc: LookupFailed) -> JSONResponse:
    error = ApiError(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=404, content=error.model_dump())
