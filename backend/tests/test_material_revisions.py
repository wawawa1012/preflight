"""Revision Backend v1：Markdown 修订材料、只读 parent/child relation、原子保存。

旧材料永远不可变；child 是全新 Material；不复制/不重定向旧引用。
"""
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from app import main, rubric_store, storage
from app.contracts import Criterion, MaterialRevisionCreate, Rubric
from app.markdown_preview import PreviewRejected, build_preview

TEXT_V1 = "第一行\n\n第三行\n\n\n第六行"
TEXT_V2 = "第一行\n\n第三行（修改版）\n\n新增说明\n"


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


class RevisionStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "revisions.db"
        storage.init_db(self.db)
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric(), ("rubric_other", 2): synthetic_rubric("rubric_other", 2)})
        self.parent = self._material("draft.md", TEXT_V1)

    def tearDown(self) -> None:
        rubric_store.reset_index()
        self._tmp.cleanup()

    def _material(self, filename: str = "a.md", text: str = TEXT_V1):
        return storage.save_material(build_preview(filename, text.encode("utf-8")), self.db)

    def _revision(self, parent_id: str, filename: str = "draft-v2.md", text: str = TEXT_V2, **kwargs):
        return storage.create_material_revision(
            parent_id, build_preview(filename, text.encode("utf-8")), db_path=self.db, **kwargs
        )

    # 1/2/3/5/6: 新建修订、child 身份全新、relation child→parent
    def test_create_revision_child_is_new_material(self) -> None:
        result = self._revision(self.parent.id)
        self.assertIsNotNone(result)
        child, revision = result
        self.assertNotEqual(child.id, self.parent.id)
        self.assertTrue(child.id.startswith("mat_"))
        self.assertEqual(child.created_at != "" and child.created_at, revision.created_at)
        self.assertEqual(revision.child_material_id, child.id)
        self.assertEqual(revision.parent_material_id, self.parent.id)
        parent_block_ids = {block.id for block in self.parent.blocks}
        child_block_ids = {block.id for block in child.blocks}
        self.assertTrue(child_block_ids)
        self.assertTrue(parent_block_ids.isdisjoint(child_block_ids))
        expected_sha = build_preview("draft-v2.md", TEXT_V2.encode("utf-8")).sha256
        self.assertEqual(child.sha256, expected_sha)
        self.assertNotEqual(child.sha256, self.parent.sha256)

    # 4: 父材料完全不变
    def test_parent_is_immutable(self) -> None:
        before = storage.get_material(self.parent.id, self.db).model_dump()
        self._revision(self.parent.id)
        after = storage.get_material(self.parent.id, self.db).model_dump()
        self.assertEqual(before, after)
        self.assertEqual(count_rows(self.db, "material_revisions"), 1)

    # 7: 一个 parent 多个 children
    def test_parent_can_have_multiple_children(self) -> None:
        first = self._revision(self.parent.id, filename="v2.md")
        time.sleep(0.002)
        second = self._revision(self.parent.id, filename="v3.md")
        context = storage.get_revision_context(self.parent.id, self.db)
        self.assertEqual(context.parent, None)
        self.assertEqual({item.material_id for item in context.children}, {first[0].id, second[0].id})
        self.assertTrue(all(item.available for item in context.children))

    # 8: child 不能有第二个 parent（relation 创建后不可修改）
    def test_child_cannot_acquire_second_parent(self) -> None:
        result = self._revision(self.parent.id)
        child, _ = result
        other = self._material("other.md", "别的材料")
        with closing(storage.connect(self.db)) as connection, connection:
            with self.assertRaises(storage.StorageConflict):
                storage._insert_revision_relation(connection, child.id, other.id, "2026-01-01T00:00:00+00:00")
        with closing(storage.connect(self.db)) as connection:
            row = connection.execute(
                "SELECT parent_material_id FROM material_revisions WHERE child_material_id = ?", (child.id,)
            ).fetchone()
        self.assertEqual(row["parent_material_id"], self.parent.id)

    # 9/11: 父不存在返回 None；校验失败不留下 child（扩展名）
    def test_invalid_parent_returns_none(self) -> None:
        self.assertIsNone(self._revision("mat_missing"))

    def test_invalid_extension_rejected_leaves_no_child(self) -> None:
        before = count_rows(self.db, "materials")
        with self.assertRaises(PreviewRejected):
            build_preview("draft.txt", TEXT_V2.encode("utf-8"))
        self.assertEqual(count_rows(self.db, "materials"), before)

    # 12: 事务中途失败必须整体回滚（用 mock 让 membership 写入抛错）
    def test_mid_transaction_failure_rolls_back_everything(self) -> None:
        review = storage.create_review("评审", "rubric_syn", 1, self.db)
        storage.upsert_review_material(review.id, self.parent.id, None, None, self.db)
        before = {
            "materials": count_rows(self.db, "materials"),
            "blocks": count_rows(self.db, "blocks"),
            "relations": count_rows(self.db, "material_revisions"),
            "bindings": count_rows(self.db, "material_rubric_bindings"),
            "members": count_rows(self.db, "review_materials"),
        }
        with mock.patch("app.storage._add_review_member", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._revision(self.parent.id, review_id=review.id)
        after = {
            "materials": count_rows(self.db, "materials"),
            "blocks": count_rows(self.db, "blocks"),
            "relations": count_rows(self.db, "material_revisions"),
            "bindings": count_rows(self.db, "material_rubric_bindings"),
            "members": count_rows(self.db, "review_materials"),
        }
        self.assertEqual(before, after)

    # 13/14/15: Review 路径：parent 是成员；label 默认 filename、显式 label 生效；child 绑定 review 的精确 rubric
    def test_review_path_adds_child_with_default_label_and_binding(self) -> None:
        review = storage.create_review("评审", "rubric_syn", 1, self.db)
        storage.upsert_review_material(review.id, self.parent.id, "初稿", None, self.db)
        before_updated = storage.get_review_detail(review.id, self.db).updated_at
        time.sleep(0.002)
        child, _ = self._revision(self.parent.id, filename="draft-v2.md", review_id=review.id)
        detail = storage.get_review_detail(review.id, self.db)
        entry = next(item for item in detail.materials if item.material_id == child.id)
        self.assertEqual(entry.label, "draft-v2.md")
        self.assertGreater(entry.position, 0)
        self.assertNotEqual(detail.updated_at, before_updated)
        binding = storage.get_binding(child.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))
        self.assertIsNone(storage.get_binding(self.parent.id, self.db))

    def test_review_path_explicit_label_wins(self) -> None:
        review = storage.create_review("评审", "rubric_syn", 1, self.db)
        storage.upsert_review_material(review.id, self.parent.id, "初稿", None, self.db)
        child, _ = self._revision(self.parent.id, review_id=review.id, label="修改版 B")
        detail = storage.get_review_detail(review.id, self.db)
        entry = next(item for item in detail.materials if item.material_id == child.id)
        self.assertEqual(entry.label, "修改版 B")

    # 16: 传入 parent binding 时 child 继承（无 Review 的继承由 API 层计算）
    def test_inherit_binding_parameter_applies(self) -> None:
        storage.bind_material_rubric(self.parent.id, "rubric_other", 2, self.db)
        child, _ = self._revision(self.parent.id, inherit_binding=("rubric_other", 2))
        binding = storage.get_binding(child.id, self.db)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_other", 2))
        parent_binding = storage.get_binding(self.parent.id, self.db)
        self.assertEqual((parent_binding.rubric_id, parent_binding.rubric_revision), ("rubric_other", 2))

    # 17: 无 Review、parent 未绑定 → child 未绑定
    def test_unbound_without_review_or_parent_binding(self) -> None:
        child, _ = self._revision(self.parent.id)
        self.assertIsNone(storage.get_binding(child.id, self.db))

    # 18: 删除 child 保留 parent
    def test_delete_child_keeps_parent(self) -> None:
        child, _ = self._revision(self.parent.id)
        self.assertTrue(storage.delete_material(child.id, self.db))
        self.assertIsNotNone(storage.get_material(self.parent.id, self.db))
        self.assertEqual(storage.get_revision_context(self.parent.id, self.db).children, [])
        self.assertEqual(storage.get_revision_context(self.parent.id, self.db).parent, None)

    # 19/20: 删除 parent 保留 child 与 relation；child 的 parent_available=false
    def test_delete_parent_keeps_child_with_unavailable_parent(self) -> None:
        child, revision = self._revision(self.parent.id)
        self.assertTrue(storage.delete_material(self.parent.id, self.db))
        self.assertIsNotNone(storage.get_material(child.id, self.db))
        context = storage.get_revision_context(child.id, self.db)
        self.assertIsNotNone(context.parent)
        self.assertEqual(context.parent.material_id, self.parent.id)
        self.assertFalse(context.parent.parent_available)
        self.assertEqual(count_rows(self.db, "material_revisions"), 1)
        with closing(storage.connect(self.db)) as connection:
            row = connection.execute(
                "SELECT parent_material_id FROM material_revisions WHERE child_material_id = ?", (child.id,)
            ).fetchone()
        self.assertEqual(row["parent_material_id"], self.parent.id)

    # 21: 现有上传不受影响；普通材料没有 parent/children
    def test_existing_upload_unaffected(self) -> None:
        ordinary = self._material("plain.md", "普通材料")
        context = storage.get_revision_context(ordinary.id, self.db)
        self.assertIsNone(context.parent)
        self.assertEqual(context.children, [])
        self.assertIsNone(storage.get_revision_context("mat_missing", self.db))

    # 22: 现有 Review 行为不受影响
    def test_existing_review_behavior_unaffected(self) -> None:
        review = storage.create_review("回归", "rubric_syn", 1, self.db)
        entry, created = storage.upsert_review_material(review.id, self.parent.id, None, None, self.db)
        self.assertTrue(created)
        self.assertEqual(entry.label, "draft.md")
        self.assertTrue(storage.remove_review_material(review.id, self.parent.id, self.db))
        self.assertIsNotNone(storage.get_material(self.parent.id, self.db))

    # 23: editable source 保留空行结构、LF normalize
    def test_editable_source_preserves_blank_lines(self) -> None:
        source = storage.get_editable_source(self.parent.id, self.db)
        self.assertEqual(source.material_id, self.parent.id)
        self.assertEqual(source.format, "md")
        self.assertEqual(source.normalization, "lf")
        self.assertEqual(source.text, TEXT_V1)
        rebuilt = build_preview("draft.md", source.text.encode("utf-8"))
        self.assertEqual(rebuilt.sha256, self.parent.sha256)

    def test_editable_source_normalizes_crlf_and_unknown_is_none(self) -> None:
        material = storage.save_material(build_preview("crlf.md", "A\r\nB\r\n".encode("utf-8")), self.db)
        self.assertEqual(storage.get_editable_source(material.id, self.db).text, "A\nB")
        self.assertTrue(storage.delete_material(material.id, self.db))
        self.assertIsNone(storage.get_editable_source(material.id, self.db))


