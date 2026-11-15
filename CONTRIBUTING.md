# Contributing

Thanks for helping improve RepoAtlas AI. Contributions should preserve its core promise: revision-aware explanations grounded in inspectable repository evidence.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

## Local checks

```bash
ruff check src tests
pytest --cov=repoatlas --cov-report=term-missing --cov-fail-under=80
```

## Pull request expectations

- Explain the user problem and intended behaviour.
- Add tests for normal, boundary, and adversarial inputs where relevant.
- Keep repository ingestion read-only; do not execute untrusted project code.
- Preserve file paths, line ranges, and revision provenance for evidence.
- Do not claim security findings without supporting evidence.
- Update documentation when behaviour or limitations change.

## Scope

The current release combines deterministic lexical retrieval, Python AST analysis, and optional Tree-sitter parsing for supported languages. New language support, semantic or model-assisted retrieval, external model providers, and automated actions require explicit design, evaluation, and security review.
