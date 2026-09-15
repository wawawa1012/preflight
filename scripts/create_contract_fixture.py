"""Deterministic, synthetic contract example. This does not analyze documents."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.contracts import RunReport, VersionDiff

texts = ["Accuracy 95% on demo-set v1.", "Accuracy 89.7% on demo-set v1."]
documents = [
    {"id": f"doc_{i}", "material_version_id": "version_1", "logical_key": key,
     "filename": name, "format": fmt, "sha256": hashlib.sha256(text.encode()).hexdigest(),
     "parse_status": "ready"}
    for i, (key, name, fmt, text) in enumerate(zip(
        ["presentation", "test_report"], ["demo.pptx", "test_report.pdf"], ["pptx", "pdf"], texts), 1)
]
blocks = [
    {"id": f"block_{i}", "document_id": f"doc_{i}", "ordinal": 0, "text": text,
     "locator": {"kind": kind, "index": position, "block_index": 1}}
    for i, (text, kind, position) in enumerate(zip(texts, ["slide", "page"], [3, 17]), 1)
]
spans = [{"block_id": f"block_{i}", "start": 0, "end": len(text), "quote": text}
         for i, text in enumerate(texts, 1)]
report = {
    "contract_version": "0.1.0",
    "project": {"id": "project_demo", "name": "Synthetic contract example"},
    "material_version": {"id": "version_1", "project_id": "project_demo", "label": "Before (mock)", "document_ids": ["doc_1", "doc_2"]},
    "rubric": {"id": "rubric_demo", "revision": 1, "title": "Demo rubric — not official AIC",
               "source_note": "Artificial fixture; no source files were parsed.",
               "criteria": [{"id": "c_accuracy", "title": "Accuracy evidence", "requirement": "Report consistent accuracy under identical conditions.", "required_evidence": ["test result"]},
                            {"id": "c_reliability", "title": "Reliability", "requirement": "Provide a repeatable reliability test.", "required_evidence": ["reliability test"]}]},
    "run": {"id": "run_1", "project_id": "project_demo", "material_version_id": "version_1", "rubric_id": "rubric_demo", "rubric_revision": 1,
            "mode": "mock", "status": "completed", "stage": "done", "prompt_version": "fixture-only"},
    "documents": documents, "blocks": blocks,
    "claims": [{"id": f"claim_{i}", "criterion_ids": ["c_accuracy"], "text": text, "source": spans[i-1], "comparison_key": "accuracy:demo-set:v1"} for i, text in enumerate(texts, 1)],
    "evidence": [{"id": f"evidence_{i}", "criterion_id": "c_accuracy", "claim_id": "claim_1", "source": spans[i-1], "relation": "context" if i == 1 else "contradicts", "citation_valid": True} for i in (1, 2)],
    "findings": [
        {"id": "finding_conflict", "fingerprint": "c_accuracy:conflict:accuracy:demo-set:v1:presentation:test_report", "criterion_id": "c_accuracy", "kind": "cross_document_conflict", "severity": "critical", "title": "Accuracy differs", "explanation": "95% versus 89.7% under the same stated conditions.", "claim_ids": ["claim_1", "claim_2"], "evidence_ids": ["evidence_1", "evidence_2"], "searched_document_ids": ["doc_1", "doc_2"]},
        {"id": "finding_missing", "fingerprint": "c_reliability:missing_evidence", "criterion_id": "c_reliability", "kind": "missing_evidence", "severity": "warning", "title": "Reliability test missing", "explanation": "No reliability test in the mock search scope.", "claim_ids": [], "evidence_ids": [], "searched_document_ids": ["doc_1", "doc_2"]}],
    "repairs": [{"id": "repair_1", "finding_id": "finding_conflict", "instruction": "Verify the test result and update the presentation, then rerun.", "status": "todo"}],
    "assessments": [{"criterion_id": "c_accuracy", "status": "conflict", "evidence_ids": ["evidence_1", "evidence_2"], "finding_ids": ["finding_conflict"]},
                    {"criterion_id": "c_reliability", "status": "missing", "evidence_ids": [], "finding_ids": ["finding_missing"]}],
    "metrics": {"submission_readiness": "blocked", "rubric_coverage": 0, "verified_evidence": 2, "critical_risks": 1, "resolved_risks": None},
    "review_questions": [{"id": "question_1", "finding_id": "finding_conflict", "question": "Which accuracy is correct?", "why": "The two materials disagree.", "outline": ["Check the shared evaluation conditions", "Cite the corrected result"], "evidence_ids": ["evidence_1", "evidence_2"]}]
}
parsed = RunReport.model_validate(report)
(ROOT / "contracts/fixtures/report.json").write_text(parsed.model_dump_json(indent=2) + "\n", encoding="utf-8")
# No fictional after-run: Phase 0 only demonstrates an explicit non-comparable response.
diff = VersionDiff(before_run_id="run_1", after_run_id="run_pending", comparable=False,
                   reason="The after run is not completed; D1 will add full three-act fixtures.", entries=[])
(ROOT / "contracts/fixtures/diff.json").write_text(diff.model_dump_json(indent=2) + "\n", encoding="utf-8")
print("Wrote synthetic fixtures (not benchmark results)")
