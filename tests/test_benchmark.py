from benchmarks.evaluate_retrieval import evaluate_retrieval


def test_hybrid_retrieval_recovers_transitive_context_in_benchmark():
    result = evaluate_retrieval(top_k=5)
    lexical = result["metrics"]["lexical"]
    hybrid = result["metrics"]["hybrid"]

    lexical_paths = set(lexical["cases"][0]["ranked_paths"])
    hybrid_paths = set(hybrid["cases"][0]["ranked_paths"])
    assert "src/services/onboarding.py" not in lexical_paths
    assert "src/services/onboarding.py" in hybrid_paths
    assert hybrid["recall_at_k"] > lexical["recall_at_k"]
    assert 0.0 <= hybrid["mrr_at_k"] <= 1.0
    assert 0.0 <= hybrid["ndcg_at_k"] <= 1.0
