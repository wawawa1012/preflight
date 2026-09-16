"""只读 mock report：复用现有 contract 模型构建并校验；不接解析、LLM 或数据库。"""
from .contracts import RunReport


def _span(blocks: dict[str, dict], block_id: str, quote: str) -> dict:
    """按原文索引生成 Span，保证 start/end 与 quote 严格一致。"""
    text = blocks[block_id]["text"]
    start = text.index(quote)
    return {"block_id": block_id, "start": start, "end": start + len(quote), "quote": quote}


_BLOCKS = [
    {
        "id": "blk_ppt_12",
        "document_id": "doc_ppt",
        "ordinal": 11,
        "text": "本材料版本 v3：在统一评测集 v2、标准推理设置（standard inference settings）下，模型准确率（Accuracy）达到 95%，优于基线 7 个百分点。",
        "locator": {"kind": "slide", "index": 12, "end_index": None, "block_index": 3},
    },
    {
        "id": "blk_report_17",
        "document_id": "doc_report",
        "ordinal": 40,
        "text": "本材料版本 v3 — Table 4: Accuracy = 89.7% (same test-set v2, standard inference settings).",
        "locator": {"kind": "page", "index": 17, "end_index": None, "block_index": 2},
    },
    {
        "id": "blk_proposal_3",
        "document_id": "doc_proposal",
        "ordinal": 2,
        "text": "本项目提出行业首创的端到端预检方案。",
        "locator": {"kind": "line", "index": 21, "end_index": None, "block_index": 3},
    },
]

_BLOCK_INDEX = {block["id"]: block for block in _BLOCKS}

_MATERIAL_DOCUMENT_IDS = ["doc_ppt", "doc_report", "doc_proposal", "doc_budget"]

