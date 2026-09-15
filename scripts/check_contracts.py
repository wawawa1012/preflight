"""Validate frozen fixture references and reject corrupted citations; no pipeline."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.contracts import ContractBundle, RunReport, VersionDiff
from pydantic import ValidationError


def check_report(report: RunReport) -> None:
    def indexed(items):
        result = {item.id: item for item in items}
        assert len(result) == len(items), "Duplicate IDs"
        return result

    docs = indexed(report.documents)
    blocks = indexed(report.blocks)
    criteria = indexed(report.rubric.criteria)
    claims = indexed(report.claims)
    evidence = indexed(report.evidence)
    findings = indexed(report.findings)
    assert set(report.material_version.document_ids) == set(docs)
    assert report.run.project_id == report.material_version.project_id == report.project.id
    assert report.run.material_version_id == report.material_version.id
    assert (report.run.rubric_id, report.run.rubric_revision) == (report.rubric.id, report.rubric.revision)
    for doc in docs.values():
        assert doc.material_version_id == report.material_version.id
    for block in blocks.values():
        doc = docs[block.document_id]
        assert block.locator.kind == {"pdf": "page", "pptx": "slide", "docx": "paragraph", "md": "line"}[doc.format]

    def check_span(span):
        text = blocks[span.block_id].text
        assert 0 <= span.start < span.end <= len(text), "Invalid span offsets"
        assert text[span.start:span.end] == span.quote, "Quote mismatch"

    for claim in claims.values():
        check_span(claim.source)
        assert set(claim.criterion_ids) <= criteria.keys()
    for item in evidence.values():
        check_span(item.source)
        assert item.criterion_id in criteria
        assert item.claim_id is None or item.claim_id in claims
    for finding in findings.values():
        assert finding.criterion_id in criteria
        assert set(finding.claim_ids) <= claims.keys()
        assert set(finding.evidence_ids) <= evidence.keys()
        assert set(finding.searched_document_ids) <= docs.keys()
        if finding.kind == "cross_document_conflict":
            assert len({blocks[evidence[eid].source.block_id].document_id for eid in finding.evidence_ids}) >= 2
            assert all(evidence[eid].citation_valid for eid in finding.evidence_ids)
        if finding.kind == "missing_evidence":
            assert finding.searched_document_ids
    for repair in report.repairs:
        assert repair.finding_id in findings
    for question in report.review_questions:
        assert question.finding_id in findings
        assert set(question.evidence_ids) <= evidence.keys()
    assert len(report.assessments) == len(criteria)
    assert {a.criterion_id for a in report.assessments} == criteria.keys()
    for assessment in report.assessments:
        assert set(assessment.evidence_ids) <= evidence.keys()
        assert set(assessment.finding_ids) <= findings.keys()
    assert report.metrics.verified_evidence == sum(e.citation_valid for e in evidence.values())
    assert report.metrics.critical_risks == sum(f.severity == "critical" for f in findings.values())


schema = json.loads((ROOT / "contracts/schema.json").read_text(encoding="utf-8"))
schema.pop("$schema")
assert schema == ContractBundle.model_json_schema(), "Stale JSON Schema; regenerate"
raw = (ROOT / "contracts/fixtures/report.json").read_text(encoding="utf-8")
report = RunReport.model_validate_json(raw)
check_report(report)
diff = VersionDiff.model_validate_json((ROOT / "contracts/fixtures/diff.json").read_text(encoding="utf-8"))
assert not diff.comparable and diff.reason and not diff.entries
for corruption in ("quote", "block_id"):
    bad = report.model_copy(deep=True)
    setattr(bad.evidence[0].source, corruption, "nonexistent")
    try:
        check_report(bad)
    except (AssertionError, KeyError):
        pass
    else:
        raise AssertionError(f"Failed to reject corrupted {corruption}")
bad_json = json.loads(raw)
bad_json["unexpected"] = True
try:
    RunReport.model_validate(bad_json)
except ValidationError:
    pass
else:
    raise AssertionError("Unknown field was accepted")
print("PASS: schema freshness, fixture structure/references, quote checks, negative cases")
