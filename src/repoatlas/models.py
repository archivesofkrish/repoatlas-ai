"""Typed domain models used by the scanner, indexer, and API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    """A safe, text-readable file in a repository snapshot."""
    path: str
    language: str
    size_bytes: int
    line_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Symbol:
    """A declaration extracted by a language-specific static parser."""
    name: str
    qualified_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    docstring: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A line-addressable search result."""
    path: str
    start_line: int
    end_line: int
    score: float
    excerpt: str
    reason: str


@dataclass(slots=True)
class AnalysisReport:
    """Serializable summary of a single repository scan."""
    root: str
    revision: str | None
    files: list[RepositoryFile] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    imports: dict[str, list[object]] = field(default_factory=dict)
    import_details: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    calls: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "revision": self.revision,
            "files": [asdict(item) for item in self.files],
            "symbols": [asdict(item) for item in self.symbols],
            "imports": self.imports,
            "import_details": self.import_details,
            "calls": self.calls,
            "warnings": self.warnings,
            "excluded": self.excluded,
            "stats": {
                "files": len(self.files),
                "symbols": len(self.symbols),
                "warnings": len(self.warnings),
                "total_bytes": sum(item.size_bytes for item in self.files),
            },
        }


def normalized_relative_path(root: Path, path: Path) -> str:
    """Return a stable POSIX path relative to root."""
    return path.relative_to(root).as_posix()