MOCK_REPORT = RunReport.model_validate(
    {
        "contract_version": "0.1.0",
        "project": {"id": "project_aic2026", "name": "Preflight · AIC 2026"},
        "material_version": {
            "id": "version_v3",
            "project_id": "project_aic2026",
            "label": "v3 提交版（Mock）",
            "document_ids": _MATERIAL_DOCUMENT_IDS,
        },
        "rubric": {
            "id": "rubric_demo",
            "revision": 1,
            "title": "演示 Rubric（非官方 AIC）",
            "source_note": "AIC 官方 rubric 尚未提供；本 rubric 仅用于结构演示，不是官方评分标准。",
            "criteria": [
                {
                    "id": "c_accuracy",
                    "title": "性能指标可核实",
                    "requirement": "同一指标必须在所有材料中使用相同数据集与条件，并给出来源。",
                    "required_evidence": ["测试结果"],
                },
                {
                    "id": "c_cost",
                    "title": "成本与可行性",
                    "requirement": "成本数字必须可溯源，并说明测算依据。",
                    "required_evidence": ["成本测算"],
                },
                {
                    "id": "c_innovation",
                    "title": "创新性",
                    "requirement": "“首创”一类表述必须提供对比依据。",
                    "required_evidence": ["对比材料"],
                },
            ],
        },
        "run": {
            "id": "run_mock_1",
            "project_id": "project_aic2026",
            "material_version_id": "version_v3",
            "rubric_id": "rubric_demo",
            "rubric_revision": 1,
            "mode": "mock",
            "status": "completed",
            "stage": "done",
            "provider": None,
            "model": None,
            "prompt_version": "mock-0.1",
            "error": None,
        },
        "documents": [
            {
                "id": "doc_ppt",
                "material_version_id": "version_v3",
                "logical_key": "pitch",
                "filename": "路演PPT.pptx",
                "format": "pptx",
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "parse_status": "ready",
            },
            {
                "id": "doc_report",
                "material_version_id": "version_v3",
                "logical_key": "test_report",
                "filename": "TestReport.pdf",
                "format": "pdf",
                "sha256": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
                "parse_status": "ready",
            },
            {
                "id": "doc_proposal",
                "material_version_id": "version_v3",
                "logical_key": "proposal",
                "filename": "技术方案.md",
                "format": "md",
                "sha256": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
                "parse_status": "ready",
            },
            {
                "id": "doc_budget",
                "material_version_id": "version_v3",
                "logical_key": "budget",
                "filename": "预算说明.docx",
                "format": "docx",
                "sha256": "ffeeddccbbaa99887766554433221100ffeeddccbbaa99887766554433221100",
                "parse_status": "ready",
            },
        ],
        "blocks": _BLOCKS,
        "claims": [
            {
                "id": "claim_accuracy",
                "criterion_ids": ["c_accuracy"],
                "text": "模型准确率（Accuracy）达到 95%",
                "source": _span(_BLOCK_INDEX, "blk_ppt_12", "模型准确率（Accuracy）达到 95%"),
                "comparison_key": "accuracy / test-set v2 / standard inference / version v3",
            },
            {
                "id": "claim_first",
                "criterion_ids": ["c_innovation"],
                "text": "行业首创的端到端预检方案",
                "source": _span(_BLOCK_INDEX, "blk_proposal_3", "行业首创的端到端预检方案"),
                "comparison_key": None,
            },
        ],
        "evidence": [
            {
                "id": "evidence_ppt_95",
                "criterion_id": "c_accuracy",
                "claim_id": "claim_accuracy",
                "source": _span(_BLOCK_INDEX, "blk_ppt_12", "模型准确率（Accuracy）达到 95%"),
                "relation": "context",
                "citation_valid": True,
                "validation_error": None,
            },
            {
                "id": "evidence_report_897",
                "criterion_id": "c_accuracy",
                "claim_id": "claim_accuracy",
                "source": _span(_BLOCK_INDEX, "blk_report_17", "Accuracy = 89.7%"),
                "relation": "contradicts",
                "citation_valid": True,
                "validation_error": None,
            },
        ],
        "findings": [
            {
                "id": "finding_accuracy_conflict",
                "fingerprint": "c_accuracy:conflict:accuracy:test-set-v2:version-v3",
                "criterion_id": "c_accuracy",
                "kind": "cross_document_conflict",
                "severity": "critical",
                "title": "同一指标数字冲突：准确率 95% vs 89.7%",
                "explanation": (
                    "PPT 第 12 页声称准确率 95%；测试报告第 17 页在同一评测集 v2、标准推理条件下实测 89.7%。"
                    "两者属于同一指标、同一数据集/条件、同一材料版本，不能同时成立。"
                ),
                "claim_ids": ["claim_accuracy"],
                "evidence_ids": ["evidence_ppt_95", "evidence_report_897"],
                "searched_document_ids": _MATERIAL_DOCUMENT_IDS,
            },
            {
                "id": "finding_missing_cost",
                "fingerprint": "c_cost:missing_evidence:version-v3",
                "criterion_id": "c_cost",
                "kind": "missing_evidence",
                "severity": "warning",
                "title": "缺少成本测算的可引用证据",
                "explanation": "已检索本材料版本的 4 份文档，未找到支持成本测算的原文段落。",
                "claim_ids": [],
                "evidence_ids": [],
                "searched_document_ids": _MATERIAL_DOCUMENT_IDS,
            },
            {
                "id": "finding_overclaim_first",
                "fingerprint": "c_innovation:overclaim:version-v3",
                "criterion_id": "c_innovation",
                "kind": "overclaim",
                "severity": "info",
                "title": "“行业首创”缺少对比依据",
                "explanation": "该声明在现有材料中没有得到对比资料的支撑。",
                "claim_ids": ["claim_first"],
                "evidence_ids": [],
                "searched_document_ids": _MATERIAL_DOCUMENT_IDS,
            },
        ],
        "repairs": [],
        "assessments": [
            {
                "criterion_id": "c_accuracy",
                "status": "conflict",
                "evidence_ids": ["evidence_ppt_95", "evidence_report_897"],
                "finding_ids": ["finding_accuracy_conflict"],
            },
            {
                "criterion_id": "c_cost",
                "status": "missing",
                "evidence_ids": [],
                "finding_ids": ["finding_missing_cost"],
            },
            {
                "criterion_id": "c_innovation",
                "status": "weak",
                "evidence_ids": [],
                "finding_ids": ["finding_overclaim_first"],
            },
        ],
        "metrics": {
            "submission_readiness": "blocked",
            "rubric_coverage": 0.0,
            "verified_evidence": 2,
            "critical_risks": 1,
            "resolved_risks": None,
        },
        "review_questions": [],
    }
)
