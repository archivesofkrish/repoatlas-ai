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
pytest -q
```

## Pull request expectations

- Explain the user problem and intended behaviour.
- Add tests for normal, boundary, and adversarial inputs where relevant.
- Keep repository ingestion read-only; do not execute untrusted project code.
- Preserve file paths, line ranges, and revision provenance for evidence.
- Do not claim security findings without supporting evidence.
- Update documentation when behaviour or limitations change.

## Scope

The initial release intentionally uses deterministic lexical retrieval and Python AST analysis. New language support, semantic retrieval, external model providers, and automated actions require explicit design and security review.
