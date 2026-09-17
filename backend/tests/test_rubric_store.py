"""Iteration 4：只读 rubric 文件仓的加载、fail-fast 与幂等性测试（合成 rubrics，test-only）。"""
import json
import tempfile
import unittest
from pathlib import Path

from app.rubric_store import RubricFileError, get_rubric, list_rubrics, load_index, reset_index, set_index


def rubric_payload(rubric_id: str = "rubric_syn", revision: int = 1, title: str = "Synthetic rubric (test-only)"):
    return {
        "id": rubric_id,
        "revision": revision,
        "title": title,
        "source_note": "test-only synthetic",
        "criteria": [
            {"id": "c_syn_1", "title": "Criterion A", "requirement": "requirement A", "required_evidence": ["x"]},
            {"id": "c_syn_2", "title": "Criterion B", "requirement": "requirement B", "required_evidence": ["y"]},
        ],
    }


class RubricStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)

    def tearDown(self) -> None:
        reset_index()
        self._tmp.cleanup()

    def write(self, name: str, payload) -> None:
        (self.directory / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_load_valid_files_and_helpers(self) -> None:
        self.write("a.json", rubric_payload())
        self.write("b.json", rubric_payload("rubric_other", 2))
        index = load_index(self.directory)
        self.assertEqual(set(index), {("rubric_syn", 1), ("rubric_other", 2)})
        set_index(index)
        self.assertEqual(len(list_rubrics()), 2)
        self.assertEqual(get_rubric("rubric_syn", 1).criteria[0].id, "c_syn_1")
        self.assertIsNone(get_rubric("rubric_syn", 99))

    def test_empty_directory_is_valid(self) -> None:
        self.assertEqual(load_index(self.directory), {})
        set_index({})
        self.assertEqual(list_rubrics(), [])

    def test_invalid_json_fails_fast(self) -> None:
        (self.directory / "broken.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(RubricFileError):
            load_index(self.directory)

    def test_invalid_contract_fails_fast(self) -> None:
        payload = rubric_payload()
        del payload["title"]
        self.write("bad.json", payload)
        with self.assertRaises(RubricFileError):
            load_index(self.directory)

    def test_duplicate_key_fails_fast(self) -> None:
        self.write("one.json", rubric_payload())
        self.write("two.json", rubric_payload())
        with self.assertRaises(RubricFileError):
            load_index(self.directory)

    def test_new_revision_keeps_old_content(self) -> None:
        self.write("rev1.json", rubric_payload(revision=1))
        first = load_index(self.directory)
        self.write("rev2.json", rubric_payload(revision=2, title="Synthetic rev2 (test-only)"))
        second = load_index(self.directory)
        self.assertEqual(set(second), {("rubric_syn", 1), ("rubric_syn", 2)})
        self.assertEqual(second[("rubric_syn", 1)].model_dump(), first[("rubric_syn", 1)].model_dump())


if __name__ == "__main__":
    unittest.main()
