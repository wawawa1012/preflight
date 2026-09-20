"""P1 Review 后端最小领域层：存储函数、API 直调、绑定守卫与默认值。"""
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from fastapi import Response
from pydantic import ValidationError

from app import main, rubric_store, storage
from app.contracts import Criterion, ReviewCreate, ReviewMaterialUpsert, ReviewUpdate, Rubric
from app.markdown_preview import build_preview

TEXT = "中文语料：准确率达到 95%，整体稳定。"


def synthetic_rubric(rubric_id: str = "rubric_syn", revision: int = 1) -> Rubric:
    return Rubric(
        id=rubric_id,
        revision=revision,
        title="Synthetic rubric (test-only)",
        source_note="test-only",
        criteria=[
            Criterion(id="c_syn_1", title="Criterion A", requirement="requirement A", required_evidence=["x"]),
        ],
    )


def count_rows(db: Path, table: str) -> int:
    with closing(storage.connect(db)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class ReviewStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "reviews.db"
        storage.init_db(self.db)
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric(), ("rubric_other", 2): synthetic_rubric("rubric_other", 2)})

    def tearDown(self) -> None:
        rubric_store.reset_index()
        self._tmp.cleanup()

    def _material(self, filename: str = "a.md", text: str = TEXT):
        return storage.save_material(build_preview(filename, text.encode("utf-8")), self.db)

    def _review(self, title: str = "我的评审"):
        return storage.create_review(title, "rubric_syn", 1, self.db)

    # 1. create Review 成功
    def test_create_review_roundtrip(self) -> None:
        review = self._review()
        self.assertTrue(review.id.startswith("rev_"))
        self.assertEqual(review.title, "我的评审")
        self.assertEqual(review.rubric_id, "rubric_syn")
        self.assertEqual(review.rubric_revision, 1)
        self.assertTrue(review.created_at)
        self.assertEqual(review.created_at, review.updated_at)

    # 3. list Reviews
    def test_list_reviews(self) -> None:
        first = self._review("第一个")
        time.sleep(0.002)
        second = self._review("第二个")
        ids = [review.id for review in storage.list_reviews(self.db)]
        self.assertEqual(sorted(ids), sorted([first.id, second.id]))
        self.assertEqual(ids[0], second.id)  # created_at DESC

    # 4. get Review detail（含 materials）
    def test_get_review_detail_with_materials(self) -> None:
        review = self._review()
        material = self._material()
        entry, created = storage.upsert_review_material(review.id, material.id, "材料一", 0, self.db)
        detail = storage.get_review_detail(review.id, self.db)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.id, review.id)
        self.assertTrue(created)
        self.assertEqual(detail.materials, [entry])
        self.assertIsNone(storage.get_review_detail("rev_missing", self.db))

    # 5. rename Review（title 变，updated_at 变，rubric 不变）
    def test_rename_review(self) -> None:
        review = self._review()
        time.sleep(0.002)
        renamed = storage.rename_review(review.id, "改名后", self.db)
        self.assertEqual(renamed.title, "改名后")
        self.assertNotEqual(renamed.updated_at, review.updated_at)
        self.assertEqual(renamed.rubric_id, "rubric_syn")
        self.assertEqual(renamed.rubric_revision, 1)

    # 7. 未绑定 rubric 的 Material 可加入；加入即完成首次 binding（绑定本 Review 的标准）
    def test_upsert_unbound_material_allowed_and_first_binding_completed(self) -> None:
        review = self._review()
        material = self._material()
        entry, created = storage.upsert_review_material(review.id, material.id, None, None, self.db)
        self.assertTrue(created)
        self.assertEqual(entry.material_id, material.id)
        self.assertEqual(count_rows(self.db, "review_materials"), 1)
        binding = storage.get_binding(material.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))

    # 7b. 重复加入（含更新 label）不会覆盖已建立的首次 binding
    def test_upsert_repeat_keeps_first_binding(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, "初稿", 0, self.db)
        first = storage.get_binding(material.id, self.db)
        time.sleep(0.002)
        storage.upsert_review_material(review.id, material.id, "改名", None, self.db)
        again = storage.get_binding(material.id, self.db)
        self.assertEqual((again.rubric_id, again.rubric_revision), ("rubric_syn", 1))
        self.assertEqual(again.created_at, first.created_at)

    # 8. 已绑定相同 rubric/revision 的 Material 可加入
    def test_upsert_same_binding_allowed(self) -> None:
        review = self._review()
        material = self._material()
        storage.bind_material_rubric(material.id, "rubric_syn", 1, self.db)
        entry, created = storage.upsert_review_material(review.id, material.id, "同版本", 0, self.db)
        self.assertTrue(created)
        self.assertEqual(entry.label, "同版本")

    # 9. 已绑定其他 rubric/revision 加入 409，且绑定未被改变
    def test_upsert_conflicting_binding_raises_and_keeps_binding(self) -> None:
        review = self._review()
        material = self._material()
        storage.bind_material_rubric(material.id, "rubric_other", 2, self.db)
        with self.assertRaises(storage.BindingConflict):
            storage.upsert_review_material(review.id, material.id, "冲突", 0, self.db)
        binding = storage.get_binding(material.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_other", 2))
        self.assertEqual(count_rows(self.db, "review_materials"), 0)

    def _review_with_rubric(self, title: str, rubric_id: str, revision: int):
        return storage.create_review(title, rubric_id, revision, self.db)

    # 守卫 1：unbound M 加入 Review A（syn）→ 首次 binding 自动完成；之后换绑其他版本被拒且绑定不变
    def test_membership_binds_then_rebind_is_rejected(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, None, None, self.db)
        first = storage.get_binding(material.id, self.db)
        self.assertEqual((first.rubric_id, first.rubric_revision), ("rubric_syn", 1))
        with self.assertRaises(storage.BindingConflict):
            storage.bind_material_rubric(material.id, "rubric_other", 2, self.db)
        self.assertEqual(storage.get_binding(material.id, self.db).created_at, first.created_at)
        detail = storage.get_review_detail(review.id, self.db)
        self.assertEqual([entry.material_id for entry in detail.materials], [material.id])

    # 守卫 2：unbound M → 加入同标准 A/A2 → 首次绑定已由第一个 Review 完成，重复绑定幂等
    def test_first_binding_allowed_with_two_same_rubric_reviews(self) -> None:
        first = self._review("评审 A")
        second = self._review_with_rubric("评审 A2", "rubric_syn", 1)
        material = self._material()
        storage.upsert_review_material(first.id, material.id, None, None, self.db)
        storage.upsert_review_material(second.id, material.id, None, None, self.db)
        binding, created = storage.bind_material_rubric(material.id, "rubric_syn", 1, self.db)
        self.assertFalse(created)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))

    # 守卫 3：unbound M → 加入 A（syn）自动绑定 syn → 再加入 B（other）被拒，绑定不得被覆盖
    def test_conflicting_review_membership_is_rejected_without_rebind(self) -> None:
        review_a = self._review("评审 A")
        review_b = self._review_with_rubric("评审 B", "rubric_other", 2)
        material = self._material()
        storage.upsert_review_material(review_a.id, material.id, None, None, self.db)
        with self.assertRaises(storage.BindingConflict):
            storage.upsert_review_material(review_b.id, material.id, None, None, self.db)
        binding = storage.get_binding(material.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))
        self.assertEqual(storage.get_review_detail(review_b.id, self.db).materials, [])
        with self.assertRaises(storage.BindingConflict):
            storage.bind_material_rubric(material.id, "rubric_other", 2, self.db)

    def _legacy_add_member(self, review_id: str, material_id: str, label: str = "旧成员", position: int = 0) -> None:
        """绕过新 API 直接写入历史状态：Review 已有成员、Material 仍未绑定。

        新 API 已经会阻止这种状态，所以 legacy fixture 必须用原始 SQL 构造。
        """
        with closing(storage.connect(self.db)) as connection, connection:
            connection.execute(
                "INSERT INTO review_materials (review_id, material_id, label, position) VALUES (?, ?, ?, ?)",
                (review_id, material_id, label, position),
            )

    # Legacy：unbound M 已属于 Review A（syn）→ 加入 Review B（other）必须 409，且整事务回滚
    def test_legacy_unbound_member_blocks_conflicting_auto_binding(self) -> None:
        review_a = self._review("评审 A")
        review_b = self._review_with_rubric("评审 B", "rubric_other", 2)
        material = self._material()
        self._legacy_add_member(review_a.id, material.id)

        with self.assertRaises(storage.BindingConflict):
            storage.upsert_review_material(review_b.id, material.id, None, None, self.db)

        self.assertIsNone(storage.get_binding(material.id, self.db))
        self.assertEqual(
            [entry.material_id for entry in storage.get_review_detail(review_a.id, self.db).materials],
            [material.id],
        )
        self.assertEqual(storage.get_review_detail(review_b.id, self.db).materials, [])

    # Legacy：unbound M 已属于 Review A（syn）→ 显式绑定 other 也走同一 guard，保持未绑定
    def test_legacy_unbound_member_blocks_explicit_conflicting_binding(self) -> None:
        review_a = self._review("评审 A")
        material = self._material()
        self._legacy_add_member(review_a.id, material.id)

        with self.assertRaises(storage.BindingConflict):
            storage.bind_material_rubric(material.id, "rubric_other", 2, self.db)

        self.assertIsNone(storage.get_binding(material.id, self.db))
        self.assertEqual(
            [entry.material_id for entry in storage.get_review_detail(review_a.id, self.db).materials],
            [material.id],
        )

    # Legacy：unbound M 已属于 Review A（syn）→ 加入同标准的 Review B2 允许，并完成首次 binding
    def test_legacy_unbound_member_allows_same_rubric_auto_binding(self) -> None:
        review_a = self._review("评审 A")
        review_b = self._review("评审 B2")
        material = self._material()
        self._legacy_add_member(review_a.id, material.id)

        entry, created = storage.upsert_review_material(review_b.id, material.id, None, None, self.db)

        self.assertTrue(created)
        self.assertEqual(entry.material_id, material.id)
        binding = storage.get_binding(material.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))

    # 10. 重复加入走更新语义（PK 幂等 upsert），不产生重复成员
    def test_upsert_repeat_is_idempotent_update(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, "首版", 3, self.db)
        entry, created = storage.upsert_review_material(review.id, material.id, None, None, self.db)
        self.assertFalse(created)
        self.assertEqual(entry.label, "首版")
        self.assertEqual(entry.position, 3)
        self.assertEqual(count_rows(self.db, "review_materials"), 1)

    # 11. 更新 label
    def test_upsert_updates_label(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, "旧名", 0, self.db)
        entry, created = storage.upsert_review_material(review.id, material.id, "新名", None, self.db)
        self.assertFalse(created)
        self.assertEqual(entry.label, "新名")
        self.assertEqual(entry.position, 0)

    # 12. 更新 position
    def test_upsert_updates_position(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, "名", 0, self.db)
        entry, created = storage.upsert_review_material(review.id, material.id, None, 9, self.db)
        self.assertFalse(created)
        self.assertEqual(entry.position, 9)
        self.assertEqual(entry.label, "名")

    # 13. 同 filename 材料可用不同 label
    def test_two_same_filename_distinct_labels(self) -> None:
        review = self._review()
        first = self._material("same.md", "第一份内容")
        second = self._material("same.md", "第二份内容")
        storage.upsert_review_material(review.id, first.id, "第一版", 0, self.db)
        storage.upsert_review_material(review.id, second.id, "第二版", 1, self.db)
        detail = storage.get_review_detail(review.id, self.db)
        self.assertEqual(sorted(entry.label for entry in detail.materials), ["第一版", "第二版"])

    # 14. DELETE 成员关系后 Material 本体仍在
    def test_remove_review_material_keeps_material(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, None, None, self.db)
        self.assertTrue(storage.remove_review_material(review.id, material.id, self.db))
        self.assertIsNotNone(storage.get_material(material.id, self.db))
        self.assertEqual(storage.get_review_detail(review.id, self.db).materials, [])
        self.assertFalse(storage.remove_review_material(review.id, material.id, self.db))

    # 15. delete_review 后成员清空、Material 仍在
    def test_delete_review_cascades_membership_keeps_material(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, None, None, self.db)
        self.assertTrue(storage.delete_review(review.id, self.db))
        self.assertIsNone(storage.get_review_detail(review.id, self.db))
        self.assertEqual(count_rows(self.db, "review_materials"), 0)
        self.assertIsNotNone(storage.get_material(material.id, self.db))

    # 16. delete_material 后成员关系被移除
    def test_delete_material_removes_memberships(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, None, None, self.db)
        self.assertTrue(storage.delete_material(material.id, self.db))
        self.assertEqual(count_rows(self.db, "review_materials"), 0)
        self.assertEqual(storage.get_review_detail(review.id, self.db).materials, [])

    # 17. delete_material 后受影响 Review updated_at 变化
    def test_delete_material_bumps_review_updated_at(self) -> None:
        review = self._review()
        material = self._material()
        storage.upsert_review_material(review.id, material.id, None, None, self.db)
        before = storage.get_review_detail(review.id, self.db).updated_at
        time.sleep(0.002)
        self.assertTrue(storage.delete_material(material.id, self.db))
        after = storage.get_review_detail(review.id, self.db).updated_at
        self.assertNotEqual(after, before)

    # 18. detail 中 materials 排序稳定：position ASC, material_id ASC
    def test_detail_materials_order_stable(self) -> None:
        review = self._review()
        materials = [self._material(f"m{i}.md", f"内容 {i}") for i in range(3)]
        storage.upsert_review_material(review.id, materials[0].id, "A", 1, self.db)
        storage.upsert_review_material(review.id, materials[1].id, "B", 0, self.db)
        storage.upsert_review_material(review.id, materials[2].id, "C", 0, self.db)
        detail = storage.get_review_detail(review.id, self.db)
        expected = sorted(
            [materials[0].id, materials[1].id, materials[2].id],
            key=lambda mid: (0 if mid != materials[0].id else 1, mid),
        )
        self.assertEqual([entry.material_id for entry in detail.materials], expected)

    # 默认值：label 缺省取 filename，position 缺省追加到末尾
    def test_upsert_defaults_label_and_position(self) -> None:
        review = self._review()
        first = self._material("first.md", "第一份")
        second = self._material("second.md", "第二份")
        entry_first, _ = storage.upsert_review_material(review.id, first.id, None, None, self.db)
        entry_second, _ = storage.upsert_review_material(review.id, second.id, None, None, self.db)
        self.assertEqual(entry_first.label, "first.md")
        self.assertEqual(entry_first.position, 0)
        self.assertEqual(entry_second.label, "second.md")
        self.assertEqual(entry_second.position, 1)

    # 19. 现有 Material API 回归：save/get/list/delete 行为不变
    def test_material_api_regression(self) -> None:
        material = self._material("regression.md")
        self.assertEqual(storage.get_material(material.id, self.db).id, material.id)
        self.assertIn(material.id, [item.id for item in storage.list_materials(self.db)])
        storage.bind_material_rubric(material.id, "rubric_syn", 1, self.db)
        self.assertEqual(storage.get_binding(material.id, self.db).rubric_id, "rubric_syn")
        with self.assertRaises(storage.BindingConflict):
            storage.bind_material_rubric(material.id, "rubric_other", 2, self.db)
        self.assertTrue(storage.delete_material(material.id, self.db))
        self.assertIsNone(storage.get_material(material.id, self.db))
        self.assertFalse(storage.delete_material("mat_missing", self.db))


