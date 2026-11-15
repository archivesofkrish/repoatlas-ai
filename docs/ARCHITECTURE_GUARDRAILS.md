# Architecture Guardrails

## Purpose

Architecture Guardrails turns the package dependency graph into explicit, reviewable design rules. It is opt-in: the engineering team defines intended boundaries, and RepoAtlas checks the observed static graph against them.

## Policy schema

Policies are UTF-8 JSON objects with `schema_version: 1`:

| Field | Meaning |
|---|---|
| `allowed_package_dependencies` | Map a source package to the complete set of package names it may import. |
| `forbidden_package_dependencies` | Explicit source/target package pairs that must not appear. Optional `reason` is shown in findings. |
| `max_cross_package_imports` | Maximum number of statically resolved file-import edges leaving each named package. |
| `fail_on_cycles` | Treat each detected strongly connected component as a policy violation. |

A policy must define at least one active rule. Package names match architecture-report package labels; the root package is `.`. Names are exact and case-sensitive. See [the example policy](../examples/architecture-policy.json).

## Usage

```bash
repoatlas guard PATH --policy ./architecture-policy.json --json
repoatlas guard PATH --policy ./architecture-policy.json --output ./artifacts/guardrails.html
```

The output includes PASS/FAIL status, rule counts, severity, package relationships and up to five representative source-file import edges. The HTTP API offers the same evaluator at `POST /v1/architecture/guardrails`; send `path` and the policy object.

## Interpretation and governance

- PASS means no configured rule was violated by the observed statically resolved package graph.
- Runtime dependency injection, reflection, dynamic imports, generated code and plugin wiring may not appear in the graph.
- Cycle rules operate on strongly connected components. A cycle is a structural signal, not proof of runtime failure.
- Cross-package import caps count resolved file-import edges, not distinct package pairs.
- Policy files are JSON data. RepoAtlas validates the schema and does not execute source or policy content.
- Version policies beside the application and review changes as architectural decisions. Overly strict or stale rules can create noise.

The report is advisory. It does not modify source code, block a build or change the repository.
