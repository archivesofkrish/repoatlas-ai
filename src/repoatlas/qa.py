"""Evidence-first question answering without a model-provider dependency."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from repoatlas.scanner import create_snapshot
from repoatlas.search import search_snapshot
from repoatlas.security import redact_secrets


def answer_question(root: str | Path, question: str, *, top_k: int = 6) -> dict:
    """Build an evidence pack from one source snapshot."""
    snapshot = create_snapshot(root)
    expanded_question = question + " " + " ".join(
        token.removesuffix("s") for token in question.lower().split() if len(token) > 3
    )
    hits = search_snapshot(snapshot, expanded_question, top_k=top_k)
    evidence = []
    for hit in hits:
        evidence.append({
            "citation": {
                "path": hit.path,
                "start_line": hit.start_line,
                "end_line": hit.end_line,
                "revision": snapshot.revision,
                "snapshot_id": snapshot.snapshot_id,
                "sha256": hit.sha256,
            },
            "score": hit.score,
            "reason": hit.reason,
            "excerpt": redact_secrets(hit.excerpt),
        })
    return {
        "question": question,
        "repository": str(Path(snapshot.root)),
        "revision": snapshot.revision,
        "snapshot_id": snapshot.snapshot_id,
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
            "Citations are bound to the captured snapshot and rejected when source-file content "
            "changes after retrieval.",
        ],
    }


def validate_citation(root: str | Path, citation: dict) -> bool:
    """Validate source containment, line bounds, and optional content-hash freshness."""
    try:
        base = Path(root).resolve(strict=True)
        raw = citation.get("path", "")
        if (
            not isinstance(raw, str)
            or not raw
            or Path(raw).is_absolute()
            or ".." in Path(raw).parts
        ):
            return False
        unresolved = base / raw
        if unresolved.is_symlink():
            return False
        target = unresolved.resolve(strict=False)
        target.relative_to(base)
        if not target.is_file():
            return False
        content = target.read_bytes()
        expected_sha256 = citation.get("sha256")
        if expected_sha256 is not None:
            if (
                not isinstance(expected_sha256, str)
                or len(expected_sha256) != 64
                or not hmac.compare_digest(
                    hashlib.sha256(content).hexdigest(),
                    expected_sha256.lower(),
                )
            ):
                return False
        lines = content.decode("utf-8").splitlines()
        start, end = citation.get("start_line"), citation.get("end_line")
        return (
            type(start) is int
            and type(end) is int
            and 1 <= start <= end <= max(len(lines), 1)
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return False
