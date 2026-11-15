"""Revision-aware repository analysis using Python AST and optional Tree-sitter grammars."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

from repoatlas.models import AnalysisReport, Symbol
from repoatlas.parsing import EXTENSION_GRAMMARS, parse_tree_sitter_file
from repoatlas.scanner import scan_files


def get_revision(root: Path) -> str | None:
    """Return the current Git commit if available; never execute repository hooks."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=2,
            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                 "GIT_CONFIG_GLOBAL": os.devnull},
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
        self.import_details: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []

    def _visit_definition(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str
    ):
        # These expressions execute in the enclosing scope, not in the definition.
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name):
                self.calls.append({
                    "source": ".".join(self.scope) or self.path,
                    "target": decorator.id,
                    "line": decorator.lineno,
                })
            elif isinstance(decorator, ast.Attribute):
                self.calls.append({
                    "source": ".".join(self.scope) or self.path,
                    "target": decorator.attr,
                    "line": decorator.lineno,
                })
                self.visit(decorator)
            else:
                self.visit(decorator)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.visit(node.args)
            if node.returns is not None:
                self.visit(node.returns)
        else:
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)

        self.scope.append(node.name)
        self.symbols.append(Symbol(
            name=node.name, qualified_name=".".join(self.scope), kind=kind, path=self.path,
            start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
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

    def visit_Call(self, node: ast.Call):
        function = node.func
        if isinstance(function, ast.Name):
            target = function.id
        elif isinstance(function, ast.Attribute):
            target = function.attr
        else:
            target = None
        if target:
            self.calls.append({
                "source": ".".join(self.scope) or self.path,
                "target": target,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)
            self.import_details.append({
                "target": alias.name,
                "line": node.lineno,
                "names": [],
            })

    def visit_ImportFrom(self, node: ast.ImportFrom):
        target = "." * node.level + (node.module or "")
        self.imports.append(target)
        self.import_details.append({
            "target": target,
            "line": node.lineno,
            "names": [alias.name for alias in node.names],
        })


def analyze_repository(root: str | Path, **scan_limits) -> AnalysisReport:
    """Scan a repository and extract Python symbols/imports without importing code."""
    base = Path(root).expanduser().resolve(strict=True)
    files, excluded, warnings = scan_files(base, **scan_limits)
    report = AnalysisReport(
        root=str(base), revision=get_revision(base), excluded=excluded, warnings=warnings
    )
    report.files = files

    for item in files:
        try:
            source = (base / item.path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report.warnings.append(f"Could not read {item.path}: {type(exc).__name__}")
            continue
        if item.language == "Python":
            try:
                tree = ast.parse(source, filename=item.path)
            except (SyntaxError, RecursionError) as exc:
                report.warnings.append(f"Could not parse {item.path}: {type(exc).__name__}")
                continue
            visitor = _PythonVisitor(item.path)
            try:
                visitor.visit(tree)
            except RecursionError:
                report.warnings.append(
                    f"Could not safely traverse {item.path}: "
                    "AST nesting exceeded the recursion limit."
                )
                continue
            report.symbols.extend(visitor.symbols)
            report.imports[item.path] = sorted(set(visitor.imports))
            report.import_details[item.path] = visitor.import_details
            report.calls[item.path] = visitor.calls
        elif Path(item.path).suffix.lower() in EXTENSION_GRAMMARS:
            parsed = parse_tree_sitter_file(item.path, source)
            report.symbols.extend(parsed["symbols"])
            report.imports[item.path] = parsed["imports"]
            report.calls[item.path] = parsed["calls"]
            if parsed["warning"]:
                report.warnings.append(parsed["warning"])
    return report
