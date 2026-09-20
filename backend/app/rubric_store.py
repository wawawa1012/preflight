"""只读评分标准文件仓：data/rubrics/*.json → (rubric_id, revision) 索引。

启动时全量加载并逐份用冻结的 Rubric 模型校验；非法文件或重复键直接抛 RubricFileError
（fail-fast，不降级为空列表继续跑）；目录为空是合法状态（空索引）。
Criterion ID 固定写在文件里；新版本 = 新文件，旧文件永不改动。
"""
import json
import os
import threading
import uuid
from pathlib import Path

from pydantic import ValidationError

from .contracts import Criterion, CriterionDraft, Rubric, RubricPublish
from .scoring_provenance import validate_aggregation_rule, validate_imported_scoring

DEFAULT_RUBRIC_DIR = Path(__file__).resolve().parents[2] / "data" / "rubrics"

_index: dict[tuple[str, int], Rubric] = {}
_publish_lock = threading.Lock()


class RubricRejected(Exception):
    """发布输入被拒绝（400 invalid_rubric）；不写入任何文件。"""

    code = "invalid_rubric"

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


def _validated_criteria(drafts: list[CriterionDraft]) -> list[Criterion]:
    """发布前校验草稿：id 与 order 均不得重复，id/title/requirement 不得空白，按 order 排序。"""
    ids = [draft.id.strip() for draft in drafts]
    orders = [draft.order for draft in drafts]
    problems: list[str] = []
    if any(not item for item in ids):
        problems.append("criterion id 不能为空白")
    if len(set(ids)) != len(ids):
        problems.append("criterion id 不能重复")
    if len(set(orders)) != len(orders):
        problems.append("criterion order 不能重复")
    for draft in drafts:
        if not draft.title.strip():
            problems.append(f"{draft.id}: title 不能为空白")
        if not draft.requirement.strip():
            problems.append(f"{draft.id}: requirement 不能为空白")
        if any(not item.strip() for item in draft.required_evidence):
            problems.append(f"{draft.id}: required_evidence 不能含空白项")
    if problems:
        raise RubricRejected("评分标准草稿校验失败", problems)
    return [
        Criterion(**draft.model_dump(exclude={"order"}))
        for draft in sorted(drafts, key=lambda item: item.order)
    ]


def _provenance_problems(draft: RubricPublish) -> list[str]:
    """plain_text/markdown 来源在 publish 时重新执行评分 provenance 校验（confirmed 不能豁免）。

    rubric_json 的结构化原文与 manual 的用户自撰规则不走此校验。
    """
    if draft.source_type not in ("plain_text", "markdown"):
        return []
    problems = validate_aggregation_rule(draft.aggregation_rule, draft.aggregation_rule_source, draft.source_text)
    for criterion in draft.criteria:
        problems.extend(validate_imported_scoring(criterion, draft.source_text))
    return problems


def publish(draft: RubricPublish, directory: Path | None = None) -> Rubric:
    """把已确认的草稿发布为不可变新文件；每次 publish 都是全新 identity，绝不覆盖旧文件。

    校验失败抛 RubricRejected（400），不落盘、不进索引；成功后才进入本进程索引。
    """
    target_dir = directory if directory is not None else DEFAULT_RUBRIC_DIR
    if not draft.title.strip() or not draft.source_note.strip():
        raise RubricRejected("title/source_note 不能为空白")
    criteria = _validated_criteria(draft.criteria)
    problems = _provenance_problems(draft)
    if problems:
        raise RubricRejected("评分语义来源校验失败", problems)
    rubric = Rubric(
        id=f"rubric_{uuid.uuid4().hex}",
        revision=1,
        title=draft.title,
        source_note=draft.source_note,
        criteria=criteria,
        source_text=draft.source_text,
        source_type=draft.source_type,
        source_name=draft.source_name,
        aggregation_rule=draft.aggregation_rule,
        aggregation_rule_source=draft.aggregation_rule_source if draft.aggregation_rule else None,
        model_assisted=draft.model_assisted,
    )
    with _publish_lock:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{rubric.id}.json"
        temporary = target_dir / f".{rubric.id}.pending"
        try:
            with temporary.open("x", encoding="utf-8") as file:
                file.write(rubric.model_dump_json(indent=2))
                file.flush()
                os.fsync(file.fileno())
            temporary.rename(target)
        finally:
            temporary.unlink(missing_ok=True)
        _index[(rubric.id, rubric.revision)] = rubric
    return rubric


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
