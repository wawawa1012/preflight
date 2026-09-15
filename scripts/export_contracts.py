"""Run with backend/.venv/Scripts/python.exe from any directory."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.contracts import ContractBundle  # noqa: E402

schema = ContractBundle.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
(ROOT / "contracts/schema.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("Exported contracts/schema.json")
