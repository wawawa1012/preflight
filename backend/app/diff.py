"""I11 修改效果对照：同一份材料修改前后两版 Finding 集合的差集。

纯函数、零 LLM、零写库：两份材料各自 inspect_statements + find_numeric_findings（同材料
数值一致性规则，宁漏勿错），把 Finding 指纹化为 (kind, measure, tuple(sorted(values)))，
再按指纹分组：

- resolved  = before 有、after 没有的指纹（取 before 一侧 Finding）；只表示
  「修改后本次规则未再检出同一 finding identity」，不代表事实已正确、风险已解决、
  修改一定有效；
- unchanged = 两侧都有的指纹（取 after 一侧 Finding，引用指向当前版本原文）
- new       = after 有、before 没有的指纹（取 after 一侧 Finding）

不做两份材料之间的数值对照（那是 cross_compare 的范围：跨文档同度量词数值对照）；
不判断外部真实性，也不给分。空分组是合法结果，只说明该组没有对应的 Finding。

请求/响应契约是 contracts.py 的 FindingSetDiffRequest / FindingSetDiffResponse（已进入
ContractBundle 导出链，和 Run-based VersionDiff 是两个独立 identity）。路由挂到
POST /api/v1/diffs：同 id 转 400 + ApiError(code=same_material)，缺一 404。
"""
from .claim_inspector import inspect_statements
from .consistency import find_numeric_findings
from .contracts import ConsistencyFinding, FindingSetDiffRequest, FindingSetDiffResponse, SavedMaterial

# Finding 指纹：kind 区分数值不一致与降级待人工判断；度量词 + 排序后的数值集合定同一条问题。
Fingerprint = tuple[str, str, tuple[str, ...]]


class SameMaterialDiff(Exception):
    """同一份材料不能与自己做修改前后对照；由 API 层转 400 + ApiError（code=same_material）。"""

    code = "same_material"

    def __init__(self, material_id: str) -> None:
        self.material_id = material_id
        self.message = "不能对照同一份材料，请选择两份不同的材料"
        self.details = [f"id={material_id}"]
        super().__init__(self.message)


DIFF_SEMANTICS_NOTE = (
    "resolved 只表示修改后本次规则未再检出同一 finding identity（kind + measure + 数值集合），"
    "不代表事实已正确、风险已解决或修改一定有效；三组结果都只是本规则的输出。"
)


def fingerprint_finding(finding: ConsistencyFinding) -> Fingerprint:
    """Finding 指纹：kind + 度量词 + 排序后的数值集合；指纹相同即同一条问题。"""
    return (finding.kind, finding.measure, tuple(sorted(finding.values)))


def _findings_by_fingerprint(material: SavedMaterial) -> dict[Fingerprint, ConsistencyFinding]:
    """一份材料自己的数值一致性 Finding，按指纹去重（首次出现为准，保序）。"""
    findings = find_numeric_findings(inspect_statements(material.blocks), material.blocks)
    by_key: dict[Fingerprint, ConsistencyFinding] = {}
    for finding in findings:
        by_key.setdefault(fingerprint_finding(finding), finding)
    return by_key


def diff_findings(before: SavedMaterial, after: SavedMaterial) -> FindingSetDiffResponse:
    """同一份材料修改前后两个版本的 Finding 集合差异；同 id 拒绝，空分组合法。"""
    if before.id == after.id:
        raise SameMaterialDiff(before.id)
    before_by_key = _findings_by_fingerprint(before)
    after_by_key = _findings_by_fingerprint(after)
    return FindingSetDiffResponse(
        material_id_before=before.id,
        material_id_after=after.id,
        filename_before=before.filename,
        filename_after=after.filename,
        note=DIFF_SEMANTICS_NOTE,
        resolved=[finding for key, finding in before_by_key.items() if key not in after_by_key],
        unchanged=[finding for key, finding in after_by_key.items() if key in before_by_key],
        new=[finding for key, finding in after_by_key.items() if key not in before_by_key],
    )
