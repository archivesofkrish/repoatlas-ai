"""Optional Tree-sitter parsing for multi-language repository structure.

This module never downloads grammars during a repository scan. Operators install/cache the
grammars they need explicitly; missing grammars produce a warning and never trigger network I/O.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from repoatlas.models import Symbol

EXTENSION_GRAMMARS = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".rb": "ruby",
    ".cs": "c_sharp",
}

DEFINITIONS = {
    "function_declaration": "function",
    "function_definition": "function",
    "function_item": "function",
    "method_declaration": "method",
    "method_definition": "method",
    "method": "method",
    "constructor_declaration": "constructor",
    "class_declaration": "class",
    "class_definition": "class",
    "class_specifier": "class",
    "struct_item": "struct",
    "struct_declaration": "struct",
    "interface_declaration": "interface",
    "trait_item": "trait",
    "enum_item": "enum",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "impl_item": "implementation",
    "mod_item": "module",
    "type_declaration": "type",
}
NAME_NODE_TYPES = {
    "identifier", "type_identifier", "field_identifier", "property_identifier",
    "constant", "namespace_identifier",
}
IMPORT_NODE_TYPES = {
    "import_statement", "import_declaration", "use_declaration",
    "preproc_include", "include_statement",
}
CALL_NODE_TYPES = {"call_expression", "call", "method_invocation", "macro_invocation"}


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _name_for(node: Any, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _text(name_node, source).strip()
    for child in node.named_children:
        if child.type in NAME_NODE_TYPES:
            return _text(child, source).strip()
    return None


def _callee_for(node: Any, source: bytes) -> str | None:
    callee = node.child_by_field_name("function") or node.child_by_field_name("name")
    if callee is None and node.named_children:
        callee = node.named_children[0]
    if callee is None:
        return None
    text = _text(callee, source).strip()
    # Normalise member calls (client.users.get -> get) but retain qualified fallback.
    parts = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", text)
    return parts[-1] if parts else None


def _import_target(node: Any, source: bytes) -> str:
    raw = _text(node, source).strip()
    if node.type == "preproc_include":
        match = re.search(r"[<\"]([^>\"]+)[>\"]", raw)
        return match.group(1) if match else raw
    quoted = re.search(r"""['"]([^'"]+)['"]""", raw)
    if quoted:
        return quoted.group(1)
    return re.sub(r"^\s*(?:import|use)\s+|;\s*$", "", raw).strip()


def parse_tree_sitter_file(path: str, source: str) -> dict[str, Any]:
    """Extract generic syntax symbols/imports/call references for a cached grammar."""
    suffix = Path(path).suffix.lower()
    grammar = EXTENSION_GRAMMARS.get(suffix)
    if not grammar:
        return {"symbols": [], "imports": [], "calls": [], "warning": None}

    try:
        from tree_sitter_language_pack import get_parser, has_parser
    except ImportError:
        return {
            "symbols": [], "imports": [], "calls": [],
            "warning": "Install the 'parsing' extra to enable Tree-sitter analysis.",
        }
    if not has_parser(grammar):
        return {
            "symbols": [], "imports": [], "calls": [],
            "warning": f"Tree-sitter grammar '{grammar}' is not installed or cached; file indexed as text.",
        }

    source_bytes = source.encode("utf-8")
    parser = get_parser(grammar)
    if hasattr(parser, "set_max_source_bytes"):
        parser.set_max_source_bytes(1_000_000)
    if hasattr(parser, "set_parse_timeout_ms"):
        parser.set_parse_timeout_ms(250)
    tree = parser.parse(source_bytes)
    root = tree.root_node
    symbols: list[Symbol] = []
    imports: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    warnings = []
    if root.has_error:
        warnings.append(f"Tree-sitter recovered from syntax errors in {path}.")

    def visit(node: Any, scope: tuple[str, ...]) -> None:
        current_scope = scope
        kind = DEFINITIONS.get(node.type)
        if kind:
            name = _name_for(node, source_bytes)
            if name:
                qualified = ".".join((*scope, name))
                symbols.append(Symbol(
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    path=path,
                    start_line=node.start_point.row + 1,
                    end_line=node.end_point.row + 1,
                    docstring=None,
                ))
                current_scope = (*scope, name)

        if node.type in IMPORT_NODE_TYPES:
            imports.append({
                "target": _import_target(node, source_bytes),
                "line": node.start_point.row + 1,
            })
        elif node.type in CALL_NODE_TYPES:
            callee = _callee_for(node, source_bytes)
            if callee:
                calls.append({
                    "source": ".".join(scope) or path,
                    "target": callee,
                    "line": node.start_point.row + 1,
                })

        for child in node.named_children:
            visit(child, current_scope)

    visit(root, ())
    return {
        "symbols": symbols,
        "imports": imports,
        "calls": calls,
        "warning": " ".join(warnings) if warnings else None,
    }


def supported_grammar_names() -> list[str]:
    """Return grammar names recognised by the adapter."""
    return sorted(set(EXTENSION_GRAMMARS.values()))
