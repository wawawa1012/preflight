"""Validate frozen fixture references and reject corrupted citations; no pipeline."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.contracts import (
    AgentProposal,
    ContractBundle,
    CriterionEvidenceLink,
    EvidenceAnnotation,
    MaterialPreflightReport,
    RubricDraft,
    RubricPublish,
    RunReport,
    VersionDiff,
)
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
properties = schema["properties"]
assert properties["diff"]["$ref"] != properties["finding_set_diff_response"]["$ref"], (
    "VersionDiff 与实际 /diffs 的 FindingSetDiffResponse 必须是独立 identity"
)
assert "statement_scan_limit" in schema["$defs"]["ConsistencyFinding"]["properties"], (
    "ConsistencyFinding 必须导出 statement_scan_limit"
)
assert "scoring_sources" in schema["$defs"]["Criterion"]["properties"], (
    "Criterion 必须导出 scoring_sources provenance"
)
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

# Evidence annotation fixture：block 引用一致、quote 与代码点区间一致、篡改必须被拒。
annotation_raw = json.loads((ROOT / "contracts/fixtures/evidence_annotation.json").read_text(encoding="utf-8"))
annotation = EvidenceAnnotation.model_validate(annotation_raw["annotation"])
text = annotation_raw["text"]
assert annotation.block_id == annotation_raw["block_id"] == annotation.source.block_id
assert text[annotation.source.start:annotation.source.end] == annotation.source.quote
tampered = annotation.model_copy(deep=True)
tampered.source.quote = "不存在的引用"
try:
    assert text[tampered.source.start:tampered.source.end] == tampered.source.quote
except AssertionError:
    pass
else:
    raise AssertionError("Tampered evidence quote was accepted")
# Criterion evidence link fixture（synthetic/test-only）：引用一致、rationale 非空、篡改 span 必须被拒。
link_raw = json.loads((ROOT / "contracts/fixtures/criterion_evidence_link.json").read_text(encoding="utf-8"))
link_annotation = EvidenceAnnotation.model_validate(link_raw["annotation"])
link = CriterionEvidenceLink.model_validate(link_raw["link"])
link_text = link_raw["text"]
assert link_raw["test_only"] is True
assert link.annotation_id == link_annotation.id and link.material_id == link_annotation.material_id
assert link_text[link_annotation.source.start:link_annotation.source.end] == link_annotation.source.quote
assert link.rationale.strip(), "rationale must not be blank"
tampered_annotation = link_annotation.model_copy(deep=True)
tampered_annotation.source.end += 1
try:
    assert link_text[tampered_annotation.source.start:tampered_annotation.source.end] == tampered_annotation.source.quote
except AssertionError:
    pass
else:
    raise AssertionError("Tampered link fixture span was accepted")


def check_proposal_fixture(fixture: dict) -> None:
    """Agent proposal fixture：候选状态、验证码与 accept 回填一致性。"""
    proposal = AgentProposal.model_validate(fixture["proposal"])
    fixture_annotation = EvidenceAnnotation.model_validate(fixture["annotation"])
    fixture_link = CriterionEvidenceLink.model_validate(fixture["link"])
    assert proposal.status == "completed" and proposal.candidates
    accepted = [c for c in proposal.candidates if c.review_status == "accepted"]
    assert len(accepted) == 1, "fixture must contain exactly one accepted candidate"
    for candidate in proposal.candidates:
        if candidate.validation_status == "invalid":
            assert candidate.validation_code, "invalid candidate must carry a machine code"
        if candidate.validation_status == "passed":
            assert candidate.validation_code is None
        if candidate.review_status == "accepted":
            assert candidate.created_annotation_id and candidate.created_link_id
        else:
            assert candidate.created_annotation_id is None and candidate.created_link_id is None
            assert candidate.reject_reason is None or candidate.review_status == "rejected"
    winner = accepted[0]
    assert winner.block_id == fixture_annotation.block_id
    assert winner.quote == fixture_annotation.source.quote
    assert winner.created_annotation_id == fixture_annotation.id
    assert winner.created_link_id == fixture_link.id
    assert fixture_link.annotation_id == fixture_annotation.id
    assert fixture_annotation.proposed_by == "agent" and fixture_link.proposed_by == "agent"


proposal_raw = json.loads((ROOT / "contracts/fixtures/proposal_candidate.json").read_text(encoding="utf-8"))
assert proposal_raw["test_only"] is True
check_proposal_fixture(proposal_raw)
tampered_proposal = json.loads(json.dumps(proposal_raw))
tampered_proposal["proposal"]["candidates"][0]["created_link_id"] = "cel_missing"
try:
    check_proposal_fixture(tampered_proposal)
except AssertionError:
    pass
else:
    raise AssertionError("Tampered proposal acceptance backfill was accepted")
tampered_invalid = json.loads(json.dumps(proposal_raw))
tampered_invalid["proposal"]["candidates"][1]["validation_code"] = None
try:
    check_proposal_fixture(tampered_invalid)
except AssertionError:
    pass
else:
    raise AssertionError("Invalid candidate without code was accepted")


def check_preflight_fixture(fixture: dict) -> None:
    """材料预审快照 fixture：行状态、计数一致、零引用必须带范围句。"""
    report = MaterialPreflightReport.model_validate(fixture["report"])
    assert report.criteria, "fixture must contain criteria"
    for row in report.criteria:
        if row.citations:
            assert row.status == "has_verified_citations"
            assert row.missing is None
            assert row.verified_citation_count == len(row.citations) >= 1
            assert all(item.criterion_id == row.criterion_id for item in row.citations)
        else:
            assert row.status == "no_verified_citations_in_scope"
            assert row.verified_citation_count == 0
            missing = row.missing
            assert missing is not None, "zero-citation row must carry scope sentence"
            assert missing.searched_block_count == report.block_count
            assert missing.searched_filename == report.filename
            assert report.filename in missing.explanation
            assert str(report.block_count) in missing.explanation
            assert "当前范围尚未发现引用" in missing.explanation


preflight_raw = json.loads((ROOT / "contracts/fixtures/material_preflight_report.json").read_text(encoding="utf-8"))
assert preflight_raw["test_only"] is True
check_preflight_fixture(preflight_raw)
tampered_row = json.loads(json.dumps(preflight_raw))
tampered_row["report"]["criteria"][1]["missing"] = None
try:
    check_preflight_fixture(tampered_row)
except AssertionError:
    pass
else:
    raise AssertionError("Zero-citation row without scope sentence was accepted")


def check_rubric_draft_fixture(fixture: dict) -> None:
    """Criteria Builder fixture：草稿可编辑、id/order 唯一、评分语义只在源有分数时出现。"""
    draft = RubricDraft.model_validate(fixture["draft"])
    publish = RubricPublish.model_validate({**fixture["draft"], "confirmed": True})
    assert draft.source_text and draft.source_text == publish.source_text
    assert publish.confirmed is True
    ids = [criterion.id for criterion in publish.criteria]
    orders = [criterion.order for criterion in publish.criteria]
    assert len(set(ids)) == len(ids), "criterion ids must be unique"
    assert len(set(orders)) == len(orders), "criterion orders must be unique"
    assert draft.criteria[0].max_score == 20, "scoring present in source must be preserved"
    assert draft.criteria[0].scoring_sources == ["满分 20 分"], "scoring provenance quotes must survive"
    assert draft.criteria[1].max_score is None, "absent scoring must stay null"


rubric_draft_raw = json.loads((ROOT / "contracts/fixtures/rubric_draft.json").read_text(encoding="utf-8"))
assert rubric_draft_raw["test_only"] is True
check_rubric_draft_fixture(rubric_draft_raw)
tampered_draft = json.loads(json.dumps(rubric_draft_raw))
tampered_draft["draft"]["criteria"][1]["id"] = tampered_draft["draft"]["criteria"][0]["id"]
try:
    check_rubric_draft_fixture(tampered_draft)
except AssertionError:
    pass
else:
    raise AssertionError("Duplicate criterion ids were accepted")
tampered_publish = {**rubric_draft_raw["draft"], "confirmed": False}
try:
    RubricPublish.model_validate(tampered_publish)
except ValidationError:
    pass
else:
    raise AssertionError("Unconfirmed rubric publish was accepted")
print(
    "PASS: schema freshness, fixture structure/references, quote checks, "
    "evidence annotation checks, criterion link checks, proposal checks, preflight report checks, "
    "rubric draft checks, negative cases"
)
