# Engineering Quality Gates

RepoAtlas uses automated checks to make the supported behaviour reproducible.

## Continuous integration

The GitHub Actions workflow runs on Python 3.11, 3.12, 3.13, and 3.14. Each matrix job:

1. Installs the package and development dependencies.
2. Compares the parser adapter's grammar identifiers with the installed Tree-sitter language-pack manifest.
3. Downloads the explicitly requested grammars into the CI environment. Runtime repository scans never download grammars.
4. Runs Ruff over `src` and `tests`.
5. Runs pytest with coverage and enforces a minimum total coverage of 80%.

The CI matrix is the source of truth for compatibility claims. A local run on one interpreter does not establish that every matrix version passes.

Optional LLM code is tested with fake providers in CI; CI never requires an API key or makes external model calls. The live provider integration must be exercised separately by an operator with an approved API key and model configuration.

## Security and resource boundaries

- The scanner uses bounded file count and byte limits and excludes symlinks, common generated directories, common credential stores, and sensitive filenames.
- Full analysis and retrieval operations capture one in-memory repository snapshot, bounded by the configured total-byte limit. Parsing, ranking, and graph expansion consume this shared capture rather than re-reading source files.
- Snapshot identifiers are content-addressed from relative paths and file SHA-256 hashes. Citations include the relevant file hash, and validation rejects a citation if the file has changed since retrieval.
- Tree-sitter parsing only runs when the requested grammar is already cached.
- Tree-sitter files are capped at 1 MB; parsing has a time limit, and syntax traversal has node-count and depth limits.
- Python modules from the scanned repository are never imported or executed.
- Import resolution and call-reference resolution are conservative. Ambiguous or insufficiently evidenced edges remain unresolved.
- Impact analysis is a static estimate over resolved import edges; it is not a proof of runtime blast radius.
- Optional model requests receive only the user question and retrieved, secret-redacted excerpts—not the full repository. The provider receives source code only when the answer command or endpoint is explicitly invoked.
- Model output is constrained to a strict JSON schema. Every claim must reference evidence IDs from the retrieved pack; unknown IDs and stale file hashes are rejected.
- Citation validation establishes path containment, line bounds, and file-hash freshness. It does not prove semantic entailment. Prompt-injection resistance is a defence-in-depth measure, not a guarantee.

## Test design

Tests use temporary directories and synthetic fixtures. They cover the scanner's exclusions, parser fallbacks, language extraction, graph resolution, transitive impact, CLI/API behaviour, evidence citations, credential redaction, strict LLM output validation, unknown evidence IDs, stale citations, and provider failure paths.

When adding a parser adapter or resolver rule, add tests for:
- a representative valid source fixture;
- an edge case or malformed input;
- an ambiguous or unresolved dependency;
- the expected line provenance;
- relevant resource or path safety boundaries.

## Interpreting coverage

Coverage is a regression guard, not a correctness proof. The enforced 80% floor helps prevent untested growth, while code review and focused adversarial tests remain necessary—especially for parsers, path handling, and dependency inference.
