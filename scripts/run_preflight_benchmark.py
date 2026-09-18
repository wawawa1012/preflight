"""I5.1 预检质量 benchmark：默认 stub（不打网，CI 可跑）；live 由用户手动运行。

stub 用合成用例回归验证门与弃权路径；live 每个 criterion 调用一次真实 LLM，
结果写入 benchmark/results/（已 gitignore）。DS 不代打用户 API key。
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import llm  # noqa: E402
from app.contracts import Block, Criterion, Rubric  # noqa: E402
from app.evidence import QuoteNotFound, resolve_span  # noqa: E402
from app.markdown_preview import build_preview  # noqa: E402

CASES_DIR = ROOT / "benchmark" / "cases"
RESULTS_DIR = ROOT / "benchmark" / "results"

# stub：neg 诚实弃权（0 候选）；pos 命中可定位关键句。
STUB_QUOTES = {
    "neg_java": [],
    "pos_metrics": ["准确率达到 95%"],
}
LIVE_ERRORS = (llm.LlmNotConfigured, llm.LlmUnavailable, llm.LlmTimeout, llm.LlmInvalidResponse, llm.PromptTooLarge)


def load_case(case_name: str) -> tuple[list[Block], Rubric]:
    directory = CASES_DIR / case_name
    preview = build_preview("material.md", (directory / "material.md").read_bytes())
    rubric = Rubric.model_validate(json.loads((directory / "rubric.json").read_text(encoding="utf-8")))
    return preview.blocks, rubric


def verify(blocks: list[Block], candidates: list[llm.RawCandidate]) -> list[str]:
    """验证门：block 必须属于材料、quote 必须命中原文；返回通过的 quote 列表。"""
    by_id = {block.id: block for block in blocks}
    quotes: list[str] = []
    for candidate in candidates:
        block = by_id.get(candidate.block_id)
        if block is None:
            continue
        try:
            resolve_span(block.text, candidate.quote)
        except QuoteNotFound:
            continue
        quotes.append(candidate.quote)
    return quotes


def stub_candidates(case_name: str, blocks: list[Block]) -> list[llm.RawCandidate]:
    items = []
    for quote in STUB_QUOTES[case_name]:
        block = next((item for item in blocks if quote in item.text), None)
        if block is None:
            raise SystemExit(f"FAIL: stub quote not found in {case_name}: {quote}")
        items.append({"block_id": block.id, "quote": quote, "rationale": "stub (test-only)"})
    return llm.parse_candidates(json.dumps({"candidates": items}))


def run_stub() -> int:
    ok = True
    for case_name in sorted(STUB_QUOTES):
        blocks, rubric = load_case(case_name)
        candidate_count = 0
        passed_count = 0
        for criterion in rubric.criteria:
            candidates = stub_candidates(case_name, blocks)
            candidate_count += len(candidates)
            passed_count += len(verify(blocks, candidates))
        print(json.dumps({"case": case_name, "passed_count": passed_count, "candidate_count": candidate_count}, ensure_ascii=False))
        if case_name == "neg_java" and candidate_count != 0:
            ok = False
        if case_name == "pos_metrics" and passed_count == 0:
            ok = False
    if not ok:
        print("FAIL: stub expectations not met")
        return 1
    return 0


def run_live() -> int:
    llm.load_env_file()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    failures = 0
    for case_name in sorted(STUB_QUOTES):
        blocks, rubric = load_case(case_name)
        for criterion in rubric.criteria:
            prompt_chars: int | None = None
            try:
                messages = llm.build_messages(criterion, blocks)
                prompt_chars = sum(len(message["content"]) for message in messages)
                started = time.perf_counter()
                candidates, _, _, _ = llm.propose_candidates(criterion, blocks)
            except LIVE_ERRORS as exc:
                failures += 1
                entry = {"case": case_name, "criterion_id": criterion.id, "error": str(exc)}
                print(json.dumps(entry, ensure_ascii=False))
                results.append(entry)
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000
            quotes = verify(blocks, candidates)
            entry = {
                "case": case_name,
                "criterion_id": criterion.id,
                "block_count": len(blocks),
                "prompt_chars": prompt_chars,
                "elapsed_ms": round(elapsed_ms, 1),
                "passed_count": len(quotes),
                "quotes": quotes,
            }
            print(json.dumps(entry, ensure_ascii=False))
            results.append(entry)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = RESULTS_DIR / f"live_{stamp}.json"
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results written: {target.relative_to(ROOT)}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight proposal benchmark (stub by default)")
    parser.add_argument("--mode", choices=["stub", "live"], default="stub")
    args = parser.parse_args()
    if args.mode == "live":
        return run_live()
    return run_stub()


if __name__ == "__main__":
    raise SystemExit(main())
