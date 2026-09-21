"""架构边界 fitness checks：parser 进口白名单、storage 不依赖 parser、角色不私写来源规则。

这些测试扫描 app/*.py 的 import 与源码文本，防止未来 change amplification：
- 只有 source_ingest.py 允许 import B2 parser（source_adapters/txt_adapter/docx_adapter）；
- storage/database/migrations 不 import parser 或 source_ingest；
- evidence.resolve_source_ref 只有 source_authority 使用；span_matches 只有 consistency 与
  evidence 使用；
- 业务角色（consistency/grill/response_coach/repair_suggest/preflight_report/llm/...）不得
  自己按 locator.kind 做业务判断（位置展示统一走 source_authority 的 helper）。
"""
import ast
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PARSER_MODULES = {"source_adapters", "txt_adapter", "docx_adapter"}
# parser 包自身内部互相 import 属于实现细节；真正的“消费者”只有 source_ingest。
PARSER_PACKAGE = {"source_adapters.py", "txt_adapter.py", "docx_adapter.py"}
PARSER_CONSUMERS = {"source_ingest.py"} | PARSER_PACKAGE
PARSER_FREE_PERSISTENCE = {"storage.py", "database.py", "migrations.py"}

RESOLVE_SOURCE_REF_OWNERS = {"evidence.py", "source_authority.py"}
SPAN_MATCHES_OWNERS = {"evidence.py", "consistency.py"}

LOCATOR_KIND_OWNERS = {"source_authority.py", "storage.py"}


def app_files() -> list[Path]:
    return sorted(path for path in APP_DIR.glob("*.py"))


def imported_names(path: Path) -> set[str]:
    """收集 `from .x import y` 的 x 与 y、`import a.b` 的 a.b，便于白名单检查。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


class ParserImportWhitelistTest(unittest.TestCase):
    def test_only_source_ingest_imports_parsers(self) -> None:
        violations: list[str] = []
        for path in app_files():
            if path.name in PARSER_CONSUMERS:
                continue
            imported = imported_names(path)
            hits = PARSER_MODULES & imported
            if hits:
                violations.append(f"{path.name}: {sorted(hits)}")
        self.assertEqual(violations, [], f"只有 source_ingest.py 可以 import parser：{violations}")

    def test_storage_and_init_layers_do_not_import_parsers_or_ingest(self) -> None:
        violations: list[str] = []
        for path in app_files():
            if path.name not in PARSER_FREE_PERSISTENCE:
                continue
            imported = imported_names(path)
            hits = (PARSER_MODULES | {"source_ingest"}) & imported
            if hits:
                violations.append(f"{path.name}: {sorted(hits)}")
        self.assertEqual(violations, [], f"持久化/初始化层不得依赖 parser：{violations}")

    def test_storage_exposes_format_metadata_as_input(self) -> None:
        source = (APP_DIR / "storage.py").read_text(encoding="utf-8")
        self.assertIn("fmt: str | None = None", source)
        self.assertIn("parser_version: str | None = None", source)


class SourceRuleOwnershipTest(unittest.TestCase):
    def _owners(self, symbol: str) -> set[str]:
        owners = {"evidence.py"}  # 规则本体定义处
        for path in app_files():
            if symbol in imported_names(path):
                owners.add(path.name)
        return owners

    def test_resolve_source_ref_only_used_by_authority(self) -> None:
        self.assertEqual(self._owners("resolve_source_ref"), RESOLVE_SOURCE_REF_OWNERS)

    def test_span_matches_only_used_by_evidence_and_consistency(self) -> None:
        self.assertEqual(self._owners("span_matches"), SPAN_MATCHES_OWNERS)

    def test_business_roles_do_not_branch_on_locator_kind(self) -> None:
        violations: list[str] = []
        for path in app_files():
            if path.name in LOCATOR_KIND_OWNERS:
                continue
            if ".locator.kind" in path.read_text(encoding="utf-8"):
                violations.append(path.name)
        self.assertEqual(violations, [], f"业务角色不得按 locator.kind 做业务判断：{violations}")

    def test_roles_use_source_authority(self) -> None:
        for name in ("grill.py", "response_coach.py", "repair_suggest.py", "preflight_report.py", "storage.py"):
            imported = imported_names(APP_DIR / name)
            self.assertIn("SourceAuthority", imported, f"{name} 应通过 SourceAuthority 验证来源")


if __name__ == "__main__":
    unittest.main()