class ReviewApiTest(unittest.TestCase):
    """API 直调 + patch storage.connect 到 temp DB，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "api.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric()})
        self.material = storage.save_material(build_preview("api.md", TEXT.encode("utf-8")))

    def tearDown(self) -> None:
        storage.connect = self._original_connect
        rubric_store.reset_index()
        self._tmp.cleanup()

    # 2. 不存在/无效 rubric 创建被拒（404 rubric_not_found）
    def test_create_review_rejects_unknown_rubric(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.create_review(ReviewCreate(title="x", rubric_id="rubric_missing", rubric_revision=1))
        self.assertEqual(caught.exception.code, "rubric_not_found")
        with self.assertRaises(main.LookupFailed):
            main.create_review(ReviewCreate(title="x", rubric_id="rubric_syn", rubric_revision=99))

    def test_create_review_with_valid_rubric(self) -> None:
        review = main.create_review(ReviewCreate(title="有效", rubric_id="rubric_syn", rubric_revision=1))
        self.assertEqual(review.rubric_id, "rubric_syn")

    # 6. PATCH 带 rubric_id/rubric_revision 被 400 拒绝（extra=forbid）
    def test_review_update_rejects_rubric_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewUpdate.model_validate({"title": "改名", "rubric_id": "rubric_other", "rubric_revision": 2})
        # rename 路径只接受 title，不会改动 rubric。
        review = main.create_review(ReviewCreate(title="原", rubric_id="rubric_syn", rubric_revision=1))
        renamed = main.update_review(review.id, ReviewUpdate.model_validate({"title": "新"}))
        self.assertEqual(renamed.title, "新")
        self.assertEqual((renamed.rubric_id, renamed.rubric_revision), ("rubric_syn", 1))

    def test_put_membership_conflict_maps_to_binding_conflict(self) -> None:
        review = main.create_review(ReviewCreate(title="r", rubric_id="rubric_syn", rubric_revision=1))
        storage.bind_material_rubric(self.material.id, "rubric_other", 2, self.db)
        with self.assertRaises(storage.BindingConflict):
            main.upsert_review_material(review.id, self.material.id, ReviewMaterialUpsert(), None)

    def test_put_missing_review_and_material_are_404(self) -> None:
        review = main.create_review(ReviewCreate(title="r", rubric_id="rubric_syn", rubric_revision=1))
        with self.assertRaises(main.LookupFailed) as caught:
            main.upsert_review_material("rev_missing", self.material.id, ReviewMaterialUpsert(), None)
        self.assertEqual(caught.exception.code, "review_not_found")
        with self.assertRaises(main.LookupFailed) as caught:
            main.upsert_review_material(review.id, "mat_missing", ReviewMaterialUpsert(), None)
        self.assertEqual(caught.exception.code, "material_not_found")

    def test_delete_membership_missing_is_404(self) -> None:
        review = main.create_review(ReviewCreate(title="r", rubric_id="rubric_syn", rubric_revision=1))
        with self.assertRaises(main.LookupFailed) as caught:
            main.remove_review_material("rev_missing", self.material.id)
        self.assertEqual(caught.exception.code, "review_not_found")
        with self.assertRaises(main.LookupFailed) as caught:
            main.remove_review_material(review.id, self.material.id)
        self.assertEqual(caught.exception.code, "membership_not_found")

    def test_put_membership_completes_first_binding_via_api(self) -> None:
        review = main.create_review(ReviewCreate(title="r", rubric_id="rubric_syn", rubric_revision=1))
        entry = main.upsert_review_material(review.id, self.material.id, ReviewMaterialUpsert(), Response())
        self.assertEqual(entry.material_id, self.material.id)
        binding = storage.get_binding(self.material.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))

    def test_delete_review_endpoint_keeps_material(self) -> None:
        review = main.create_review(ReviewCreate(title="r", rubric_id="rubric_syn", rubric_revision=1))
        main.upsert_review_material(review.id, self.material.id, ReviewMaterialUpsert(), Response())

        response = main.remove_review(review.id)

        self.assertEqual(response.status_code, 204)
        self.assertIsNone(storage.get_review_detail(review.id, self.db))
        self.assertEqual(count_rows(self.db, "review_materials"), 0)
        self.assertIsNotNone(storage.get_material(self.material.id, self.db))
        self.assertIsNotNone(storage.get_binding(self.material.id, self.db))

    def test_delete_missing_review_is_404(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.remove_review("rev_missing")
        self.assertEqual(caught.exception.code, "review_not_found")


if __name__ == "__main__":
    unittest.main()
