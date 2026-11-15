"""Reproducible retrieval benchmark over the checked-in synthetic corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from repoatlas.hybrid import hybrid_search_repository
from repoatlas.search import search_repository

BENCHMARK_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BENCHMARK_DIR / "corpus"
CASES_PATH = BENCHMARK_DIR / "cases.json"


def _reciprocal_rank(paths: list[str], relevant: set[str]) -> float:
    for rank, path in enumerate(paths, start=1):
        if path in relevant:
            return 1.0 / rank
    return 0.0


def _recall(paths: list[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    return len(set(paths) & relevant) / len(relevant)


def _ndcg(paths: list[str], relevant: set[str], k: int) -> float:
    import math

    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, path in enumerate(paths[:k], start=1)
        if path in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal if ideal else 0.0


def evaluate_retrieval(
    corpus: Path = CORPUS_DIR,
    cases_path: Path = CASES_PATH,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Evaluate lexical and hybrid retrieval using MRR, Recall, and nDCG at k."""
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if cases.get("dataset_version") != "1.1" or not cases.get("cases"):
        raise ValueError("Unsupported or empty benchmark dataset")

    modes = {
        "lexical": lambda query: search_repository(corpus, query, top_k=top_k),
        "hybrid": lambda query: hybrid_search_repository(
            corpus, query, top_k=top_k, graph_depth=2
        ),
    }
    per_mode: dict[str, dict[str, Any]] = {}
    for mode_name, retrieve in modes.items():
        per_case = []
        for case in cases["cases"]:
            relevant = set(case["relevant"])
            hits = retrieve(case["query"])
            paths = [hit.path for hit in hits]
            per_case.append({
                "id": case["id"],
                "query": case["query"],
                "ranked_paths": paths,
                "mrr": _reciprocal_rank(paths, relevant),
                "recall": _recall(paths, relevant),
                "ndcg": _ndcg(paths, relevant, top_k),
            })
        count = max(len(per_case), 1)
        per_mode[mode_name] = {
            "mrr_at_k": round(sum(item["mrr"] for item in per_case) / count, 4),
            "recall_at_k": round(sum(item["recall"] for item in per_case) / count, 4),
            "ndcg_at_k": round(sum(item["ndcg"] for item in per_case) / count, 4),
            "cases": per_case,
        }

    return {
        "dataset": cases["dataset_version"],
        "top_k": top_k,
        "description": cases.get("description", ""),
        "case_definitions": cases["cases"],
        "metrics": per_mode,
        "interpretation": (
            "Metrics are measured on a small synthetic benchmark and are intended for "
            "regression detection, not as a claim of general retrieval quality."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RepoAtlas retrieval quality")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(evaluate_retrieval(top_k=args.top_k), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
