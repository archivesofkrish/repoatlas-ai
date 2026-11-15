"""Hybrid retrieval combining lexical matches with static dependency context."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from repoatlas.analyzer import analyze_repository
from repoatlas.graph import build_graph
from repoatlas.models import SearchHit
from repoatlas.search import _tokens_with_identifiers, search_repository

_GRAPH_DECAY = 0.72
_MAX_GRAPH_SEEDS = 20
_MAX_GRAPH_CANDIDATES = 500


def _context_hit(
    base: Path,
    path: str,
    query_terms: set[str],
    symbols_by_path: dict[str, list],
    context_lines: int,
    score: float,
    reason: str,
) -> SearchHit | None:
    """Create a clearly-labelled structural result anchored to a real source line."""
    candidate = base / path
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base)
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not lines:
        return None

    symbols = symbols_by_path.get(path, [])
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
        path=path,
        start_line=index + 1,
        end_line=index + 1,
        score=round(score, 6),
        excerpt=excerpt,
        reason=reason,
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
    """Rank direct lexical evidence and files connected by resolved import edges.

    Lexical matches remain the retrieval seeds. Graph expansion adds bounded, one-to-three
    hop dependency context and labels it explicitly; it never pretends that a related file
    contains a direct query match. The final score is a weighted combination of normalised
    lexical relevance and decayed graph proximity.
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

    base = Path(root).expanduser().resolve(strict=True)
    lexical_hits = search_repository(
        base,
        query,
        top_k=100,
        context_lines=context_lines,
        **scan_limits,
    )
    if not lexical_hits:
        return []

    report = analyze_repository(base, **scan_limits)
    graph = build_graph(report)
    file_paths = {item.path for item in report.files}
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
        queue = deque([(seed.path, 0, seed_strength)])
        best_for_seed = {seed.path: seed_strength}
        while queue:
            current, depth, strength = queue.popleft()
            if depth >= graph_depth:
                continue
            for neighbour, relation, via in adjacency.get(current, []):
                next_depth = depth + 1
                propagated = seed_strength * (_GRAPH_DECAY ** next_depth)
                if propagated <= best_for_seed.get(neighbour, 0.0):
                    continue
                best_for_seed[neighbour] = propagated
                detail = (
                    f"related to lexical match {seed.path} via {relation} "
                    f"(distance {next_depth}; import evidence {via})"
                )
                previous = graph_signals.get(neighbour)
                if previous is None or propagated > previous[0]:
                    graph_signals[neighbour] = (propagated, detail)
                queue.append((neighbour, next_depth, propagated))
                if len(graph_signals) >= _MAX_GRAPH_CANDIDATES:
                    break
            if len(graph_signals) >= _MAX_GRAPH_CANDIDATES:
                break
        if len(graph_signals) >= _MAX_GRAPH_CANDIDATES:
            break

    symbols_by_path: dict[str, list] = defaultdict(list)
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
            ))
        elif graph_reason:
            context_hit = _context_hit(
                base,
                path,
                query_terms,
                symbols_by_path,
                context_lines,
                combined_score,
                f"Graph-expanded evidence: {graph_reason}; no direct lexical match in this file.",
            )
            if context_hit is not None:
                combined.append(context_hit)

    return sorted(combined, key=lambda hit: (-hit.score, hit.path))[:top_k]
