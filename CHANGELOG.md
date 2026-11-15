# Changelog

## 0.5.0 - 2026-11-15

- Add an optional OpenAI Responses API provider behind the `llm` extra.
- Add CLI `repoatlas answer` and HTTP endpoint `POST /v1/answer`; keep `ask` retrieval-only.
- Require strict structured claim output with one or more allow-listed evidence IDs per claim.
- Revalidate repository containment, line ranges, and cited-file SHA-256 after generation.
- Skip provider calls when retrieval returns no evidence; reject unknown or stale citations.
- Send only bounded, secret-redacted retrieved excerpts and the question when answer generation is explicitly invoked.
- Add LLM safety guidance and fake-provider tests; no live API key is required by CI.


## 0.4.0 - 2026-11-15

- Introduce bounded, content-addressed in-memory repository snapshots.
- Reuse the same captured source text for parsing, lexical ranking, and dependency-graph expansion.
- Attach per-file SHA-256 and snapshot identifiers to search results and evidence citations.
- Reject citations when the source file changes after retrieval.
- Detect Git HEAD changes during snapshot capture and avoid assigning a misleading revision.
- Preserve the metadata-only `scan_files` API for existing callers.

## 0.3.0 - 2026-11-15

- Add graph-aware hybrid retrieval with explicit multi-hop import provenance.
- Add a four-scenario synthetic benchmark for MRR@k, Recall@k, and nDCG@k.
- Add hybrid search CLI and API endpoints.

## 0.2.0 - 2026-11-15

- Add multi-language static parsing, dependency graphs, and change-impact analysis.
- Add CI coverage enforcement and documented quality gates.

## 0.1.0 - 2026-11-15

- Initial safe scanner, Python AST analysis, lexical retrieval, evidence packs, CLI, and local API.
