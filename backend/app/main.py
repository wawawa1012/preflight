from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal

app = FastAPI(title="Preflight", version="0.1.0")


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    contract_version: Literal["0.1.0"] = "0.1.0"


@app.get("/api/v1/health", response_model=Health)
def health() -> Health:
    return Health()
