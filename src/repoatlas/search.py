"""Deterministic lexical retrieval over immutable repository snapshots."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from repoatlas.models import RepositorySnapshot, SearchHit
from repoatlas.scanner import create_snapshot

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "where",
    "what", "when", "does", "have", "are", "was", "how", "can", "you",
    "your", "about", "which",
}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if token.lower() not in STOPWORDS]


def _tokens_with_identifiers(text: str) -> list[str]:
    """Tokenize identifiers both whole and by underscore boundaries."""
    tokens = tokenize(text)
    for token in list(tokens):
        tokens.extend(part.lower() for part in re.split(r"[_\W]+", token) if len(part) > 1)
    return tokens


def search_snapshot(
    snapshot: RepositorySnapshot,
    query: str,
    *,
    top_k: int = 8,
    context_lines: int = 2,
) -> list[SearchHit]:
    """Search captured source text without any additional filesystem reads."""
    if not query.strip():
        raise ValueError("Query must not be empty")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    if not 0 <= context_lines <= 20:
        raise ValueError("context_lines must be between 0 and 20")
    query_terms = _tokens_with_identifiers(query)
    if not query_terms:
        raise ValueError("Query did not contain searchable terms")

    documents: list[tuple[str, list[str], list[str], str]] = []
    document_frequency: Counter[str] = Counter()
    for document in snapshot.documents:
        path = document.metadata.path
        lines = document.content.splitlines()
        words = _tokens_with_identifiers("\n".join(lines))
        documents.append((path, lines, words, document.metadata.sha256))
        document_frequency.update(set(words))

    document_count = max(len(documents), 1)
    hits: list[SearchHit] = []
    for path, lines, words, file_sha256 in documents:
        term_frequency = Counter(words)
        score = 0.0
        matched = []
        for term in set(query_terms):
            if term_frequency[term]:
                inverse_frequency = math.log(
                    1 + (document_count - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                score += inverse_frequency * (1 + math.log(term_frequency[term]))
                matched.append(term)
        if score <= 0:
            continue

        best_index, best_score = 0, -1
        for index, line in enumerate(lines):
            local_score = len(set(_tokens_with_identifiers(line)).intersection(matched))
            if local_score > best_score:
                best_index, best_score = index, local_score

        start = max(0, best_index - context_lines)
        end = min(len(lines), best_index + context_lines + 1)
        excerpt = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
        hits.append(
            SearchHit(
                path=path,
                start_line=best_index + 1,
                end_line=best_index + 1,
                score=round(score, 4),
                excerpt=excerpt,
                reason="Matched terms: " + ", ".join(sorted(matched)),
                sha256=file_sha256,
                snapshot_id=snapshot.snapshot_id,
                revision=snapshot.revision,
            )
        )
    return sorted(hits, key=lambda hit: (-hit.score, hit.path))[:top_k]


def search_repository(
    root: str | Path,
    query: str,
    *,
    top_k: int = 8,
    context_lines: int = 2,
    **scan_limits,
) -> list[SearchHit]:
    """Capture a bounded snapshot and search it without re-reading indexed files."""
    snapshot = create_snapshot(root, **scan_limits)
    return search_snapshot(snapshot, query, top_k=top_k, context_lines=context_lines)
