from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from src.indexing.chroma_store import DEFAULT_CHROMA_DIR
from src.indexing.embedder import DEFAULT_MODEL_NAME
from src.retrieval.searcher import search


DEFAULT_QUERY_FILE = Path("data/samples/evaluation_queries.local.json")
DEFAULT_TOP_K = 3


def quiet_noisy_loggers() -> None:
    """Chroma 0.5.x may print telemetry warnings even when telemetry is disabled."""

    logging.getLogger("chromadb").setLevel(logging.CRITICAL)
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


@dataclass
class EvaluationCase:
    id: str
    collection: str
    query: str
    expected_keywords: list[str]
    notes: str = ""


def load_cases(path: str | Path) -> list[EvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvaluationCase(**item) for item in payload]


def contains_keywords(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return all(keyword.lower() in normalized for keyword in keywords)


def shorten(value: str, max_length: int = 95) -> str:
    value = " ".join(value.split())
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."


def evaluate_case(
    case: EvaluationCase,
    persist_dir: str | Path,
    model_name: str,
    top_k: int,
) -> tuple[bool, str]:
    results = search(
        query=case.query,
        collection_name=case.collection,
        persist_dir=persist_dir,
        model_name=model_name,
        top_k=top_k,
    )

    combined_text = "\n".join(result.text for result in results)
    passed = contains_keywords(combined_text, case.expected_keywords)

    if not results:
        return False, "no results"

    best = results[0]
    summary = f"top score={best.score:.4f}, citation={best.citation}"
    return passed, summary


def run_evaluation(
    query_file: str | Path = DEFAULT_QUERY_FILE,
    persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    model_name: str = DEFAULT_MODEL_NAME,
    top_k: int = DEFAULT_TOP_K,
) -> int:
    cases = load_cases(query_file)
    passed_count = 0

    for case in cases:
        passed, summary = evaluate_case(case, persist_dir, model_name, top_k)
        status = "PASS" if passed else "FAIL"
        if passed:
            passed_count += 1

        print(f"[{status}] {case.id}")
        print(f"  query: {shorten(case.query)}")
        print(f"  expected: {', '.join(case.expected_keywords)}")
        print(f"  {shorten(summary)}")

    print()
    print(f"Passed {passed_count}/{len(cases)} evaluation case(s)")
    return 0 if passed_count == len(cases) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run simple retrieval evaluation queries.")
    parser.add_argument("--query-file", default=str(DEFAULT_QUERY_FILE), help="Path to evaluation query JSON.")
    parser.add_argument("--persist-dir", default=str(DEFAULT_CHROMA_DIR), help="ChromaDB persistence folder.")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="Embedding model name.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of chunks to check per query.")
    return parser.parse_args()


def main() -> None:
    quiet_noisy_loggers()
    args = parse_args()
    raise SystemExit(
        run_evaluation(
            query_file=args.query_file,
            persist_dir=args.persist_dir,
            model_name=args.model,
            top_k=args.top_k,
        )
    )


if __name__ == "__main__":
    main()
