# Changelog

## 0.7.0 - 2026-11-15

- Add a change-review workbench comparing the current working tree with a selected Git base reference.
- Trace changed source files to direct and transitive dependants through resolved static import edges.
- Render a responsive, self-contained offline HTML dashboard with filtering, impact map, module inspector and JSON export.
- Expose the review operation through the CLI and document working-tree scope and analysis limitations.


## 0.6.0 - 2026-11-15

- Add architecture intelligence for file-level dependency hotspots, package boundaries, isolated files, and strongly connected import cycles.
- Add a self-contained interactive HTML dependency explorer with search, package/language filters, module inspection, and pan/zoom controls.
- Add the `repoatlas architecture` CLI command and `POST /v1/architecture` API endpoint.
- Keep the analysis static and read-only; unresolved imports and architectural limitations remain explicit.

## 0.5.1 - 2026-11-15

- Harden local API workspace path resolution through a shared validator that rejects paths outside `REPOATLAS_ROOT`.
- Reject non-finite hybrid-search numeric input at the Pydantic request boundary.
- Add regression coverage for path traversal and API numeric constraints.
- Document HTTP input validation and the local-only API deployment boundary.

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