class RevisionApiTest(unittest.TestCase):
    """API 直调 + patch storage.connect 到 temp DB，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "revision-api.db"
        self._original_connect = storage.connect
        storage.connect = lambda db_path=storage.DEFAULT_DB_PATH: self._original_connect(self.db)
        storage.init_db()
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric(), ("rubric_other", 2): synthetic_rubric("rubric_other", 2)})
        self.parent = storage.save_material(build_preview("draft.md", TEXT_V1.encode("utf-8")))

    def tearDown(self) -> None:
        storage.connect = self._original_connect
        rubric_store.reset_index()
        self._tmp.cleanup()

    def _payload(self, **overrides) -> MaterialRevisionCreate:
        data = {"text": TEXT_V2, "filename": "draft-v2.md"}
        data.update(overrides)
        return MaterialRevisionCreate(**data)

    def test_api_creates_revision_and_context(self) -> None:
        created = main.create_material_revision(self.parent.id, self._payload())
        self.assertEqual(created.revision.parent_material_id, self.parent.id)
        self.assertEqual(created.material.filename, "draft-v2.md")
        context = main.material_revision_context(self.parent.id)
        self.assertEqual([item.material_id for item in context.children], [created.material.id])
        child_context = main.material_revision_context(created.material.id)
        self.assertEqual(child_context.parent.material_id, self.parent.id)
        self.assertTrue(child_context.parent.parent_available)

    def test_api_unknown_parent_404(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.create_material_revision("mat_missing", self._payload())
        self.assertEqual(caught.exception.code, "material_not_found")

    def test_api_invalid_extension_rejected_and_no_child(self) -> None:
        with self.assertRaises(PreviewRejected) as caught:
            main.create_material_revision(self.parent.id, self._payload(filename="draft.txt"))
        self.assertEqual(caught.exception.code, "invalid_extension")
        self.assertEqual(len(storage.list_materials()), 1)

    def test_api_unknown_review_404(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.create_material_revision(self.parent.id, self._payload(review_id="rev_missing"))
        self.assertEqual(caught.exception.code, "review_not_found")

    def test_api_parent_not_in_review_409(self) -> None:
        review = storage.create_review("评审", "rubric_syn", 1)
        with self.assertRaises(storage.ParentNotInReview) as caught:
            main.create_material_revision(self.parent.id, self._payload(review_id=review.id))
        self.assertEqual(caught.exception.code, "parent_not_in_review")
        self.assertEqual(len(storage.list_materials()), 1)

    def test_api_missing_rubric_file_404(self) -> None:
        review = storage.create_review("评审", "rubric_syn", 1)
        storage.upsert_review_material(review.id, self.parent.id, None, None)
        rubric_store.reset_index()
        with self.assertRaises(main.LookupFailed) as caught:
            main.create_material_revision(self.parent.id, self._payload(review_id=review.id))
        self.assertEqual(caught.exception.code, "rubric_not_found")
        self.assertEqual(len(storage.list_materials()), 1)

    def test_api_review_path_binds_review_rubric(self) -> None:
        review = main.create_review(main.ReviewCreate(title="评审", rubric_id="rubric_syn", rubric_revision=1))
        main.upsert_review_material(review.id, self.parent.id, main.ReviewMaterialUpsert(), mock.Mock(status_code=200))
        created = main.create_material_revision(self.parent.id, self._payload(review_id=review.id))
        binding = main.material_rubric_binding(created.material.id)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_syn", 1))

    def test_api_inherits_parent_binding_without_review(self) -> None:
        storage.bind_material_rubric(self.parent.id, "rubric_other", 2)
        created = main.create_material_revision(self.parent.id, self._payload())
        binding = main.material_rubric_binding(created.material.id)
        self.assertEqual((binding.rubric_id, binding.rubric_revision), ("rubric_other", 2))

    def test_api_child_unbound_without_review_or_parent_binding(self) -> None:
        created = main.create_material_revision(self.parent.id, self._payload())
        self.assertIsNone(main.material_rubric_binding(created.material.id))

    def test_api_editable_source(self) -> None:
        source = main.material_editable_source(self.parent.id)
        self.assertEqual(source.text, TEXT_V1)
        self.assertEqual(source.normalization, "lf")
        with self.assertRaises(main.LookupFailed):
            main.material_editable_source("mat_missing")


if __name__ == "__main__":
    unittest.main()
