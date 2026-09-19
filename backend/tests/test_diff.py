"""I11 修改效果对照（同一材料修改前后 Finding 集合差集）——纯函数层单元测试。

纪律：复用同材料数值一致性规则（宁漏勿错）；指纹 (kind, measure, tuple(sorted(values)))；
resolved / unchanged / new 三分组，空分组合法；同 id 拒绝（code=same_material）；
不调 LLM、不落库、不新增表；不做跨材料数值对照（那是 cross_compare 的范围）。
"""
import unittest
from pathlib import Path

from app import diff
from app.contracts import Block, Locator, SavedMaterial


def material_of(material_id: str, filename: str, texts: list[str]) -> SavedMaterial:
    """内存 Blocks：每个文本一行一块，line_number 依次 1..n（不触库、不触预览）。"""
    blocks = [
        Block(
            id=f"{material_id}-blk-{index}",
            document_id=material_id,
            ordinal=index,
            text=text,
            locator=Locator(kind="line", index=index, block_index=index),
        )
        for index, text in enumerate(texts, start=1)
    ]
    return SavedMaterial(
        id=material_id,
        filename=filename,
        size_bytes=sum(len(text.encode("utf-8")) for text in texts),
        sha256="a" * 64,
        line_count=len(texts),
        created_at="2026-09-19T00:00:00+00:00",
        blocks=blocks,
    )


class DiffFindingsPureTest(unittest.TestCase):
    """纯函数层：零数据库、零网络、零 LLM。"""

    def test_resolved_finding_disappears_after_unification(self) -> None:
        # 修改前 88% vs 93% 是数值不一致；修改后统一为 93% —— 这条应进 resolved。
        before = material_of("mat_before", "draft.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 93%。", "复现实验的准确率达到 93%。"])

        result = diff.diff_findings(before, after)

        self.assertEqual(result.material_id_before, "mat_before")
        self.assertEqual(result.material_id_after, "mat_after")
        self.assertEqual(result.filename_before, "draft.md")
        self.assertEqual(result.filename_after, "revised.md")
        self.assertEqual(len(result.resolved), 1)
        finding = result.resolved[0]
        self.assertEqual(finding.kind, "numeric_inconsistency")
        self.assertEqual(finding.measure, "准确率")
        self.assertEqual(sorted(finding.values), ["88%", "93%"])
        self.assertEqual(finding.material_id, "mat_before")
        self.assertEqual(result.unchanged, [])
        self.assertEqual(result.new, [])

    def test_unchanged_finding_keeps_current_side_citation(self) -> None:
        # 两侧指纹相同即「仍存在」；取 after 一侧 Finding，引用指向当前版本原文。
        before = material_of("mat_before", "draft.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])

        result = diff.diff_findings(before, after)

        self.assertEqual(result.resolved, [])
        self.assertEqual(result.new, [])
        self.assertEqual(len(result.unchanged), 1)
        finding = result.unchanged[0]
        self.assertEqual(finding.material_id, "mat_after")
        self.assertTrue(all(citation.block_id.startswith("mat_after-") for citation in finding.citations))

    def test_fingerprint_ignores_value_order_between_versions(self) -> None:
        # 数值出现顺序变了但集合相同：指纹排序后一致，仍算「仍存在」。
        before = material_of("mat_before", "draft.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 93%。", "复现实验的准确率达到 88%。"])

        result = diff.diff_findings(before, after)

        self.assertEqual(len(result.unchanged), 1)
        self.assertEqual(result.resolved, [])
        self.assertEqual(result.new, [])

    def test_new_finding_appears_after_edit(self) -> None:
        before = material_of("mat_before", "draft.md", ["实验组准确率达到 93%。", "复现实验的准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])

        result = diff.diff_findings(before, after)

        self.assertEqual(result.resolved, [])
        self.assertEqual(result.unchanged, [])
        self.assertEqual(len(result.new), 1)
        self.assertEqual(result.new[0].material_id, "mat_after")
        self.assertEqual(sorted(result.new[0].values), ["88%", "93%"])

    def test_all_three_groups_at_once(self) -> None:
        before = material_of(
            "mat_before",
            "draft.md",
            ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。", "召回率达到 70%。", "召回率达到 80%。"],
        )
        after = material_of(
            "mat_after",
            "revised.md",
            ["实验组准确率达到 93%。", "复现实验的准确率达到 96%。", "召回率达到 70%。", "召回率达到 80%。"],
        )

        result = diff.diff_findings(before, after)

        self.assertEqual([finding.measure for finding in result.resolved], ["准确率"])
        self.assertEqual(sorted(result.resolved[0].values), ["88%", "93%"])
        self.assertEqual([finding.measure for finding in result.unchanged], ["召回率"])
        self.assertEqual(sorted(result.unchanged[0].values), ["70%", "80%"])
        self.assertEqual([finding.measure for finding in result.new], ["准确率"])
        self.assertEqual(sorted(result.new[0].values), ["93%", "96%"])

    def test_empty_groups_are_legal(self) -> None:
        # 两份版本都没有可对照的数值差异：三组都是空列表，不报错。
        before = material_of("mat_before", "draft.md", ["实验组准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 93%。"])

        result = diff.diff_findings(before, after)

        self.assertEqual(result.resolved, [])
        self.assertEqual(result.unchanged, [])
        self.assertEqual(result.new, [])

    def test_same_id_is_rejected(self) -> None:
        material = material_of("mat_a", "draft.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])

        with self.assertRaises(diff.SameMaterialDiff) as caught:
            diff.diff_findings(material, material)

        self.assertEqual(caught.exception.code, "same_material")
        self.assertEqual(caught.exception.material_id, "mat_a")
        self.assertEqual(caught.exception.message, "不能对照同一份材料，请选择两份不同的材料")
        self.assertEqual(caught.exception.details, ["id=mat_a"])

    def test_result_is_deterministic(self) -> None:
        before = material_of("mat_before", "draft.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 93%。"])
        first = diff.diff_findings(before, after).model_dump()
        second = diff.diff_findings(before, after).model_dump()
        self.assertEqual(first, second)

    def test_request_and_response_are_local_contracts(self) -> None:
        request = diff.DiffRequest(material_id_before="mat_before", material_id_after="mat_after")
        self.assertEqual(request.material_id_before, "mat_before")
        with self.assertRaises(ValueError):
            diff.DiffRequest(material_id_before="mat_before", material_id_after="mat_after", extra_field="x")

        before = material_of("mat_before", "draft.md", ["实验组准确率达到 88%。", "复现实验的准确率达到 93%。"])
        after = material_of("mat_after", "revised.md", ["实验组准确率达到 93%。"])
        payload = diff.diff_findings(before, after).model_dump()
        self.assertEqual(
            sorted(payload),
            sorted(
                [
                    "material_id_before",
                    "material_id_after",
                    "filename_before",
                    "filename_after",
                    "resolved",
                    "unchanged",
                    "new",
                ]
            ),
        )

    def test_diff_module_stays_pure(self) -> None:
        source = Path(diff.__file__).read_text(encoding="utf-8")
        self.assertNotIn("storage", source)
        self.assertNotIn("llm", source)


if __name__ == "__main__":
    unittest.main()
