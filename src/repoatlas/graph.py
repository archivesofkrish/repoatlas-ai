"""Dependency and call-reference graph construction and impact analysis."""

from __future__ import annotations

import posixpath
from collections import defaultdict, deque
from dataclasses import asdict, dataclass

from repoatlas.models import AnalysisReport


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    path: str
    line: int
    resolved: bool


def _resolve_module(module: str, files: set[str], source_path: str) -> str | None:
    cleaned = module.strip().strip("'").strip('"').replace("\\", "/")
    if not cleaned or cleaned.startswith(("http://", "https://")):
        return None
    if cleaned.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), cleaned))
    else:
        base = cleaned.replace(".", "/").lstrip("/")
    candidates = [
        base, base + ".py", base + ".js", base + ".jsx", base + ".ts",
        base + ".tsx", base + ".go", base + ".rs", base + ".java",
        base + "/__init__.py", base + "/index.js", base + "/index.ts",
    ]
    for candidate in candidates:
        if candidate in files:
            return candidate
    matches = [
        path for path in files
        if path.rsplit("/", 1)[-1].split(".")[0] == cleaned
    ]
    return sorted(matches)[0] if len(matches) == 1 else None


def build_graph(report: AnalysisReport) -> dict:
    """Build file dependency edges and best-effort symbol call-reference edges."""
    file_paths = {item.path for item in report.files}
    symbols_by_name: dict[str, list[str]] = defaultdict(list)
    nodes = set(file_paths)
    for symbol in report.symbols:
        node_id = f"{symbol.path}::{symbol.qualified_name}"
        symbols_by_name[symbol.name].append(node_id)
        nodes.add(node_id)

    edges: list[GraphEdge] = []
    for path, imports in report.imports.items():
        for item in imports:
            if isinstance(item, dict):
                target = str(item.get("target", ""))
                line = int(item.get("line", 1))
            else:
                target, line = str(item), 1
            resolved = _resolve_module(target, file_paths, path)
            edges.append(GraphEdge(
                source=path,
                target=resolved or target,
                kind="imports",
                path=path,
                line=line,
                resolved=resolved is not None,
            ))

    for path, calls in report.calls.items():
        for call in calls:
            target = str(call.get("target", ""))
            source_name = str(call.get("source") or path)
            source = f"{path}::{source_name}" if source_name != path else path
            candidates = symbols_by_name.get(target, [])
            resolved_target = candidates[0] if len(candidates) == 1 else None
            edges.append(GraphEdge(
                source=source,
                target=resolved_target or target,
                kind="calls",
                path=path,
                line=int(call.get("line", 1)),
                resolved=resolved_target is not None,
            ))

    for edge in edges:
        nodes.add(edge.source)
        nodes.add(edge.target)
    return {
        "nodes": sorted(nodes),
        "edges": [asdict(edge) for edge in edges],
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "resolved_edges": sum(edge.resolved for edge in edges),
            "unresolved_edges": sum(not edge.resolved for edge in edges),
            "imports": sum(edge.kind == "imports" for edge in edges),
            "calls": sum(edge.kind == "calls" for edge in edges),
        },
    }


def impact_analysis(graph: dict, target_path: str, *, max_depth: int = 5) -> dict:
    """Find files that directly or transitively depend on target_path."""
    if not 1 <= max_depth <= 20:
        raise ValueError("max_depth must be between 1 and 20")
    nodes = set(graph.get("nodes", []))
    if target_path not in nodes:
        raise ValueError(f"Target path not found in graph: {target_path}")
    reverse: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        if edge.get("kind") == "imports" and edge.get("resolved"):
            reverse[str(edge["target"])].add(str(edge["source"]))
    queue = deque([(target_path, 0)])
    seen = {target_path}
    affected = []
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for dependent in sorted(reverse.get(current, set())):
            if dependent not in seen:
                seen.add(dependent)
                affected.append({"path": dependent, "distance": depth + 1})
                queue.append((dependent, depth + 1))
    return {
        "target": target_path,
        "affected": affected,
        "stats": {"affected_files": len(affected), "max_depth": max_depth},
        "limitations": [
            "Impact follows statically resolved file import edges only.",
            "Dynamic imports, runtime dependency injection, reflection, and generated code are not modelled.",
        ],
    }
