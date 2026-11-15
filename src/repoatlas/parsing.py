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
    ".cs": "csharp",
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
    "type_alias_declaration": "type",
    "abstract_class_declaration": "class",
}
NAME_NODE_TYPES = {
    "identifier", "type_identifier", "field_identifier", "property_identifier",
    "constant", "namespace_identifier",
}
IMPORT_NODE_TYPES = {
    "import_statement", "import_declaration", "use_declaration",
    "preproc_include", "include_statement", "using_directive",
}
CALL_NODE_TYPES = {"call_expression", "call", "method_invocation", "macro_invocation"}


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _name_for(node: Any, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _text(name_node, source).strip()
    def find_name(candidate: Any) -> str | None:
        if candidate.type in NAME_NODE_TYPES:
            return _text(candidate, source).strip()
        for child in candidate.named_children:
            found = find_name(child)
            if found:
                return found
        return None

    for child in node.named_children:
        found = find_name(child)
        if found:
            return found
    return None


def _callee_for(node: Any, source: bytes) -> str | None:
    callee = node.child_by_field_name("function")
    if callee is None:
        callee = node.child_by_field_name("name")
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
        quoted = re.search(r'"([^"]+)"', raw)
        if quoted:
            target = quoted.group(1)
            return target if target.startswith(("./", "../")) else f"./{target}"
        match = re.search(r"<([^>]+)>", raw)
        return match.group(1) if match else raw
    if node.type == "import_spec":
        path_node = node.child_by_field_name("path")
        raw = _text(path_node, source).strip() if path_node is not None else raw
        return raw.strip("'\"")
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
        from tree_sitter import Parser
        from tree_sitter_language_pack import downloaded_languages, get_language
    except ImportError:
        return {
            "symbols": [], "imports": [], "calls": [],
            "warning": "Install the 'parsing' extra to enable Tree-sitter analysis.",
        }
    # Check the local cache first. get_language can fetch missing grammars, so it
    # must only be called when the exact grammar is already present on disk.
    if grammar not in set(downloaded_languages()):
        return {
            "symbols": [], "imports": [], "calls": [],
            "warning": (
                f"Tree-sitter grammar '{grammar}' is not installed or cached; "
                "file indexed as text."
            ),
        }

    source_bytes = source.encode("utf-8")
    if len(source_bytes) > 1_000_000:
        return {
            "symbols": [], "imports": [], "calls": [],
            "warning": f"Tree-sitter source limit exceeded for {path}.",
        }
    try:
        # get_language() returns a standard tree_sitter.Language. Constructing
        # tree_sitter.Parser directly ensures nodes expose the standard Python API
        # (.type, .named_children, .start_point) used by this adapter.
        parser = Parser(get_language(grammar))
        if hasattr(parser, "timeout_micros"):
            parser.timeout_micros = 250_000
        tree = parser.parse(source_bytes)
    except Exception as exc:
        return {
            "symbols": [], "imports": [], "calls": [],
            "warning": f"Tree-sitter could not parse {path}: {type(exc).__name__}: {exc}",
        }
    root = tree.root_node
    symbols: list[Symbol] = []
    imports: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    warnings = []
    if root.has_error:
        warnings.append(f"Tree-sitter recovered from syntax errors in {path}.")

    def descendants_of_type(node: Any, node_type: str) -> list[Any]:
        found: list[Any] = []
        for child in node.named_children:
            if child.type == node_type:
                found.append(child)
            else:
                found.extend(descendants_of_type(child, node_type))
        return found

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
        elif node.type == "variable_declarator":
            # JavaScript/TypeScript commonly declare functions as const handlers = () => {}.
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if (
                name_node is not None
                and value_node is not None
                and value_node.type in {"arrow_function", "function_expression"}
            ):
                name = _text(name_node, source_bytes).strip()
                if name:
                    qualified = ".".join((*scope, name))
                    symbols.append(Symbol(
                        name=name,
                        qualified_name=qualified,
                        kind="function",
                        path=path,
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        docstring=None,
                    ))
                    current_scope = (*scope, name)

        if node.type in IMPORT_NODE_TYPES:
            if node.type == "import_declaration":
                specs = descendants_of_type(node, "import_spec")
                if specs:
                    for spec in specs:
                        imports.append({
                            "target": _import_target(spec, source_bytes),
                            "line": spec.start_point.row + 1,
                        })
                else:
                    imports.append({
                        "target": _import_target(node, source_bytes),
                        "line": node.start_point.row + 1,
                    })
            else:
                imports.append({
                    "target": _import_target(node, source_bytes),
                    "line": node.start_point.row + 1,
                })
        elif node.type == "call_expression":
            function_node = node.child_by_field_name("function")
            arguments_node = node.child_by_field_name("arguments")
            if (
                function_node is not None
                and _text(function_node, source_bytes).strip() == "require"
                and arguments_node is not None
                and arguments_node.named_children
            ):
                argument = _text(arguments_node.named_children[0], source_bytes).strip()
                required = re.match(r"""['"]([^'"]+)['"]""", argument)
                if required:
                    imports.append({
                        "target": required.group(1),
                        "line": node.start_point.row + 1,
                    })
            callee = _callee_for(node, source_bytes)
            if callee:
                calls.append({
                    "source": ".".join(scope) or path,
                    "target": callee,
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
