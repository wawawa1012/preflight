"""Offline manifest runner; reports known gaps separately from assertion success.

No live mode, configuration loading, or API calls. Run a single case with --case.
Uses the existing unittest fixtures, not another evaluation framework.
"""
import argparse
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Single manifest case ID, e.g. C-A3; default: all offline cases")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "benchmark" / "agent-evaluation-manifest.json").read_text(encoding="utf-8"))
    cases = [case for case in manifest["cases"] if args.case is None or case["case_id"] == args.case]
    if not cases:
        parser.error("Unknown case ID")
    failed = 0
    for case in cases:
        suite = unittest.defaultTestLoader.loadTestsFromName(case["test"])
        result = unittest.TestResult()
        suite.run(result)
        ok = result.wasSuccessful() and result.testsRun == 1 and not result.skipped
        failed += not ok
        print(json.dumps({"case_id": case["case_id"], "role": case["role"], "assertions_passed": ok,
                          "observed_result": case["observed_result"], "known_limitation": case["known_limitation"],
                          "live_semantic_quality": "not_evaluated"}, ensure_ascii=False))
        for _test, traceback in result.errors + result.failures:
            print(traceback, file=sys.stderr)
    print(json.dumps({"offline_cases": len(cases), "assertion_failures": failed,
                      "semantic_safety_verdict": "not_established"}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
