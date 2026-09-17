"""预检 data/rubrics/*.json：复用 rubric_store 的加载器；非法则 exit 1。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.rubric_store import RubricFileError, load_index  # noqa: E402


def main() -> int:
    try:
        index = load_index()
    except RubricFileError as exc:
        print(f"FAIL: {exc}")
        return 1
    if not index:
        print("OK: no rubric files (empty store is valid)")
        return 0
    for (rubric_id, revision), rubric in sorted(index.items()):
        print(f"OK {rubric_id} rev{revision} criteria={len(rubric.criteria)} title={rubric.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
