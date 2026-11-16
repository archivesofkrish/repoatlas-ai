# RepoAtlas AI — Engineering Audit

**Review date:** 16 November 2026  
**Reviewed revision:** 3cbe8aa4a83942bcb3a2d837154375e3f57c90ea (current main after PR #13)  
**Scope:** repository scanner, snapshot capture, Python analysis, dependency graph, hybrid retrieval, LLM evidence flow, API path handling, change review and architecture guardrails.  
**Review type:** source-level engineering review and targeted security hardening. This is not a third-party penetration test or a formal security certification.

## Executive summary

RepoAtlas has a sound architectural foundation: read-only scanning, bounded snapshots, content hashes, conservative dependency resolution, explicit opt-in model calls, structured claims and stale-source citation rejection. The main risks remain at trust boundaries: aggregate API resource use under concurrent requests, incomplete heuristic secret detection, provider disclosure boundaries, and the distinction between citation provenance and semantic correctness. Scanner credential exclusions and descriptor-based path opening have been strengthened on main. An overlapping-span redaction defect was found and fixed in PR #13.

## Findings

| ID | Severity | Area | Finding | Status |
|---|---|---|---|---|
| RA-01 | Medium | Scanner / LLM data boundary | GitHub CLI, Docker, Kubernetes and Azure CLI credential locations were not all excluded by path. Ordinary YAML/JSON credential files could therefore be indexed and, during an explicit model-answer request, selected as evidence. | **Fixed in this branch** |
| RA-02 | Medium | Filesystem safety | The scanner previously checked symlink and file metadata before a path-based open, leaving a check/open race for concurrently modified workspaces. | **Mitigated: POSIX descriptor-relative traversal pins directories and rejects symlink components; other platforms use identity checks** |
| RA-03 | Medium | API resource isolation | Per-scan limits bound an individual analysis, but simultaneous API requests can each allocate a bounded snapshot and parser/graph workload. The local-only deployment guidance is appropriate; a shared concurrency and aggregate-work budget is a useful next safeguard. | Follow-up hardening |
| RA-04 | Medium | Grounded answers | Evidence IDs, source hashes and line ranges validate provenance and freshness, not semantic entailment. A model can still overstate what a cited excerpt establishes. The limitation is explicitly documented and must remain visible in the UI/API. | Known limitation; retain |
| RA-05 | Low | Architecture graph | Import and call edges are static approximations. Dynamic imports, reflection, dependency injection, conditional imports and runtime plugin loading can be unresolved or absent. The current conservative resolution policy is preferable to inventing edges. | Known limitation; improve language-specific coverage |
| RA-06 | Medium | Secret redaction | Overlapping generic-assignment and specific-token matches were replaced using offsets from the original excerpt. A replacement could shift later offsets and leave a quote or fragment behind. | **Fixed in PR #13: coalesce overlapping spans and redact each merged span once** |
| RA-07 | High (deployment boundary) | API exposure | The local FastAPI service has no production authentication, tenant isolation, global rate limit or aggregate resource budget. Per-request limits do not prevent concurrent requests from multiplying memory and CPU load. | Local-only deployment; aggregate admission controls remain follow-up work |

## Implemented hardening on main

- Exclude common cloud and developer credential locations, including GitHub CLI, Docker, Kubernetes, Azure CLI, Git, npm and Python package-index credential stores.
- Use descriptor-relative, no-follow traversal for POSIX scanning to reduce parent-directory and final-component symlink replacement races; other platforms apply identity checks after opening.
- Coalesce overlapping detected-secret spans before replacement so one redaction cannot invalidate another match's offsets.
- Add regression tests for credential-store exclusions, path replacement and overlapping GitHub/AWS credential patterns.
- Preserve the warning that credential detection and redaction are heuristic and incomplete.

These are defence-in-depth exclusions, not a guarantee that all secrets can be detected. New credential formats and repository-specific secret files may still require additional exclusions. Secret-pattern redaction remains heuristic.

## Positive controls observed

- Repository reads are bounded by file count, per-file size and total bytes.
- Symlinks are excluded; POSIX file reads now use descriptor-relative no-follow traversal for parent directories and final files, while other platforms perform post-open file identity checks.
- Analysis and retrieval share captured source content and file hashes.
- Ambiguous dependency edges remain unresolved rather than being guessed.
- Provider-backed answers are explicit opt-in; the provider receives bounded selected excerpts, no tools and structured-output constraints.
- Unknown evidence identifiers and stale source hashes fail closed.
- API workspace paths are resolved and checked against the configured root.
- Architecture policy input is size-bounded, parsed as JSON, schema-validated and rendered with HTML escaping.

## Validation evidence

PR #13 passed the complete Python 3.11–3.14 CI matrix on its exact head revision (`1cc1bce5c74a8ea3b5cf01c42e6e16a9bac72502`). The merged `main` revision `3cbe8aa4a83942bcb3a2d837154375e3f57c90ea` also passed the post-merge CI run [43861582910](https://github.com/archivesofkrish/repoatlas-ai/actions/runs/43861582910).

Recommended next validation additions:
1. API load tests that exercise concurrent scans at the configured per-request limits.
2. A labelled multi-language retrieval benchmark with adjudicated expected evidence, false-positive tracking and reproducible scores.
3. Nested JSON/YAML credential fixtures and multiline private-key redaction tests.
4. Cross-platform scanner stress tests under concurrent path replacement.

## Next development priorities

1. Add shared API concurrency controls and aggregate scan/parse/graph work budgets, with cancellation and bounded queues.
2. Expand the retrieval benchmark beyond the small synthetic corpus; publish per-query evidence judgements and language-specific slices.
3. Improve package-manifest and language-specific graph resolution while preserving explicit unresolved states.
4. Measure evidence-claim entailment separately from citation provenance; do not treat source-hash verification as proof of semantic support.
5. Add cross-platform scanner stress tests for filesystem replacement and permission edge cases.

## Security boundary

RepoAtlas is a local, read-only analysis tool. Do not expose its API publicly without authentication, authorization, rate limiting, isolation and an explicit data-processing review. Secret filtering is not a security guarantee. Provider-backed answering can disclose selected source excerpts to the configured provider; only use it for repositories approved for that disclosure.