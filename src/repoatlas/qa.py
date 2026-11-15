"""Evidence-first question answering without a model-provider dependency."""
from __future__ import annotations

from pathlib import Path

from repoatlas.analyzer import analyze_repository
from repoatlas.search import search_repository
from repoatlas.security import redact_secrets


def answer_question(root: str | Path, question: str, *, top_k: int = 6) -> dict:
    base = Path(root).expanduser().resolve(strict=True)
    report = analyze_repository(base)
    expanded_question = question + " " + " ".join(
        token.removesuffix("s") for token in question.lower().split() if len(token) > 3
    )
    hits = search_repository(base, expanded_question, top_k=top_k)
    evidence = []
    for hit in hits:
        evidence.append({
            "citation": {"path": hit.path, "start_line": hit.start_line,
                         "end_line": hit.end_line, "revision": report.revision},
            "score": hit.score, "reason": hit.reason, "excerpt": redact_secrets(hit.excerpt),
        })
    return {
        "question": question, "repository": str(base), "revision": report.revision,
        "answer": (
            "The following repository evidence is relevant to your question. "
            "This baseline release provides retrieved evidence, not an LLM-generated conclusion. "
            "Review the cited source before making an engineering decision."
            if evidence else
            "No matching source evidence was found. This does not prove the behaviour is absent; "
            "the repository may use unsupported languages or terminology."
        ),
        "evidence": evidence,
        "limitations": [
            "Retrieval is lexical in this release; semantic retrieval and runtime tracing "
            "are not implemented.",
            "Python symbol extraction uses static AST parsing and does not infer "
            "dynamic behaviour.",
            "Secret detection uses heuristics and cannot guarantee complete credential removal.",
        ],
    }

def validate_citation(root: str | Path, citation: dict) -> bool:
    base = Path(root).resolve(strict=True)
    raw = citation.get("path", "")
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        return False
    unresolved = base / raw
    if unresolved.is_symlink():
        return False
    target = unresolved.resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError:
        return False
    if not target.is_file():
        return False
    try:
        line_count = len(target.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False
    start, end = citation.get("start_line"), citation.get("end_line")
    return (
        isinstance(start, int)
        and isinstance(end, int)
        and 1 <= start <= end <= max(line_count, 1)
    )
