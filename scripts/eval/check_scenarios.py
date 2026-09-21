"""Eval-only scenario lint (stdlib only, never imports product code).

Checks for benchmark/uat + benchmark/stakeholders scenario files:
1. Required 8 black-box sections present (USER GOAL / STARTING STATE / TASK /
   ALLOWED KNOWLEDGE / SUCCESS CONDITION / BLOCKED CONDITION / TRUST FAILURE / METRICS).
2. Forbidden implementation references absent (internal API / DB / oracle / code paths).
3. Report reminder: verdicts must not be pre-declared on a changing UI.

Usage (from repo root of the eval worktree):
    python scripts/eval/check_scenarios.py
Exit 0 = all files pass. Exit 1 = violations listed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET_DIRS = [REPO / "benchmark" / "uat" / "scenarios"]
LAB_SCENARIOS = REPO / "benchmark" / "stakeholders" / "scenarios"
if LAB_SCENARIOS.is_dir():
    TARGET_DIRS.append(LAB_SCENARIOS)

REQUIRED = [
    "USER GOAL",
    "STARTING STATE",
    "TASK",
    "ALLOWED KNOWLEDGE",
    "SUCCESS CONDITION",
    "BLOCKED CONDITION",
    "TRUST FAILURE",
    "METRICS",
]

# Heuristics for implementation leakage (case-insensitive, word-ish).
FORBIDDEN = [
    r"/api/v1",
    r"\bSELECT\b.*\bFROM\b",
    r"\bsqlite\b",
    r"backend/logs",
    r"backend\.app",
    r"frontend/src",
    r"\.py:\d+",
    r"Traceback \(most recent call last\)",
    r"golden-v2[^\n]*\u7b54\u6848",  # golden answer pasted as oracle
]

failures: list[str] = []


def check_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    ok = True
    for section in REQUIRED:
        if section not in text:
            failures.append(f"{path.name}: missing section '{section}'")
            ok = False
    for pat in FORBIDDEN:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            failures.append(f"{path.name}: forbidden pattern '{pat}' near: ...{text[max(0, m.start()-30):m.end()+30]!r}...")
            ok = False
    return ok


def main() -> int:
    files: list[Path] = []
    for d in TARGET_DIRS:
        if d.is_dir():
            files.extend(sorted(d.glob("*.md")))
    if not files:
        print("check_scenarios: no scenario files found")
        return 1
    passed = 0
    for f in files:
        if check_file(f):
            passed += 1
    print(f"check_scenarios: {passed}/{len(files)} files pass")
    if failures:
        print("violations:")
        for v in failures:
            print(f"  - {v}")
        return 1
    print("note: scenarios are assets only; no verdict on changing UI (see sprint1_gate.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
