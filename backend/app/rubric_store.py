"""只读评分标准文件仓：data/rubrics/*.json → (rubric_id, revision) 索引。

启动时全量加载并逐份用冻结的 Rubric 模型校验；非法文件或重复键直接抛 RubricFileError
（fail-fast，不降级为空列表继续跑）；目录为空是合法状态（空索引）。
Criterion ID 固定写在文件里；新版本 = 新文件，旧文件永不改动。
"""
import json
from pathlib import Path

from pydantic import ValidationError

from .contracts import Rubric

DEFAULT_RUBRIC_DIR = Path(__file__).resolve().parents[2] / "data" / "rubrics"

_index: dict[tuple[str, int], Rubric] = {}


class RubricFileError(Exception):
    """评分标准文件非法或重复；由启动与校验脚本直接上报。"""


def load_index(directory: Path = DEFAULT_RUBRIC_DIR) -> dict[tuple[str, int], Rubric]:
    directory.mkdir(parents=True, exist_ok=True)
    index: dict[tuple[str, int], Rubric] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RubricFileError(f"{path.name}: 无法读取或解析 JSON（{exc}）") from exc
        try:
            rubric = Rubric.model_validate(raw)
        except ValidationError as exc:
            raise RubricFileError(f"{path.name}: 不符合 Rubric 契约（{exc.error_count()} 处错误）") from exc
        key = (rubric.id, rubric.revision)
        if key in index:
            raise RubricFileError(f"{path.name}: 重复的 (rubric_id, revision) {key}")
        index[key] = rubric
    return index


def set_index(index: dict[tuple[str, int], Rubric]) -> None:
    """lifespan 注入加载结果；测试也用它注入合成标准（test-only，不入 data/）。"""
    global _index
    _index = dict(index)


def reset_index() -> None:
    global _index
    _index = {}


def list_rubrics() -> list[Rubric]:
    return [rubric for _, rubric in sorted(_index.items())]


def get_rubric(rubric_id: str, revision: int) -> Rubric | None:
    return _index.get((rubric_id, revision))
