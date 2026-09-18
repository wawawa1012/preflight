"""材料级预审快照：只读装配，不写库、不做满足判定。"""
from pathlib import Path

from . import rubric_store, storage
from .contracts import (
    MaterialPreflightCitation,
    MaterialPreflightCriterionRow,
    MaterialPreflightMissing,
    MaterialPreflightReport,
    MaterialPreflightSummary,
)
from .storage import RubricNotBound

SCOPE_TMPL = (
    "当前范围尚未发现引用：已核对材料「{filename}」的 {n} 个 Block 上全部已确认关联，"
    "本评分要求已关联 0 条。这不是证明材料外不存在证据。"
)


def _resolve_rubric(material_id: str, db_path: Path) -> tuple:
    binding = storage.get_binding(material_id, db_path=db_path)
    if binding is None:
        raise RubricNotBound("该材料尚未绑定评分标准")
    rubric = rubric_store.get_rubric(binding.rubric_id, binding.rubric_revision)
    if rubric is None:
        raise RubricNotBound(
            "绑定的评分标准版本已不可用", [f"{binding.rubric_id} rev{binding.rubric_revision}"]
        )
    return binding, rubric


def _assemble_criteria(material, rubric, links, annotations, blocks_by_id) -> list[MaterialPreflightCriterionRow]:
    rows: list[MaterialPreflightCriterionRow] = []
    for criterion in rubric.criteria:
        citations: list[MaterialPreflightCitation] = []
        for link in links:
            if link.criterion_id != criterion.id:
                continue
            annotation = annotations.get(link.annotation_id)
            if annotation is None:
                continue  # 关联残留不该发生（FK CASCADE）；跳过，不要崩
            block = blocks_by_id.get(annotation.block_id)
            line = block.locator.index if block else 1
            citations.append(
                MaterialPreflightCitation(
                    link_id=link.id,
                    annotation_id=annotation.id,
                    criterion_id=criterion.id,
                    block_id=annotation.block_id,
                    line_number=line,
                    quote=annotation.source.quote,
                    rationale=link.rationale,
                    proposed_by=link.proposed_by,
                    start=annotation.source.start,
                    end=annotation.source.end,
                )
            )
        if citations:
            rows.append(
                MaterialPreflightCriterionRow(
                    criterion_id=criterion.id,
                    title=criterion.title,
                    requirement=criterion.requirement,
                    verified_citation_count=len(citations),
                    status="has_verified_citations",
                    citations=citations,
                    missing=None,
                )
            )
        else:
            rows.append(
                MaterialPreflightCriterionRow(
                    criterion_id=criterion.id,
                    title=criterion.title,
                    requirement=criterion.requirement,
                    verified_citation_count=0,
                    status="no_verified_citations_in_scope",
                    citations=[],
                    missing=MaterialPreflightMissing(
                        searched_block_count=len(material.blocks),
                        searched_filename=material.filename,
                        explanation=SCOPE_TMPL.format(filename=material.filename, n=len(material.blocks)),
                    ),
                )
            )
    return rows


def _load_scope(material_id: str, db_path: Path):
    links = storage.list_links(material_id, db_path=db_path)
    annotations = {item.id: item for item in storage.list_evidence_annotations(material_id, db_path=db_path)}
    return links, annotations


def assemble_report(
    material_id: str, db_path: Path = storage.DEFAULT_DB_PATH
) -> MaterialPreflightReport | None:
    material = storage.get_material(material_id, db_path=db_path)
    if material is None:
        return None
    _, rubric = _resolve_rubric(material_id, db_path)
    links, annotations = _load_scope(material_id, db_path)
    blocks_by_id = {block.id: block for block in material.blocks}
    rows = _assemble_criteria(material, rubric, links, annotations, blocks_by_id)
    return MaterialPreflightReport(
        material_id=material.id,
        filename=material.filename,
        block_count=len(material.blocks),
        rubric_id=rubric.id,
        rubric_revision=rubric.revision,
        rubric_title=rubric.title,
        criteria=rows,
        blocks=material.blocks,
    )


def assemble_summaries(db_path: Path = storage.DEFAULT_DB_PATH) -> list[MaterialPreflightSummary]:
    summaries: list[MaterialPreflightSummary] = []
    for item in storage.list_materials(db_path=db_path):
        material = storage.get_material(item.id, db_path=db_path)
        if material is None:
            continue
        binding = storage.get_binding(item.id, db_path=db_path)
        if binding is None:
            summaries.append(
                MaterialPreflightSummary(
                    material_id=item.id,
                    filename=item.filename,
                    created_at=item.created_at,
                    block_count=item.block_count,
                    bound=False,
                    rubric_revision=None,
                    verified_citation_count=0,
                    criteria_total=None,
                    criteria_with_citations=None,
                    criteria_without_citations=None,
                )
            )
            continue
        rubric = rubric_store.get_rubric(binding.rubric_id, binding.rubric_revision)
        if rubric is None:
            # 绑定在但标准文件不可用：不猜，计数保持未评估语义（None 由前端展示为未评估）。
            summaries.append(
                MaterialPreflightSummary(
                    material_id=item.id,
                    filename=item.filename,
                    created_at=item.created_at,
                    block_count=item.block_count,
                    bound=True,
                    rubric_revision=binding.rubric_revision,
                    verified_citation_count=0,
                    criteria_total=None,
                    criteria_with_citations=None,
                    criteria_without_citations=None,
                )
            )
            continue
        links, annotations = _load_scope(item.id, db_path)
        blocks_by_id = {block.id: block for block in material.blocks}
        rows = _assemble_criteria(material, rubric, links, annotations, blocks_by_id)
        with_citations = sum(1 for row in rows if row.citations)
        summaries.append(
            MaterialPreflightSummary(
                material_id=item.id,
                filename=item.filename,
                created_at=item.created_at,
                block_count=item.block_count,
                bound=True,
                rubric_revision=binding.rubric_revision,
                verified_citation_count=sum(row.verified_citation_count for row in rows),
                criteria_total=len(rows),
                criteria_with_citations=with_citations,
                criteria_without_citations=len(rows) - with_citations,
            )
        )
    return summaries
