"""Hybrid retrieval combining lexical matches with static dependency context."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from repoatlas.analyzer import analyze_snapshot
from repoatlas.graph import build_graph
from repoatlas.models import RepositorySnapshot, SearchHit, SourceDocument, Symbol
from repoatlas.scanner import create_snapshot
from repoatlas.search import _tokens_with_identifiers, search_snapshot

_GRAPH_DECAY = 0.72
_MAX_GRAPH_SEEDS = 20
_MAX_GRAPH_CANDIDATES = 500


def _context_hit(
    document: SourceDocument,
    snapshot: RepositorySnapshot,
    query_terms: set[str],
    symbols_by_path: dict[str, list[Symbol]],
    context_lines: int,
    score: float,
    reason: str,
) -> SearchHit | None:
    """Create structural evidence from the exact source text in the snapshot."""
    lines = document.content.splitlines()
    if not lines:
        return None

    item = document.metadata
    symbols = symbols_by_path.get(item.path, [])
    ranked_symbols = []
    for symbol in symbols:
        symbol_terms = set(_tokens_with_identifiers(
            " ".join((symbol.name, symbol.qualified_name, symbol.docstring or ""))
        ))
        overlap = len(query_terms.intersection(symbol_terms))
        ranked_symbols.append((overlap, -symbol.start_line, symbol.start_line))
    if ranked_symbols:
        best_overlap, _negative_line, anchor = max(ranked_symbols)
        if best_overlap == 0:
            anchor = min(symbol.start_line for symbol in symbols)
    else:
        anchor = next(
            (index + 1 for index, line in enumerate(lines) if line.strip()),
            1,
        )

    index = min(max(anchor - 1, 0), len(lines) - 1)
    start = max(0, index - context_lines)
    end = min(len(lines), index + context_lines + 1)
    excerpt = "\n".join(f"{line_no + 1}: {lines[line_no]}" for line_no in range(start, end))
    return SearchHit(
        path=item.path,
        start_line=index + 1,
        end_line=index + 1,
        score=round(score, 6),
        excerpt=excerpt,
        reason=reason,
        sha256=item.sha256,
        snapshot_id=snapshot.snapshot_id,
        revision=snapshot.revision,
    )


def hybrid_search_repository(
    root: str | Path,
    query: str,
    *,
    top_k: int = 8,
    graph_depth: int = 2,
    lexical_weight: float = 0.65,
    context_lines: int = 2,
    **scan_limits,
) -> list[SearchHit]:
    """Rank direct lexical evidence and graph-linked files from one source snapshot.

    Lexical matches remain the retrieval seeds. Graph expansion adds bounded, one-to-three
    hop dependency context and labels it explicitly; it never pretends that a related file
    contains a direct query match. All text, symbols, imports, and citations derive from the
    same content-addressed snapshot, avoiding repeated scans and mixed-source responses.
    """
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    if not 1 <= graph_depth <= 3:
        raise ValueError("graph_depth must be between 1 and 3")
    if not 0.1 <= lexical_weight <= 0.9:
        raise ValueError("lexical_weight must be between 0.1 and 0.9")
    if not 0 <= context_lines <= 20:
        raise ValueError("context_lines must be between 0 and 20")
    if not query.strip():
        raise ValueError("Query must not be empty")

    snapshot = create_snapshot(root, **scan_limits)
    lexical_hits = search_snapshot(
        snapshot,
        query,
        top_k=100,
        context_lines=context_lines,
    )
    if not lexical_hits:
        return []

    report = analyze_snapshot(snapshot)
    graph = build_graph(report)
    file_paths = {item.path for item in report.files}
    documents_by_path = {
        document.metadata.path: document for document in snapshot.documents
    }
    adjacency: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["kind"] != "imports" or not edge["resolved"]:
            continue
        source, target = str(edge["source"]), str(edge["target"])
        if source not in file_paths or target not in file_paths:
            continue
        via = f"{edge['path']}:{edge['line']}"
        adjacency[source].append((target, "dependency", via))
        adjacency[target].append((source, "dependent", via))
    for path in adjacency:
        adjacency[path].sort()

    maximum_lexical_score = max(hit.score for hit in lexical_hits) or 1.0
    lexical_by_path = {hit.path: hit for hit in lexical_hits}
    graph_signals: dict[str, tuple[float, str]] = {}
    seeds = lexical_hits[:_MAX_GRAPH_SEEDS]

    for seed in seeds:
        seed_strength = seed.score / maximum_lexical_score
        queue = deque([(seed.path, 0, seed_strength, [])])
        best_for_seed = {seed.path: seed_strength}
        while queue:
            current, depth, strength, chain = queue.popleft()
            if depth >= graph_depth:
                continue
            for neighbour, relation, via in adjacency.get(current, []):
                next_depth = depth + 1
                propagated = seed_strength * (_GRAPH_DECAY ** next_depth)
                if propagated <= best_for_seed.get(neighbour, 0.0):
                    continue
                best_for_seed[neighbour] = propagated
                next_chain = [
                    *chain,
                    f"{current} -[{relation}]-> {neighbour} (import at {via})",
                ]
                detail = (
                    f"related to lexical match {seed.path} by import path "
                    f"(distance {next_depth}; {'; '.join(next_chain)})"
                )
                previous = graph_signals.get(neighbour)
                if previous is None or propagated > previous[0]:
                    graph_signals[neighbour] = (propagated, detail)
                queue.append((neighbour, next_depth, propagated, next_chain))
                if len(graph_signals) >= _MAX_GRAPH_CANDIDATES:
                    break
            if len(graph_signals) >= _MAX_GRAPH_CANDIDATES:
                break
        if len(graph_signals) >= _MAX_GRAPH_CANDIDATES:
            break

    symbols_by_path: dict[str, list[Symbol]] = defaultdict(list)
    for symbol in report.symbols:
        symbols_by_path[symbol.path].append(symbol)
    for path in symbols_by_path:
        symbols_by_path[path].sort(key=lambda symbol: (symbol.start_line, symbol.qualified_name))

    query_terms = set(_tokens_with_identifiers(query))
    combined: list[SearchHit] = []
    for path in set(lexical_by_path) | set(graph_signals):
        lexical_hit = lexical_by_path.get(path)
        lexical_score = (
            lexical_hit.score / maximum_lexical_score if lexical_hit is not None else 0.0
        )
        graph_score, graph_reason = graph_signals.get(path, (0.0, ""))
        combined_score = (
            lexical_weight * lexical_score
            + (1.0 - lexical_weight) * graph_score
        )
        if lexical_hit is not None:
            reason = lexical_hit.reason
            if graph_reason:
                reason += f"; graph context: {graph_reason}"
            combined.append(SearchHit(
                path=lexical_hit.path,
                start_line=lexical_hit.start_line,
                end_line=lexical_hit.end_line,
                score=round(combined_score, 6),
                excerpt=lexical_hit.excerpt,
                reason=reason,
                sha256=lexical_hit.sha256,
                snapshot_id=snapshot.snapshot_id,
                revision=snapshot.revision,
            ))
        elif graph_reason:
            document = documents_by_path.get(path)
            if document is None:
                continue
            context_hit = _context_hit(
                document,
                snapshot,
                query_terms,
                symbols_by_path,
                context_lines,
                combined_score,
                f"Graph-expanded evidence: {graph_reason}; no direct lexical match in this file.",
            )
            if context_hit is not None:
                combined.append(context_hit)

    return sorted(combined, key=lambda hit: (-hit.score, hit.path))[:top_k]
