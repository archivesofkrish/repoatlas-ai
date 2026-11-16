# RepoAtlas AI — Engineering Audit

**Review date:** 16 November 2026  
**Reviewed revision:** ebba6eabf80d0ae9bdc7628a5540d30547bad2f1 (branch audit/engineering-baseline-2026-11, initially based on main)  
**Scope:** repository scanner, snapshot capture, Python analysis, dependency graph, hybrid retrieval, LLM evidence flow, API path handling, change review and architecture guardrails.  
**Review type:** source-level engineering review and targeted security hardening. This is not a third-party penetration test or a formal security certification.

## Executive summary

RepoAtlas has a sound architectural foundation: read-only scanning, bounded snapshots, content hashes, conservative dependency resolution, explicit opt-in model calls, structured claims and stale-source citation rejection. The main risks are at trust boundaries: local credential discovery, path/filesystem race resistance, per-request resource multiplication, and the distinction between citation provenance and semantic correctness.

One actionable gap was confirmed and fixed in this branch: several common CLI credential stores were not covered by the scanner's sensitive-path exclusions. The new regression test verifies those paths are excluded before content is opened.

## Findings

| ID | Severity | Area | Finding | Status |
|---|---|---|---|---|
| RA-01 | Medium | Scanner / LLM data boundary | GitHub CLI, Docker, Kubernetes and Azure CLI credential locations were not all excluded by path. Ordinary YAML/JSON credential files could therefore be indexed and, during an explicit model-answer request, selected as evidence. | **Fixed in this branch** |
| RA-02 | Medium | Filesystem safety | The scanner checks symlinks and file metadata before opening a path. A concurrently modified workspace can create a check/open race. The existing read-only design and non-following directory walk reduce exposure, but do not establish race-free file opening. | Follow-up hardening |
| RA-03 | Medium | API resource isolation | Per-scan limits bound an individual analysis, but simultaneous API requests can each allocate a bounded snapshot and parser/graph workload. The local-only deployment guidance is appropriate; a shared concurrency and aggregate-work budget is a useful next safeguard. | Follow-up hardening |
| RA-04 | Medium | Grounded answers | Evidence IDs, source hashes and line ranges validate provenance and freshness, not semantic entailment. A model can still overstate what a cited excerpt establishes. The limitation is explicitly documented and must remain visible in the UI/API. | Known limitation; retain |
| RA-05 | Low | Architecture graph | Import and call edges are static approximations. Dynamic imports, reflection, dependency injection, conditional imports and runtime plugin loading can be unresolved or absent. The current conservative resolution policy is preferable to inventing edges. | Known limitation; improve language-specific coverage |

## Implemented hardening in this branch

- Exclude .azure, .docker and .kube credential directories in addition to the existing AWS, SSH and GnuPG locations.
- Exclude GitHub CLI and legacy Hub credential directories under .config.
- Exclude common standalone credential files such as .netrc, .git-credentials, .npmrc, .pypirc and Docker's legacy .dockercfg.
- Add a regression fixture containing representative credential material and assert that only the benign source file is indexed.
- Update README and changelog to describe the wider exclusion boundary.

These are defence-in-depth exclusions, not a guarantee that all secrets can be detected. New credential formats and repository-specific secret files may still require additional exclusions. Secret-pattern redaction remains heuristic.

## Positive controls observed

- Repository reads are bounded by file count, per-file size and total bytes.
- Symlinks are excluded; project code is not imported or executed by the scanner.
- Analysis and retrieval share captured source content and file hashes.
- Ambiguous dependency edges remain unresolved rather than being guessed.
- Provider-backed answers are explicit opt-in; the provider receives bounded selected excerpts, no tools and structured-output constraints.
- Unknown evidence identifiers and stale source hashes fail closed.
- API workspace paths are resolved and checked against the configured root.
- Architecture policy input is size-bounded, parsed as JSON, schema-validated and rendered with HTML escaping.

## Validation plan

For this change, run the complete supported Python matrix and coverage-enforced CI on the branch. The new scanner fixture must pass on Python 3.11–3.14. Review the resulting workflow run and PR checks before merging. No test result for this branch is claimed until GitHub Actions reports it.

Recommended next validation additions:
1. Adversarial path fixtures for symlink swaps and nested credential paths.
2. API load tests that exercise concurrent scans at the configured per-request limits.
3. A labelled multi-language retrieval benchmark with expected evidence, false-positive tracking and reproducible scores.
4. LLM redaction tests for nested JSON/YAML credential formats and multiline private-key material.

## Next development priorities

1. Close or explicitly mitigate scanner check/open race windows using safe file-descriptor-based opening where supported.
2. Add shared API concurrency controls and aggregate resource budgets.
3. Expand the benchmark corpus beyond the small synthetic retrieval set and publish per-query evidence judgments.
4. Improve graph resolution for language-specific package manifests while preserving explicit unresolved states.
5. Keep provenance validation and semantic answer quality as separate metrics.

## Security boundary

RepoAtlas is a local, read-only analysis tool. Do not expose its API publicly without authentication, authorization, rate limiting, isolation and an explicit data-processing review. Secret filtering is not a security guarantee. Provider-backed answering can disclose selected source excerpts to the configured provider; only use it for repositories approved for that disclosure.