"""Leaf B 两材料数值对照：只比较用户显式选中的两个材料 id。

确定性纯函数、零 LLM、零写库：两份材料各自 inspect_statements，合并后复用同材料
数值一致性规则（consistency.find_numeric_findings，宁漏勿错），再只保留引用横跨
两份材料的 Finding；只落在一份材料内部的数值差异全部丢弃（那是同材料报告的范围）。
范围就是传入的两个材料，绝不自动扫描整个材料库；不判断外部真实性，也不给分。
"""
from .claim_inspector import inspect_statements
from .consistency import find_numeric_findings
from .contracts import Block, ConsistencyFinding, CrossCompareResponse, SavedMaterial


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


def compare_materials(material_a: SavedMaterial, material_b: SavedMaterial) -> CrossCompareResponse:
    """两份材料的数值对照；引用只横跨一份材料的 Finding 全部丢弃，空列表是合法结果。"""
    blocks = [*material_a.blocks, *material_b.blocks]
    statements = [*inspect_statements(material_a.blocks), *inspect_statements(material_b.blocks)]
    blocks_by_id = {block.id: block for block in blocks}
    findings = [
        finding
        for finding in find_numeric_findings(statements, blocks)
        if _spans_two_materials(finding, blocks_by_id)
    ]
    return CrossCompareResponse(
        material_id_a=material_a.id,
        material_id_b=material_b.id,
        filename_a=material_a.filename,
        filename_b=material_b.filename,
        findings=findings,
    )
