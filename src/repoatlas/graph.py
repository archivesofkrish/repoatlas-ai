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


_MODULE_SUFFIXES = (
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".go", ".rs", ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh",
    ".rb", ".cs",
)
_INDEX_FILES = (
    "index.py", "index.js", "index.jsx", "index.mjs", "index.cjs",
    "index.ts", "index.tsx", "__init__.py",
)
_SOURCE_ROOTS = ("src", "lib", "app", "include", "packages")


def _module_candidates(base: str) -> list[str]:
    return [
        base,
        *(base + suffix for suffix in _MODULE_SUFFIXES),
        *(posixpath.join(base, name) for name in _INDEX_FILES),
    ]


def _resolve_module(module: str, files: set[str], source_path: str) -> str | None:
    """Resolve only structurally plausible module paths; ambiguity stays unresolved."""
    cleaned = module.strip().strip("'").strip('"').replace("\\", "/")
    if not cleaned or cleaned.startswith(("http://", "https://")):
        return None

    if cleaned.startswith(("./", "../")):
        bases = [posixpath.normpath(posixpath.join(posixpath.dirname(source_path), cleaned))]
    elif cleaned.startswith("."):
        # Python relative imports count leading dots as package traversal levels.
        level = len(cleaned) - len(cleaned.lstrip("."))
        remainder = cleaned[level:]
        package_dir = posixpath.dirname(source_path)
        for _ in range(max(level - 1, 0)):
            package_dir = posixpath.dirname(package_dir)
        bases = [posixpath.normpath(posixpath.join(package_dir, remainder.replace(".", "/")))]
    else:
        base = cleaned.replace(".", "/").lstrip("/")
        bases = [base, *(posixpath.join(root, base) for root in _SOURCE_ROOTS)]

    matches = {
        candidate
        for base in bases
        for candidate in _module_candidates(base)
        if candidate in files
    }
    return next(iter(matches)) if len(matches) == 1 else None


def build_graph(report: AnalysisReport) -> dict:
    """Build file dependency edges and best-effort symbol call-reference edges."""
    file_paths = {item.path for item in report.files}
    symbols_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    nodes = set(file_paths)
    for symbol in report.symbols:
        node_id = f"{symbol.path}::{symbol.qualified_name}"
        symbols_by_name[symbol.name].append((symbol.path, node_id))
        nodes.add(node_id)

    edges: list[GraphEdge] = []
    for path, imports in report.imports.items():
        for item in imports:
            if isinstance(item, dict):
                target = str(item.get("target", ""))
                line = int(item.get("line", 1))
                imported_names = [
                    str(name) for name in item.get("names", [])
                    if isinstance(name, str) and name != "*"
                ]
            else:
                target, line, imported_names = str(item), 1, []

            resolved = _resolve_module(target, file_paths, path)
            edges.append(GraphEdge(
                source=path,
                target=resolved or target,
                kind="imports",
                path=path,
                line=line,
                resolved=resolved is not None,
            ))

            # A from-import may reference both a package initializer and a sibling module.
            for imported_name in imported_names:
                submodule = (
                    f"{target}{imported_name}"
                    if target.endswith(".")
                    else f"{target}.{imported_name}"
                )
                submodule_resolved = _resolve_module(submodule, file_paths, path)
                if submodule_resolved and submodule_resolved != resolved:
                    edges.append(GraphEdge(
                        source=path,
                        target=submodule_resolved,
                        kind="imports",
                        path=path,
                        line=line,
                        resolved=True,
                    ))

    for path, calls in report.calls.items():
        for call in calls:
            target = str(call.get("target", ""))
            source_name = str(call.get("source") or path)
            source = f"{path}::{source_name}" if source_name != path else path
            # Name-only matching across a repository can invent cross-file edges.
            # Resolve a call only to a unique declaration in its own source file.
            candidates = [
                node_id for candidate_path, node_id in symbols_by_name.get(target, [])
                if candidate_path == path
            ]
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
            "Dynamic imports, runtime dependency injection, reflection, "
            "and generated code are not modelled.",
        ],
    }
