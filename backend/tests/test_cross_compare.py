"""Leaf B：两材料数值对照（跨材料数值一致性）——只比较用户显式选中的两个 id。

TDD：本文件先写、先红，再实现 app/cross_compare.py 与 POST /api/v1/comparisons。
纪律：复用同材料一致性规则（宁漏勿错）；只有引用横跨两份材料的 Finding 才保留，
仅在一份材料内部的数值差异全部丢弃；不调 LLM、不落库、不新增表；
范围就是传入的两个 id，绝不自动扫描整个材料库。
"""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import cross_compare, main, storage
from app.contracts import CrossCompareRequest, SavedMaterial
from app.markdown_preview import build_preview


def material_of(text: str, material_id: str, filename: str) -> SavedMaterial:
    """预览 Block 与持久化无关；判定只要求 block.document_id 指向材料 id。"""
    preview = build_preview(filename, text.encode("utf-8"))
    blocks = [
        block.model_copy(update={"id": f"{material_id}-blk-{index}", "document_id": material_id})
        for index, block in enumerate(preview.blocks)
    ]
    return SavedMaterial(
        id=material_id,
        filename=filename,
        size_bytes=preview.size_bytes,
        sha256=preview.sha256,
        line_count=preview.line_count,
        created_at="2026-09-19T00:00:00+00:00",
        blocks=blocks,
    )


def materials_span(finding, *materials: SavedMaterial) -> set[str]:
    """一条 Finding 的引用落在哪些材料上（block.document_id 即材料 id）。"""
    blocks = {block.id: block for material in materials for block in material.blocks}
    return {blocks[citation.block_id].document_id for citation in finding.citations}


def request_for(material_a: SavedMaterial | str, material_b: SavedMaterial | str) -> CrossCompareRequest:
    id_a = material_a.id if isinstance(material_a, SavedMaterial) else material_a
    id_b = material_b.id if isinstance(material_b, SavedMaterial) else material_b
    return CrossCompareRequest(material_id_a=id_a, material_id_b=id_b)


class CrossComparePureTest(unittest.TestCase):
    """纯函数层：零数据库、零网络、零 LLM。"""

    def test_same_measure_different_values_across_two_materials_is_reported(self) -> None:
        a = material_of("本文系统准确率达到 95%。\n", "mat_a", "ev-a.md")
        b = material_of("复现实验的准确率达到 89.7%。\n", "mat_b", "ev-b.md")

        result = cross_compare.compare_materials(a, b)

        self.assertEqual(result.material_id_a, "mat_a")
        self.assertEqual(result.material_id_b, "mat_b")
        self.assertEqual(result.filename_a, "ev-a.md")
        self.assertEqual(result.filename_b, "ev-b.md")
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.kind, "numeric_inconsistency")
        self.assertEqual(finding.measure, "准确率")
        self.assertEqual(finding.values, ["95%", "89.7%"])
        self.assertEqual({item.quote for item in finding.citations}, {"95%", "89.7%"})
        self.assertEqual(materials_span(finding, a, b), {"mat_a", "mat_b"})

    def test_different_measures_across_materials_yield_empty(self) -> None:
        a = material_of("本文系统准确率达到 95%。\n", "mat_a", "ev-a.md")
        b = material_of("复现实验的召回率达到 89.7%。\n", "mat_b", "ev-b.md")
        self.assertEqual(cross_compare.compare_materials(a, b).findings, [])

    def test_same_value_across_materials_is_not_reported(self) -> None:
        a = material_of("本文系统准确率达到 95%。\n", "mat_a", "ev-a.md")
        b = material_of("复现实验的准确率达到 95%。\n", "mat_b", "ev-b.md")
        self.assertEqual(cross_compare.compare_materials(a, b).findings, [])

    def test_within_material_only_differences_are_dropped(self) -> None:
        # 甲内部 95% vs 90% 是同材料问题，不属于跨材料对照；乙没有数字。
        a = material_of("本文系统准确率达到 95%。\n\n复现实验的准确率达到 90%。\n", "mat_a", "ev-a.md")
        b = material_of("本材料没有需要核对的数字。\n", "mat_b", "ev-b.md")
        self.assertEqual(cross_compare.compare_materials(a, b).findings, [])

    def test_finding_spanning_both_materials_keeps_all_citations(self) -> None:
        # 横跨两份材料的 Finding 保留全部引用（含甲内部那一处），由人核对。
        a = material_of("本文系统准确率达到 95%。\n\n复现实验的准确率达到 90%。\n", "mat_a", "ev-a.md")
        b = material_of("第三方复现的准确率达到 89.7%。\n", "mat_b", "ev-b.md")

        findings = cross_compare.compare_materials(a, b).findings

        self.assertEqual(len(findings), 1)
        self.assertEqual(len(findings[0].citations), 3)
        self.assertEqual(materials_span(findings[0], a, b), {"mat_a", "mat_b"})

    def test_measureless_same_unit_downgrade_also_crosses_materials(self) -> None:
        a = material_of("达到 95%。\n", "mat_a", "ev-a.md")
        b = material_of("达到 89.7%。\n", "mat_b", "ev-b.md")
        findings = cross_compare.compare_materials(a, b).findings
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "needs_review")
        self.assertEqual(materials_span(findings[0], a, b), {"mat_a", "mat_b"})

    def test_result_is_deterministic(self) -> None:
        a = material_of("本文系统准确率达到 95%。\n", "mat_a", "ev-a.md")
        b = material_of("复现实验的准确率达到 89.7%。\n", "mat_b", "ev-b.md")
        first = cross_compare.compare_materials(a, b).model_dump()
        second = cross_compare.compare_materials(a, b).model_dump()
        self.assertEqual(first, second)


