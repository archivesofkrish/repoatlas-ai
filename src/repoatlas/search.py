"""Deterministic lexical retrieval with line-level evidence references."""
from __future__ import annotations
import math
import re
from collections import Counter
from pathlib import Path
from repoatlas.models import SearchHit
from repoatlas.scanner import scan_files

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
STOPWORDS = {"the", "and", "for", "that", "this", "with", "from", "into", "where", "what", "when", "does", "have", "are", "was", "how", "can", "you", "your", "about", "which"}

def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if token.lower() not in STOPWORDS]

def _tokens_with_identifiers(text: str) -> list[str]:
    tokens = tokenize(text)
    for token in list(tokens):
        tokens.extend(part.lower() for part in re.split(r"[_\W]+", token) if len(part) > 1)
    return tokens

def search_repository(root: str | Path, query: str, *, top_k: int = 8, context_lines: int = 2, **scan_limits) -> list[SearchHit]:
    if not query.strip():
        raise ValueError("Query must not be empty")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    if not 0 <= context_lines <= 20:
        raise ValueError("context_lines must be between 0 and 20")
    base = Path(root).expanduser().resolve(strict=True)
    files, _, _ = scan_files(base, **scan_limits)
    query_terms = _tokens_with_identifiers(query)
    if not query_terms:
        raise ValueError("Query did not contain searchable terms")
    documents: list[tuple[str, list[str], list[str]]] = []
    df: Counter[str] = Counter()
    for item in files:
        try:
            lines = (base / item.path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        words = _tokens_with_identifiers("\n".join(lines))
        documents.append((item.path, lines, words))
        df.update(set(words))
    n_docs = max(len(documents), 1)
    hits: list[SearchHit] = []
    for path, lines, words in documents:
        tf = Counter(words)
        score = 0.0
        matched = []
        for term in set(query_terms):
            if tf[term]:
                idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (1 + math.log(tf[term]))
                matched.append(term)
        if score <= 0:
            continue
        best_index, best_score = 0, -1
        for i, line in enumerate(lines):
            local = len(set(_tokens_with_identifiers(line)).intersection(matched))
            if local > best_score:
                best_index, best_score = i, local
        start = max(0, best_index - context_lines)
        end = min(len(lines), best_index + context_lines + 1)
        excerpt = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
        hits.append(SearchHit(path=path, start_line=best_index + 1, end_line=best_index + 1,
                              score=round(score, 4), excerpt=excerpt,
                              reason="Matched terms: " + ", ".join(sorted(matched))))
    return sorted(hits, key=lambda hit: (-hit.score, hit.path))[:top_k]
