"""Language-aware analysis for Python source using the standard-library AST."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

from repoatlas.models import AnalysisReport, Symbol
from repoatlas.scanner import scan_files


def get_revision(root: Path) -> str | None:
    """Return the current Git commit if available; never execute repository hooks."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=2,
            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
                 "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": os.devnull},
        )
        value = result.stdout.strip()
        return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None
    except (OSError, subprocess.SubprocessError):
        return None


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.scope: list[str] = []
        self.symbols: list[Symbol] = []
        self.imports: list[str] = []

    def _visit_definition(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str):
        self.scope.append(node.name)
        self.symbols.append(Symbol(
            name=node.name,
            qualified_name=".".join(self.scope),
            kind=kind,
            path=self.path,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node),
        ))
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_definition(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_definition(node, "async_function")

    def visit_ClassDef(self, node: ast.ClassDef):
        self._visit_definition(node, "class")

    def visit_Import(self, node: ast.Import):
        self.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        prefix = "." * node.level + (node.module or "")
        self.imports.append(prefix)


def analyze_repository(root: str | Path, **scan_limits) -> AnalysisReport:
    """Scan a repository and extract Python symbols/imports without importing code."""
    base = Path(root).expanduser().resolve(strict=True)
    files, excluded, warnings = scan_files(base, **scan_limits)
    report = AnalysisReport(root=str(base), revision=get_revision(base), excluded=excluded, warnings=warnings)
    report.files = files

    for item in files:
        if item.language != "Python":
            continue
        path = base / item.path
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=item.path)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            report.warnings.append(f"Could not parse {item.path}: {type(exc).__name__}")
            continue
        visitor = _PythonVisitor(item.path)
        visitor.visit(tree)
        report.symbols.extend(visitor.symbols)
        report.imports[item.path] = sorted(set(visitor.imports))
    return report
