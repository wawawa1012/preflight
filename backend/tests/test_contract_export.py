"""Contract export chain：contracts.py → contracts/schema.json → frontend generated contracts.ts。

Gate 要求实际 /api/v1/diffs 的 FindingSetDiffResponse 进入正式导出链，且与 Run-based
VersionDiff 保持独立 identity；generated TS 必须包含 Revision / Criteria Builder /
scoring metadata / statement_scan_limit / DiffResponse.note / Review contracts。
"""
import json
import unittest
from pathlib import Path

from app.contracts import ContractBundle, FindingSetDiffResponse, VersionDiff

ROOT = Path(__file__).resolve().parents[2]


class ContractExportTest(unittest.TestCase):
    def test_schema_json_matches_contracts_py(self) -> None:
        schema = json.loads((ROOT / "contracts/schema.json").read_text(encoding="utf-8"))
        schema.pop("$schema")
        self.assertEqual(schema, ContractBundle.model_json_schema(), "schema.json 过期，请重新导出")

    def test_bundle_exports_expected_identities(self) -> None:
        fields = set(ContractBundle.model_fields)
        for name in (
            "finding_set_diff_request",
            "finding_set_diff_response",
            "rubric_draft_request",
            "rubric_draft",
            "rubric_publish",
            "criterion_draft",
            "rubric_level",
            "review",
            "review_create",
            "review_detail",
            "review_material",
            "material_revision",
            "material_revision_create",
            "material_revision_created",
            "revision_parent",
            "revision_child",
            "revision_context",
            "editable_source",
            "consistency_finding",
            "grill_request",
            "grill_question",
            "coach_source_ref",
            "response_coach_request",
            "response_coach_response",
            "coach_claim",
            "coach_source",
        ):
            self.assertIn(name, fields, f"ContractBundle 缺少 {name}")
        self.assertIsNot(FindingSetDiffResponse, VersionDiff)

    def test_finding_set_diff_and_version_diff_are_distinct_in_schema(self) -> None:
        properties = ContractBundle.model_json_schema()["properties"]
        self.assertIn("diff", properties)
        self.assertIn("finding_set_diff_response", properties)
        self.assertNotEqual(properties["diff"], properties["finding_set_diff_response"])
        response_ref = properties["finding_set_diff_response"]["$ref"]
        self.assertTrue(response_ref.endswith("FindingSetDiffResponse"))

    def test_generated_typescript_is_fresh(self) -> None:
        source = (ROOT / "frontend/src/types/contracts.ts").read_text(encoding="utf-8")
        for marker in (
            "FindingSetDiffResponse",
            "statement_scan_limit",
            "scoring_sources",
            "aggregation_rule_source",
            "source_name",
            "RubricDraft",
            "MaterialRevision",
            "ReviewDetail",
            "GrillQuestion",
            "ResponseCoachRequest",
            "ResponseCoachResponse",
            "CoachSource",
        ):
            self.assertIn(marker, source, f"generated contracts.ts 缺少 {marker}；请运行 npm.cmd --prefix frontend run contracts")
        self.assertIn("VersionDiff", source)
        # 真实 /diffs 响应的三个分组与 note 必须在导出类型里；statement_scan_limit 是必需字段。
        interface_start = source.index("export interface FindingSetDiffResponse")
        interface_body = source[interface_start : source.index("}", interface_start)]
        for field in ("material_id_before", "filename_before", "note", "resolved", "unchanged", "new"):
            self.assertIn(field, interface_body)
        self.assertIn("statement_scan_limit: ", source)
        self.assertNotIn("statement_scan_limit?: ", source)
        # Sprint 2：Grill preparation 与 Coach source authority 必须在生成类型里。
        grill_start = source.index("export interface GrillQuestion")
        grill_body = source[grill_start : source.index("}", grill_start)]
        for field in ("trigger", "why", "preparation"):
            self.assertIn(field, grill_body)
        self.assertIn("CoachSource", source)


if __name__ == "__main__":
    unittest.main()
