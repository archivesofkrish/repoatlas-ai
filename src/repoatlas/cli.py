"""Command-line interface for RepoAtlas AI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from repoatlas import __version__
from repoatlas.analyzer import analyze_repository
from repoatlas.graph import build_graph, impact_analysis
from repoatlas.qa import answer_question
from repoatlas.search import search_repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repoatlas", description="Evidence-grounded repository intelligence"
    )
    parser.add_argument("--version", action="version", version=f"RepoAtlas AI {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Summarise files, Python symbols, and imports")
    scan.add_argument("path", type=Path)
    scan.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    search = sub.add_parser("search", help="Search source files with line-addressable evidence")
    search.add_argument("path", type=Path)
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=8)
    graph = sub.add_parser("graph", help="Build a dependency and call-reference graph")
    graph.add_argument("path", type=Path)
    impact = sub.add_parser("impact", help="Find files affected by changing a target file")
    impact.add_argument("path", type=Path)
    impact.add_argument("target")
    impact.add_argument("--max-depth", type=int, default=5)
    ask = sub.add_parser("ask", help="Create an evidence pack for a question")
    ask.add_argument("path", type=Path)
    ask.add_argument("question")
    ask.add_argument("--top-k", type=int, default=6)
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan":
            result = analyze_repository(args.path).to_dict()
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"RepoAtlas scan — {result['root']}")
                print(f"Revision: {result['revision'] or 'not a Git checkout'}")
                print(
                    f"Files: {result['stats']['files']} | "
                    f"Python symbols: {result['stats']['symbols']}"
                )
                for item in result["files"]:
                    print(f"  {item['path']} ({item['language']}, {item['line_count']} lines)")
                for warning in result["warnings"]:
                    print(f"WARNING: {warning}", file=sys.stderr)
            return 0
        if args.command == "search":
            hits = search_repository(args.path, args.query, top_k=args.top_k)
            for hit in hits:
                print(f"{hit.path}:{hit.start_line}-{hit.end_line}  score={hit.score}")
                print(hit.excerpt)
                print()
            if not hits:
                print("No matching evidence found.")
            return 0
        if args.command == "graph":
            result = build_graph(analyze_repository(args.path))
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "impact":
            graph_data = build_graph(analyze_repository(args.path))
            result = impact_analysis(graph_data, args.target, max_depth=args.max_depth)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "ask":
            print(json.dumps(answer_question(args.path, args.question, top_k=args.top_k), indent=2))
            return 0
    except (OSError, ValueError) as exc:
        print(f"repoatlas: error: {exc}", file=sys.stderr)
        return 2
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
