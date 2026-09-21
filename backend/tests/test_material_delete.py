"""删除材料：本体与从属行一次性移除（FK CASCADE）、recent 指针重指、404 语义。"""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import database
from app import main, rubric_store, storage
from app.markdown_preview import build_preview

TEXT = "中文语料：准确率达到 95%，整体稳定。"
QUOTE = "准确率达到 95%"

DEPENDENT_TABLES = (
    "materials",
    "blocks",
    "evidence_annotations",
    "material_rubric_bindings",
    "criterion_evidence_links",
    "agent_proposals",
    "proposal_candidates",
)


def synthetic_rubric():
    from app.contracts import Criterion, Rubric

    return Rubric(
        id="rubric_syn",
        revision=1,
        title="Synthetic rubric (test-only)",
        source_note="test-only",
        criteria=[
            Criterion(id="c_syn_1", title="Criterion A", requirement="requirement A", required_evidence=["x"]),
        ],
    )


def count_rows(db: Path, table: str) -> int:
    with closing(database.connect(db)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class DeleteMaterialStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        database.init_db(self.db)
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric()})

    def tearDown(self) -> None:
        rubric_store.reset_index()
        self._tmp.cleanup()

    def _full_material(self, filename: str = "a.md"):
        """一份挂满从属数据的材料：block + annotation + binding + link + proposal + candidate。"""
        material = storage.save_material(build_preview(filename, TEXT.encode("utf-8")), self.db)
        annotation = storage.save_evidence_annotation(material.blocks[0].id, QUOTE, db_path=self.db)
        storage.bind_material_rubric(material.id, "rubric_syn", 1, self.db)
        storage.create_link(material.id, annotation.id, "c_syn_1", "人工判断相关", db_path=self.db)
        storage.save_agent_proposal(
            material,
            "c_syn_1",
            "rubric_syn",
            1,
            "test",
            "test",
            "p-test",
            "completed",
            None,
            None,
            [storage.CandidateInput(material.blocks[0].id, QUOTE, "相关")],
            db_path=self.db,
        )
        return material

    def test_delete_removes_material_and_all_dependents(self) -> None:
        material = self._full_material()
        self.assertEqual(storage.get_material(material.id, self.db).id, material.id)

        self.assertTrue(storage.delete_material(material.id, self.db))

        self.assertIsNone(storage.get_material(material.id, self.db))
        self.assertFalse(storage.material_exists(material.id, self.db))
        self.assertEqual(storage.list_materials(self.db), [])
        self.assertEqual(storage.list_evidence_annotations(material.id, self.db), [])
        self.assertIsNone(storage.get_binding(material.id, self.db))
        self.assertEqual(storage.list_links(material.id, self.db), [])
        self.assertEqual(storage.list_agent_proposals(material.id, db_path=self.db), [])
        for table in DEPENDENT_TABLES:
            self.assertEqual(count_rows(self.db, table), 0, table)

    def test_delete_unknown_material_returns_false_without_side_effects(self) -> None:
        material = self._full_material()
        with closing(database.connect(self.db)) as connection:
            before = tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in DEPENDENT_TABLES)

        self.assertFalse(storage.delete_material("mat_missing", self.db))

        with closing(database.connect(self.db)) as connection:
            after = tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in DEPENDENT_TABLES)
        self.assertEqual(before, after)
        self.assertEqual(storage.get_material(material.id, self.db).id, material.id)

    def test_delete_keeps_other_materials_intact(self) -> None:
        first = self._full_material("a.md")
        second = self._full_material("b.md")

        self.assertTrue(storage.delete_material(first.id, self.db))

        self.assertIsNone(storage.get_material(first.id, self.db))
        survivor = storage.get_material(second.id, self.db)
        self.assertEqual(survivor.id, second.id)
        self.assertEqual([item.id for item in storage.list_materials(self.db)], [second.id])
        self.assertEqual(count_rows(self.db, "blocks"), len(second.blocks))
        self.assertEqual(count_rows(self.db, "evidence_annotations"), 1)
        self.assertEqual(count_rows(self.db, "criterion_evidence_links"), 1)
        self.assertEqual(count_rows(self.db, "agent_proposals"), 1)
        self.assertEqual(count_rows(self.db, "proposal_candidates"), 1)
        self.assertIsNotNone(storage.get_binding(second.id, self.db))

    def test_delete_repoints_recent_pointer_to_surviving_material(self) -> None:
        first = storage.save_material(build_preview("a.md", "A\n".encode("utf-8")), self.db)
        second = storage.save_material(build_preview("b.md", "B\n".encode("utf-8")), self.db)
        self.assertEqual(storage.get_recent_material(self.db).id, second.id)

        self.assertTrue(storage.delete_material(second.id, self.db))

        # 指针改指仍然存在的最近材料，而不是留下悬空引用或假装没有材料。
        self.assertEqual(storage.get_recent_material(self.db).id, first.id)

        self.assertTrue(storage.delete_material(first.id, self.db))
        self.assertIsNone(storage.get_recent_material(self.db))

    def test_delete_other_material_keeps_recent_pointer(self) -> None:
        first = storage.save_material(build_preview("a.md", "A\n".encode("utf-8")), self.db)
        second = storage.save_material(build_preview("b.md", "B\n".encode("utf-8")), self.db)
        self.assertEqual(storage.get_recent_material(self.db).id, second.id)

        self.assertTrue(storage.delete_material(first.id, self.db))

        self.assertEqual(storage.get_recent_material(self.db).id, second.id)


class DeleteMaterialApiTest(unittest.TestCase):
    """API 直调 + patch database.connect 到 temp DB，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "api.db"
        self._original_connect = database.connect
        database.connect = lambda db_path=database.DEFAULT_DB_PATH: self._original_connect(self.db)
        database.init_db()
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric()})
        self.material = storage.save_material(build_preview("api.md", TEXT.encode("utf-8")))

    def tearDown(self) -> None:
        database.connect = self._original_connect
        rubric_store.reset_index()
        self._tmp.cleanup()

    def test_unknown_material_maps_to_404(self) -> None:
        with self.assertRaises(main.LookupFailed) as caught:
            main.remove_material("mat_missing")
        self.assertEqual(caught.exception.code, "material_not_found")

    def test_delete_returns_204_and_material_leaves_every_read_path(self) -> None:
        response = main.remove_material(self.material.id)
        self.assertEqual(response.status_code, 204)

        self.assertIsNone(storage.get_material(self.material.id))
        self.assertEqual(main.saved_materials(), [])
        self.assertEqual(main.preflight_summaries(), [])
        with self.assertRaises(main.LookupFailed) as caught:
            main.material_by_id(self.material.id)
        self.assertEqual(caught.exception.code, "material_not_found")

    def test_delete_twice_second_call_is_404(self) -> None:
        main.remove_material(self.material.id)
        with self.assertRaises(main.LookupFailed) as caught:
            main.remove_material(self.material.id)
        self.assertEqual(caught.exception.code, "material_not_found")


if __name__ == "__main__":
    unittest.main()
