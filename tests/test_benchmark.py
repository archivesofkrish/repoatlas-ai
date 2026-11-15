from benchmarks.evaluate_retrieval import evaluate_retrieval


def test_hybrid_retrieval_recovers_graph_only_context_across_benchmark_cases():
    result = evaluate_retrieval(top_k=5)
    lexical = result["metrics"]["lexical"]
    hybrid = result["metrics"]["hybrid"]

    lexical_cases = {item["id"]: item for item in lexical["cases"]}
    hybrid_cases = {item["id"]: item for item in hybrid["cases"]}

    for case in result["case_definitions"]:
        lexical_paths = set(lexical_cases[case["id"]]["ranked_paths"])
        hybrid_paths = set(hybrid_cases[case["id"]]["ranked_paths"])
        for expected_path in case["graph_only_relevant"]:
            assert expected_path not in lexical_paths
            assert expected_path in hybrid_paths

    assert hybrid["recall_at_k"] > lexical["recall_at_k"]
    assert 0.0 <= hybrid["mrr_at_k"] <= 1.0
    assert 0.0 <= hybrid["ndcg_at_k"] <= 1.0
