"""Iteration 4：材料绑定、人工关联、删除与 API 错误码测试（合成 rubric，test-only）。"""
import asyncio
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi import Response
from pydantic import ValidationError

from app import database
from app import main, rubric_store, storage
from app.contracts import Criterion, CriterionEvidenceLinkCreate, Rubric, RubricBindingCreate
from app.markdown_preview import build_preview

TEXT = "中文语料：准确率达到 95%，整体稳定。"
QUOTE = "准确率达到 95%"


def synthetic_rubric(rubric_id: str = "rubric_syn", revision: int = 1) -> Rubric:
    return Rubric(
        id=rubric_id,
        revision=revision,
        title="Synthetic rubric (test-only)",
        source_note="test-only synthetic；不是真实评分标准",
        criteria=[
            Criterion(id="c_syn_1", title="Criterion A", requirement="requirement A", required_evidence=["x"]),
            Criterion(id="c_syn_2", title="Criterion B", requirement="requirement B", required_evidence=["y"]),
        ],
    )


class LinkStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        database.init_db(self.db)
        self.material = storage.save_material(
            build_preview("ev.md", TEXT.encode("utf-8")), self.db
        )
        self.block = self.material.blocks[0]
        self.annotation = storage.save_evidence_annotation(self.block.id, QUOTE, db_path=self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _bind(self, material_id: str | None = None):
        return storage.bind_material_rubric(material_id or self.material.id, "rubric_syn", 1, self.db)

    def _link(self, **overrides):
        values = {
            "material_id": self.material.id,
            "annotation_id": self.annotation.id,
            "criterion_id": "c_syn_1",
            "rationale": "人工判断：该引用与 Criterion A 相关",
        }
        values.update(overrides)
        return storage.create_link(**values, db_path=self.db)

    def test_binding_is_idempotent_and_conflict_on_rebind(self) -> None:
        binding, created = self._bind()
        self.assertTrue(created)
        again, created_again = self._bind()
        self.assertFalse(created_again)
        self.assertEqual(again.model_dump(), binding.model_dump())
        with self.assertRaises(storage.BindingConflict):
            storage.bind_material_rubric(self.material.id, "rubric_other", 1, self.db)
        self.assertIsNone(storage.bind_material_rubric("mat_missing", "rubric_syn", 1, self.db))

    def test_link_creation_derives_identity_from_annotation(self) -> None:
        self._bind()
        link = self._link()
        self.assertEqual(link.material_id, self.material.id)
        self.assertEqual(link.rubric_id, "rubric_syn")
        self.assertEqual(link.rubric_revision, 1)
        self.assertEqual(link.proposed_by, "human")
        self.assertEqual([item.id for item in storage.list_links(self.material.id, self.db)], [link.id])

    def test_same_annotation_can_link_to_different_criteria(self) -> None:
        self._bind()
        first = self._link(criterion_id="c_syn_1")
        second = self._link(criterion_id="c_syn_2")
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(storage.list_links(self.material.id, self.db)), 2)

    def test_duplicate_link_is_rejected(self) -> None:
        self._bind()
        self._link()
        with self.assertRaises(storage.DuplicateLink):
            self._link(rationale="重复")

    def test_unbound_material_is_rejected(self) -> None:
        with self.assertRaises(storage.RubricNotBound):
            self._link()

    def test_cross_material_annotation_returns_none_and_no_rows(self) -> None:
        self._bind()
        other = storage.save_material(build_preview("other.md", "乙\n".encode("utf-8")), self.db)
        self.assertIsNone(self._link(material_id=other.id))
        self.assertEqual(storage.list_links(other.id, self.db), [])

    def test_tampered_span_is_rejected_without_rows(self) -> None:
        self._bind()
        with closing(database.connect(self.db)) as connection, connection:
            connection.execute(
                "UPDATE evidence_annotations SET quote = ? WHERE id = ?", ("被篡改的引用", self.annotation.id)
            )
        with self.assertRaises(storage.SpanMismatch):
            self._link()
        self.assertEqual(storage.list_links(self.material.id, self.db), [])

    def test_delete_link_then_delete_annotation_cascades(self) -> None:
        self._bind()
        link = self._link()
        self.assertTrue(storage.delete_link(self.material.id, link.id, self.db))
        self.assertFalse(storage.delete_link(self.material.id, link.id, self.db))

        second = self._link(criterion_id="c_syn_2")
        self.assertTrue(storage.delete_evidence_annotation(self.material.id, self.annotation.id, self.db))
        self.assertEqual(storage.list_links(self.material.id, self.db), [])
        self.assertIsNone(storage.get_evidence_annotation(self.annotation.id, self.db))
        self.assertFalse(storage.delete_evidence_annotation(self.material.id, self.annotation.id, self.db))
        # Annotation 删除不影响 Block/材料完整性。
        loaded = storage.get_material(self.material.id, self.db)
        self.assertEqual(len(loaded.blocks), 1)
        self.assertEqual(loaded.blocks[0].text, TEXT)
        self.assertNotEqual(second.id, link.id)

    def test_delete_annotation_wrong_material_is_rejected(self) -> None:
        other = storage.save_material(build_preview("other.md", "乙\n".encode("utf-8")), self.db)
        self.assertFalse(storage.delete_evidence_annotation(other.id, self.annotation.id, self.db))
        self.assertIsNotNone(storage.get_evidence_annotation(self.annotation.id, self.db))

    def test_material_delete_cascades_binding_and_links(self) -> None:
        target = storage.save_material(build_preview("target.md", "甲\n".encode("utf-8")), self.db)
        storage.save_material(build_preview("keep.md", "乙\n".encode("utf-8")), self.db)  # recent 指向另一份
        annotation = storage.save_evidence_annotation(target.blocks[0].id, "甲", db_path=self.db)
        storage.bind_material_rubric(target.id, "rubric_syn", 1, self.db)
        link = storage.create_link(target.id, annotation.id, "c_syn_1", "理由", db_path=self.db)
        with closing(database.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM materials WHERE id = ?", (target.id,))
        self.assertIsNone(storage.get_binding(target.id, self.db))
        self.assertIsNone(storage.get_evidence_annotation(annotation.id, self.db))
        self.assertIsNotNone(link)  # 删除前确实建立过


class LinkApiTest(unittest.TestCase):
    """API 直调 + patch database.connect 到 temp DB，避免读写开发库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "api.db"
        self._original_connect = database.connect
        database.connect = lambda db_path=database.DEFAULT_DB_PATH: self._original_connect(self.db)
        database.init_db()
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric()})
        self.material = storage.save_material(build_preview("ev.md", TEXT.encode("utf-8")))
        self.annotation = storage.save_evidence_annotation(self.material.blocks[0].id, QUOTE)

    def tearDown(self) -> None:
        database.connect = self._original_connect
        rubric_store.reset_index()
        self._tmp.cleanup()

    def test_bind_endpoint_status_codes_and_errors(self) -> None:
        response = Response()
        binding = main.bind_material_rubric(
            self.material.id, RubricBindingCreate(rubric_id="rubric_syn", rubric_revision=1), response
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(binding.material_id, self.material.id)

        response_again = Response()
        main.bind_material_rubric(
            self.material.id, RubricBindingCreate(rubric_id="rubric_syn", rubric_revision=1), response_again
        )
        self.assertEqual(response_again.status_code, 200)

        with self.assertRaises(main.LookupFailed) as unknown_rubric:
            main.bind_material_rubric(
                self.material.id, RubricBindingCreate(rubric_id="rubric_other", rubric_revision=1), Response()
            )
        self.assertEqual(unknown_rubric.exception.code, "rubric_not_found")

        with self.assertRaises(main.LookupFailed) as unknown_material:
            main.bind_material_rubric(
                "mat_missing", RubricBindingCreate(rubric_id="rubric_syn", rubric_revision=1), Response()
            )
        self.assertEqual(unknown_material.exception.code, "material_not_found")

    def test_binding_getter_and_conflict(self) -> None:
        self.assertIsNone(main.material_rubric_binding(self.material.id))
        response = Response()
        main.bind_material_rubric(
            self.material.id, RubricBindingCreate(rubric_id="rubric_syn", rubric_revision=1), response
        )
        self.assertEqual(main.material_rubric_binding(self.material.id).rubric_revision, 1)
        rubric_store.set_index({("rubric_syn", 1): synthetic_rubric(), ("rubric_other", 1): synthetic_rubric("rubric_other")})
        with self.assertRaises(storage.BindingConflict):
            main.bind_material_rubric(
                self.material.id, RubricBindingCreate(rubric_id="rubric_other", rubric_revision=1), Response()
            )

    def test_link_endpoint_unknown_criterion_and_annotation(self) -> None:
        with self.assertRaises(storage.RubricNotBound):
            main.create_criterion_link(
                self.material.id,
                CriterionEvidenceLinkCreate(annotation_id=self.annotation.id, criterion_id="c_syn_1", rationale="理由"),
            )
        main.bind_material_rubric(
            self.material.id, RubricBindingCreate(rubric_id="rubric_syn", rubric_revision=1), Response()
        )
        with self.assertRaises(main.LookupFailed) as unknown_criterion:
            main.create_criterion_link(
                self.material.id,
                CriterionEvidenceLinkCreate(annotation_id=self.annotation.id, criterion_id="c_missing", rationale="理由"),
            )
        self.assertEqual(unknown_criterion.exception.code, "criterion_not_found")

        other = storage.save_material(build_preview("other.md", "乙\n".encode("utf-8")))
        with self.assertRaises(main.LookupFailed) as unknown_annotation:
            main.create_criterion_link(
                other.id,
                CriterionEvidenceLinkCreate(annotation_id=self.annotation.id, criterion_id="c_syn_1", rationale="理由"),
            )
        self.assertEqual(unknown_annotation.exception.code, "annotation_not_found")

    def test_link_endpoint_delete_flows(self) -> None:
        main.bind_material_rubric(
            self.material.id, RubricBindingCreate(rubric_id="rubric_syn", rubric_revision=1), Response()
        )
        link = main.create_criterion_link(
            self.material.id,
            CriterionEvidenceLinkCreate(annotation_id=self.annotation.id, criterion_id="c_syn_1", rationale="理由"),
        )
        self.assertEqual(len(main.material_criterion_links(self.material.id)), 1)

        response = main.delete_criterion_link(self.material.id, link.id)
        self.assertEqual(response.status_code, 204)
        with self.assertRaises(main.LookupFailed) as missing_link:
            main.delete_criterion_link(self.material.id, link.id)
        self.assertEqual(missing_link.exception.code, "link_not_found")

        response_annotation = main.remove_evidence_annotation(self.material.id, self.annotation.id)
        self.assertEqual(response_annotation.status_code, 204)
        with self.assertRaises(main.LookupFailed) as missing_annotation:
            main.remove_evidence_annotation(self.material.id, self.annotation.id)
        self.assertEqual(missing_annotation.exception.code, "annotation_not_found")

    def test_blank_rationale_is_rejected_by_contract(self) -> None:
        with self.assertRaises(ValidationError):
            CriterionEvidenceLinkCreate(annotation_id="ev_x", criterion_id="c_syn_1", rationale="   ")

    def test_conflict_and_span_handlers_are_machine_readable(self) -> None:
        conflict = asyncio.run(main.storage_conflict(None, storage.DuplicateLink("该引用已关联此评分要求")))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(json.loads(conflict.body)["code"], "duplicate_link")

        mismatch = asyncio.run(main.span_mismatch(None, storage.SpanMismatch()))
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(json.loads(mismatch.body)["code"], "span_mismatch")

    def test_rubrics_endpoint_lists_only_configured(self) -> None:
        self.assertEqual(len(main.available_rubrics()), 1)
        rubric_store.set_index({})
        self.assertEqual(main.available_rubrics(), [])


if __name__ == "__main__":
    unittest.main()
