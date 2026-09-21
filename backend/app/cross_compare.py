"""Leaf B 两材料数值对照：只比较用户显式选中的两个材料 id。

确定性纯函数、零 LLM、零写库：两份材料各自 inspect_statements，合并后复用同材料
数值一致性规则（consistency.find_numeric_findings，宁漏勿错），再只保留引用横跨
两份材料的 Finding；只落在一份材料内部的数值差异全部丢弃（那是同材料报告的范围）。
范围就是传入的两个材料，绝不自动扫描整个材料库；不判断外部真实性，也不给分。

Trust P0（sameVariantSets）：先按材料拆出各自的归一化 (数值, 单位) 集合。
- 两侧集合完全相同（含顺序不同、95 vs 95.0、百分比等价、单位别名）→ 不生成
  跨材料数值差异 Finding；
- 集合只有部分重合、或单位写法不可安全比较 → 降级 needs_review，不假装确定冲突；
- 只有同一度量词、可比较单位、双方数值集合无交集 → 才报 numeric_inconsistency。

范围措辞必须真实：每份材料的关键信号只提取前 MAX_STATEMENTS 条，非全文穷尽。
"""
from .claim_inspector import MAX_STATEMENTS, inspect_statements
from .consistency import find_numeric_findings
from .contracts import Block, ConsistencyCitation, ConsistencyFinding, CrossCompareResponse, SavedMaterial
from .numeric_value import value_key


class SameMaterialCompare(Exception):
    """同一份材料不能与自己对照；由 API 层转 400 + ApiError。"""

    code = "same_material"

    def __init__(self, material_id: str) -> None:
        self.material_id = material_id
        self.message = "不能对照同一份材料，请选择两份不同的材料"
        self.details = [f"id={material_id}"]
        super().__init__(self.message)


def _spans_two_materials(finding: ConsistencyFinding, blocks_by_id: dict[str, Block]) -> bool:
    """引用的 Block 是否来自两个不同的 document_id（当前即两份材料 id）。"""
    document_ids = {blocks_by_id[citation.block_id].document_id for citation in finding.citations}
    return len(document_ids) >= 2


def _side_citations(
    finding: ConsistencyFinding, material: SavedMaterial, blocks_by_id: dict[str, Block]
) -> list[ConsistencyCitation]:
    return [
        citation
        for citation in finding.citations
        if blocks_by_id[citation.block_id].document_id == material.id
    ]


def _side_keys(citations: list[ConsistencyCitation]) -> set[tuple[str, str]]:
    """一侧材料的归一化集合：95 与 95.0 同键，单位别名在提取时已归一。"""
    return {(value_key(citation.value), citation.unit) for citation in citations}


def _display_values(citations: list[ConsistencyCitation]) -> str:
    """按引用既有顺序（Block.ordinal + span）列出这一侧的不同数值，只用于解释文本。"""
    seen: set[tuple[str, str]] = set()
    values: list[str] = []
    for citation in citations:
        key = (value_key(citation.value), citation.unit)
        if key in seen:
            continue
        seen.add(key)
        values.append(f"{citation.value}{citation.unit}")
    return "、".join(values)


def _scope_sentence() -> str:
    return (
        f"仅比较两份材料各自已提取的关键信号（每份最多前 {MAX_STATEMENTS} 条，非全文穷尽检查），"
        "未判定实验条件相同，也未判定任何一方正确。"
    )


def _cross_explanation(
    finding: ConsistencyFinding,
    material_a: SavedMaterial,
    material_b: SavedMaterial,
    side_a: list[ConsistencyCitation],
    side_b: list[ConsistencyCitation],
) -> tuple[str, str] | None:
    """返回 (kind, explanation)；None 表示双方归一化集合相同，不属于跨材料数值差异。"""
    keys_a = _side_keys(side_a)
    keys_b = _side_keys(side_b)
    if not keys_a or not keys_b or keys_a == keys_b:
        return None
    values_a = {value for value, _unit in keys_a}
    values_b = {value for value, _unit in keys_b}
    units = {citation.unit for citation in finding.citations}
    label = finding.measure or "同单位数值"
    left = _display_values(side_a)
    right = _display_values(side_b)
    scope = _scope_sentence()
    if not finding.measure:
        return "needs_review", (
            f"两份材料各有一组数值信号（{left} 对 {right}），但没有共同度量词，"
            f"无法判定是否同一指标；{scope}需人工核对。"
        )
    if len(units) > 1:
        return "needs_review", (
            f"两份材料在「{label}」下的单位缺失或写法不一致（{left} 对 {right}），不能安全比较；"
            f"{scope}需人工核对。"
        )
    if values_a & values_b:
        return "needs_review", (
            f"两份材料在「{label}」下的数值只有部分重合（{left} 对 {right}），"
            f"不能据此判定为冲突；{scope}需人工核对。"
        )
    return "numeric_inconsistency", (
        f"两份材料在「{label}」下没有共同数值（{left} 对 {right}）；"
        f"{scope}请核对后决定以哪一处为准。"
    )


def compare_materials(material_a: SavedMaterial, material_b: SavedMaterial) -> CrossCompareResponse:
    """两份材料的数值对照；引用只横跨一份材料的 Finding 全部丢弃，空列表是合法结果。"""
    blocks = [*material_a.blocks, *material_b.blocks]
    statements = [*inspect_statements(material_a.blocks), *inspect_statements(material_b.blocks)]
    blocks_by_id = {block.id: block for block in blocks}
    findings: list[ConsistencyFinding] = []
    # unit_aware：候选形成阶段保留 (数值, 单位) identity，95 ms vs 95 秒 不被裸数值去重吞掉。
    for finding in find_numeric_findings(statements, blocks, unit_aware=True):
        if not _spans_two_materials(finding, blocks_by_id):
            continue
        verdict = _cross_explanation(
            finding,
            material_a,
            material_b,
            _side_citations(finding, material_a, blocks_by_id),
            _side_citations(finding, material_b, blocks_by_id),
        )
        if verdict is None:
            continue
        kind, explanation = verdict
        findings.append(finding.model_copy(update={"kind": kind, "explanation": explanation}))
    return CrossCompareResponse(
        material_id_a=material_a.id,
        material_id_b=material_b.id,
        filename_a=material_a.filename,
        filename_b=material_b.filename,
        findings=findings,
    )