class CrossCompareRouteTest(unittest.TestCase):
    """API 直调层：临时库；路由只做同 id / 存在性检查并转交纯函数。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "compare.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()

    def tearDown(self) -> None:
        storage.connect = self._original_connect
        self._tmp.cleanup()

    def save(self, filename: str, text: str) -> SavedMaterial:
        return storage.save_material(build_preview(filename, text.encode("utf-8")))

    def test_two_materials_with_cross_inconsistency_return_one_finding(self) -> None:
        a = self.save("ev-a.md", "本文系统准确率达到 95%。\n")
        b = self.save("ev-b.md", "复现实验的准确率达到 89.7%。\n")

        result = main.create_comparison(request_for(a, b))

        self.assertEqual((result.material_id_a, result.material_id_b), (a.id, b.id))
        self.assertEqual((result.filename_a, result.filename_b), ("ev-a.md", "ev-b.md"))
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.kind, "numeric_inconsistency")
        self.assertEqual(materials_span(finding, a, b), {a.id, b.id})
        citation_blocks = {item.block_id for item in finding.citations}
        self.assertEqual(citation_blocks, {a.blocks[0].id, b.blocks[0].id})

    def test_materials_without_cross_inconsistency_return_empty_list(self) -> None:
        a = self.save("ev-a.md", "本文系统准确率达到 95%。\n")
        b = self.save("ev-b.md", "复现实验的召回率达到 89.7%。\n")
        self.assertEqual(main.create_comparison(request_for(a, b)).findings, [])

    def test_same_existing_material_id_is_rejected(self) -> None:
        a = self.save("ev-a.md", "本文系统准确率达到 95%。\n")
        with self.assertRaises(cross_compare.SameMaterialCompare) as caught:
            main.create_comparison(request_for(a, a))
        self.assertEqual(caught.exception.code, "same_material")

    def test_same_missing_material_id_is_rejected_before_lookup(self) -> None:
        # 同 id 是请求级错误：先于存在性检查拒绝，不误报 404。
        with self.assertRaises(cross_compare.SameMaterialCompare):
            main.create_comparison(request_for("mat_missing", "mat_missing"))

    def test_missing_material_maps_to_material_not_found(self) -> None:
        a = self.save("ev-a.md", "本文系统准确率达到 95%。\n")
        for payload in (request_for(a, "mat_missing"), request_for("mat_missing", a)):
            with self.subTest(payload=payload.model_dump()):
                with self.assertRaises(main.LookupFailed) as caught:
                    main.create_comparison(payload)
                self.assertEqual(caught.exception.code, "material_not_found")

    def test_only_the_two_chosen_materials_are_compared(self) -> None:
        # 丙与甲有同度量词的不同数值，但用户选的是甲与乙：丙不得参与。
        a = self.save("ev-a.md", "本文系统准确率达到 95%。\n")
        b = self.save("ev-b.md", "复现实验的召回率达到 89.7%。\n")
        c = self.save("ev-c.md", "第三方复现的准确率达到 89.7%。\n")

        self.assertEqual(main.create_comparison(request_for(a, b)).findings, [])
        cross = main.create_comparison(request_for(a, c)).findings
        self.assertEqual(len(cross), 1)
        self.assertEqual(materials_span(cross[0], a, c), {a.id, c.id})

    def test_route_persists_nothing_and_adds_no_tables(self) -> None:
        a = self.save("ev-a.md", "本文系统准确率达到 95%。\n")
        b = self.save("ev-b.md", "复现实验的准确率达到 89.7%。\n")
        before_materials = storage.list_materials()
        before_a = storage.get_material(a.id)

        main.create_comparison(request_for(a, b))

        self.assertEqual(storage.list_materials(), before_materials)
        self.assertEqual(storage.get_material(a.id), before_a)
        with closing(sqlite3.connect(self.db)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual([name for name in tables if "compar" in name.lower()], [])

    def test_same_material_handler_is_machine_readable(self) -> None:
        response = asyncio.run(main.same_material_compare(None, cross_compare.SameMaterialCompare("mat_x")))
        self.assertEqual(response.status_code, 400)
        body = json.loads(response.body)
        self.assertEqual(body["code"], "same_material")
        self.assertIn("mat_x", body["details"][0])


if __name__ == "__main__":
    unittest.main()
