# Retrieval benchmark

Run the checked-in, deterministic synthetic corpus benchmark from the repository root:

```bash
python benchmarks/evaluate_retrieval.py --top-k 5
```

The evaluator compares the original lexical ranker with the hybrid ranker over versioned query cases. It reports:

- **MRR@k** — how early the first relevant file appears.
- **Recall@k** — the fraction of known relevant files retrieved.
- **nDCG@k** — ranking quality with higher credit for relevant files near the top.

Dataset version 1.1 includes four query scenarios: password registration, tenant scoping, credential revocation, and role-based permissions. Each scenario contains an implementation, an API consumer, a downstream workflow, and a lexical decoy. The cases identify files expected to be found only through the import graph, so the test checks structural recall rather than just whether the command returns results.

The corpus is intentionally small and transparent. It is suitable for preventing regressions while developing retrieval; it is not large enough to support claims about performance on arbitrary repositories. Expand it with reviewed examples from multiple languages, repository sizes, and query intents before using it as a general quality claim.
