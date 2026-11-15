from repoatlas.parsing import EXTENSION_GRAMMARS, parse_tree_sitter_file


def test_supported_extension_mapping():
    assert EXTENSION_GRAMMARS[".js"] == "javascript"
    assert EXTENSION_GRAMMARS[".go"] == "go"
    assert EXTENSION_GRAMMARS[".rs"] == "rust"


def test_javascript_symbols_imports_and_calls_when_grammar_cached():
    result = parse_tree_sitter_file(
        "src/app.js",
        "import { run } from './worker.js';\nclass App { start() { run(); } }\n",
    )
    if result["warning"] and "not installed" in result["warning"]:
        return
    assert any(symbol.name == "App" for symbol in result["symbols"])
    assert any(symbol.name == "start" for symbol in result["symbols"])
    assert any(item["target"] == "./worker.js" for item in result["imports"])
    assert any(item["target"] == "run" for item in result["calls"])


def test_go_symbol_and_import_extraction_when_grammar_cached():
    result = parse_tree_sitter_file(
        "main.go",
        'package main\nimport "fmt"\nfunc main() { fmt.Println("hi") }\n',
    )
    if result["warning"] and "not installed" in result["warning"]:
        return
    assert any(symbol.name == "main" for symbol in result["symbols"])
    assert any("fmt" in item["target"] for item in result["imports"])
