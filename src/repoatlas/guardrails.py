"""Declarative architecture-policy evaluation and offline HTML reporting."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

MAX_POLICY_BYTES = 65_536
_POLICY_KEYS = {
    "schema_version",
    "name",
    "description",
    "allowed_package_dependencies",
    "forbidden_package_dependencies",
    "max_cross_package_imports",
    "fail_on_cycles",
}


def load_architecture_policy(path: str | Path) -> dict[str, Any]:
    """Load a bounded JSON policy file without executing repository content."""
    policy_path = Path(path).expanduser()
    try:
        size = policy_path.stat().st_size
    except OSError:
        raise
    if size > MAX_POLICY_BYTES:
        raise ValueError(f"architecture policy exceeds the {MAX_POLICY_BYTES}-byte limit")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"architecture policy is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(policy, dict):
        raise ValueError("architecture policy must be a JSON object")
    return policy


def _package_for(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


def _policy_name(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field} must be a non-empty string of at most 200 characters")
    return value


def _validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(policy) - _POLICY_KEYS)
    if unknown:
        raise ValueError(f"architecture policy contains unknown keys: {', '.join(unknown)}")
    if type(policy.get("schema_version")) is not int or policy["schema_version"] != 1:
        raise ValueError("architecture policy schema_version must be 1")

    name = policy.get("name", "Architecture policy")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("architecture policy name must be a non-empty string of at most 120 characters")
    description = policy.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError("architecture policy description must be a string of at most 500 characters")

    allowed = policy.get("allowed_package_dependencies", {})
    if not isinstance(allowed, dict):
        raise ValueError("allowed_package_dependencies must be an object")
    clean_allowed: dict[str, list[str]] = {}
    for source, targets in allowed.items():
        source_name = _policy_name(source, "allowed package source")
        if not isinstance(targets, list):
            raise ValueError(f"allowed dependencies for {source_name!r} must be an array")
        target_names = [_policy_name(item, "allowed package target") for item in targets]
        if len(target_names) != len(set(target_names)):
            raise ValueError(f"allowed dependencies for {source_name!r} contain duplicates")
        clean_allowed[source_name] = sorted(target_names)

    forbidden = policy.get("forbidden_package_dependencies", [])
    if not isinstance(forbidden, list):
        raise ValueError("forbidden_package_dependencies must be an array")
    clean_forbidden: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in forbidden:
        if not isinstance(item, dict) or set(item) - {"source", "target", "reason"}:
            raise ValueError("each forbidden dependency must contain source, target and optional reason")
        source = _policy_name(item.get("source"), "forbidden dependency source")
        target = _policy_name(item.get("target"), "forbidden dependency target")
        reason = item.get("reason", "This package dependency is explicitly forbidden.")
        if not isinstance(reason, str) or len(reason) > 500:
            raise ValueError("forbidden dependency reason must be a string of at most 500 characters")
        pair = (source, target)
        if pair in seen_pairs:
            raise ValueError(f"duplicate forbidden dependency: {source!r} -> {target!r}")
        seen_pairs.add(pair)
        clean_forbidden.append({"source": source, "target": target, "reason": reason})

    limits = policy.get("max_cross_package_imports", {})
    if not isinstance(limits, dict):
        raise ValueError("max_cross_package_imports must be an object")
    clean_limits: dict[str, int] = {}
    for package, maximum in limits.items():
        package_name = _policy_name(package, "package limit key")
        if type(maximum) is not int or maximum < 0:
            raise ValueError(f"max_cross_package_imports[{package_name!r}] must be a non-negative integer")
        clean_limits[package_name] = maximum

    fail_on_cycles = policy.get("fail_on_cycles", False)
    if type(fail_on_cycles) is not bool:
        raise ValueError("fail_on_cycles must be a boolean")

    if not clean_allowed and not clean_forbidden and not clean_limits and not fail_on_cycles:
        raise ValueError("architecture policy must define at least one active rule")

    return {
        "schema_version": 1,
        "name": name.strip(),
        "description": description,
        "allowed_package_dependencies": clean_allowed,
        "forbidden_package_dependencies": clean_forbidden,
        "max_cross_package_imports": clean_limits,
        "fail_on_cycles": fail_on_cycles,
    }


def evaluate_architecture_policy(
    architecture_report: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate package import relationships and cycle limits against a policy."""
    if not isinstance(architecture_report, dict):
        raise ValueError("architecture_report must be an object")
    if not isinstance(policy, dict):
        raise ValueError("architecture policy must be an object")
    config = _validate_policy(policy)

    package_rows = architecture_report.get("packages", [])
    package_edges = architecture_report.get("package_dependencies", [])
    files = architecture_report.get("files", [])
    if not isinstance(package_rows, list) or not isinstance(package_edges, list) or not isinstance(files, list):
        raise ValueError("architecture report has an invalid package or file structure")

    evidence_by_pair: dict[tuple[str, str], list[dict[str, str]]] = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        source_package = item.get("package") or _package_for(item["path"])
        for target_path in item.get("dependencies", []):
            if not isinstance(target_path, str):
                continue
            target_package = _package_for(target_path)
            if source_package != target_package:
                evidence_by_pair.setdefault((source_package, target_package), []).append({
                    "source_file": item["path"],
                    "target_file": target_path,
                })

    violations: list[dict[str, Any]] = []
    forbidden_map = {
        (item["source"], item["target"]): item["reason"]
        for item in config["forbidden_package_dependencies"]
    }
    allowed_map = config["allowed_package_dependencies"]

    for edge in package_edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        count = edge.get("edge_count")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        reason = forbidden_map.get((source, target))
        if reason is not None:
            violations.append({
                "rule": "forbidden_package_dependency",
                "severity": "critical",
                "message": reason,
                "source": source,
                "target": target,
                "edge_count": int(count) if type(count) is int and count >= 0 else 0,
                "evidence": evidence_by_pair.get((source, target), [])[:5],
            })
        elif source in allowed_map and target not in allowed_map[source]:
            violations.append({
                "rule": "package_dependency_not_allowed",
                "severity": "high",
                "message": f"{source} is not allowed to depend on {target}.",
                "source": source,
                "target": target,
                "edge_count": int(count) if type(count) is int and count >= 0 else 0,
                "evidence": evidence_by_pair.get((source, target), [])[:5],
            })

    package_by_name = {
        item.get("name"): item for item in package_rows
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for package, maximum in config["max_cross_package_imports"].items():
        observed = package_by_name.get(package)
        if observed is None:
            continue
        actual = observed.get("cross_package_imports", 0)
        if type(actual) is not int or actual < 0:
            raise ValueError(f"architecture report has an invalid cross_package_imports value for {package!r}")
        if actual > maximum:
            violations.append({
                "rule": "max_cross_package_imports",
                "severity": "medium",
                "message": f"{package} has {actual} cross-package imports; the policy allows at most {maximum}.",
                "source": package,
                "target": None,
                "observed": actual,
                "maximum": maximum,
                "evidence": [],
            })

    cycles = architecture_report.get("cycles", [])
    total_cycles = architecture_report.get("total_cycles", len(cycles))
    if config["fail_on_cycles"]:
        for component in cycles:
            if not isinstance(component, list):
                continue
            paths = sorted(path for path in component if isinstance(path, str))
            violations.append({
                "rule": "dependency_cycle",
                "severity": "high",
                "message": "A statically resolved dependency cycle is present.",
                "files": paths,
                "evidence": [],
            })

    violations.sort(
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2}.get(item["severity"], 3),
            item["rule"],
            item.get("source") or "",
            item.get("target") or "",
            item.get("files", []),
        )
    )
    rules_checked = (
        len(config["allowed_package_dependencies"])
        + len(config["forbidden_package_dependencies"])
        + len(config["max_cross_package_imports"])
        + int(config["fail_on_cycles"])
    )
    return {
        "repository": str(architecture_report.get("repository") or "Repository"),
        "revision": architecture_report.get("revision"),
        "snapshot_id": architecture_report.get("snapshot_id"),
        "policy_name": config["name"],
        "policy_description": config["description"],
        "schema_version": 1,
        "status": "FAIL" if violations else "PASS",
        "summary": {
            "packages": len(package_by_name),
            "package_dependencies": len(package_edges),
            "rules_checked": rules_checked,
            "violations": len(violations),
            "critical": sum(item["severity"] == "critical" for item in violations),
            "high": sum(item["severity"] == "high" for item in violations),
            "medium": sum(item["severity"] == "medium" for item in violations),
            "cycles_detected": int(total_cycles) if type(total_cycles) is int and total_cycles >= 0 else 0,
            "cycles_evaluated": len(cycles) if config["fail_on_cycles"] else 0,
        },
        "violations": violations,
        "limitations": [
            "Only statically resolved import edges represented in the architecture report are evaluated.",
            "Runtime imports, reflection, dependency injection, generated code and dynamic plugin wiring may be absent.",
            "A PASS means no configured rule was violated by the observed static graph; it is not proof of architectural correctness.",
            "Policies are opt-in and do not alter, block or execute repository code.",
        ],
    }


def render_architecture_guardrails_html(
    result: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Write a self-contained architecture-policy report with escaped repository data."""
    if not isinstance(result, dict) or result.get("status") not in {"PASS", "FAIL"}:
        raise ValueError("result must be a completed architecture policy report")

    summary = result.get("summary", {})
    status = result["status"]
    cards = [
        ("Packages", summary.get("packages", 0)),
        ("Package links", summary.get("package_dependencies", 0)),
        ("Rules checked", summary.get("rules_checked", 0)),
        ("Violations", summary.get("violations", 0)),
    ]
    card_html = "".join(
        f'<article class="metric"><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></article>'
        for label, value in cards
    )
    violations_html = []
    for item in result.get("violations", []):
        severity = html.escape(str(item.get("severity", "medium")).lower())
        rule = html.escape(str(item.get("rule", "policy_violation")))
        message = html.escape(str(item.get("message", "")))
        source = html.escape(str(item.get("source") or ""))
        target = html.escape(str(item.get("target") or ""))
        relationship = f"{source} → {target}" if target else source
        if item.get("files"):
            evidence = "<br>".join(html.escape(str(path)) for path in item["files"])
        else:
            evidence = "<br>".join(
                f'{html.escape(str(row.get("source_file", "")))} → '
                f'{html.escape(str(row.get("target_file", "")))}'
                for row in item.get("evidence", [])
            )
        if not evidence:
            evidence = "No file-level example available in the scanned evidence."
        violations_html.append(
            f'<article class="finding"><div class="finding-top"><span class="severity {severity}">{severity}</span>'
            f'<span class="rule">{rule}</span></div><h2>{message}</h2>'
            f'<p class="relationship">{relationship}</p><div class="evidence">{evidence}</div></article>'
        )
    if not violations_html:
        violations_content = (
            '<div class="empty"><div class="check">✓</div><h2>No configured rules were violated</h2>'
            '<p>The observed static package graph satisfies this policy.</p></div>'
        )
    else:
        violations_content = "".join(violations_html)
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in result.get("limitations", [])
    )
    repository = html.escape(str(result.get("repository", "Repository")))
    revision = html.escape(str(result.get("revision") or "working tree"))
    policy_name = html.escape(str(result.get("policy_name", "Architecture policy")))
    description = html.escape(str(result.get("policy_description", "")))
    status_label = "Policy passed" if status == "PASS" else "Policy violations found"
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Architecture policy report generated by RepoAtlas AI">
<title>RepoAtlas Guardrails · {policy_name}</title>
<style>
:root{{color-scheme:dark;--bg:#0b1020;--panel:#131f35;--line:#2b3c58;--ink:#e9eff9;--muted:#a1b0c5;--cyan:#65d7e6;--red:#ff7887;--amber:#f6c36b;--green:#7be0b2}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at 10% 0,#1c3452 0,#0b1020 46%);color:var(--ink);font:15px/1.55 Inter,system-ui,-apple-system,Segoe UI,sans-serif}}
header{{padding:30px clamp(18px,5vw,64px);border-bottom:1px solid var(--line);background:#0b1020cc;backdrop-filter:blur(16px)}}
.brand{{font-size:12px;letter-spacing:.17em;text-transform:uppercase;color:var(--cyan);font-weight:850}}
h1{{font-size:clamp(30px,4vw,46px);letter-spacing:-.045em;line-height:1.08;margin:13px 0 8px}}
.sub{{color:var(--muted);max-width:780px}}.meta{{margin-top:19px;color:#8fa2bd;font-size:12px}}
main{{max-width:1400px;margin:0 auto;padding:26px clamp(14px,3vw,34px) 54px}}
.status{{display:flex;gap:12px;align-items:center;border:1px solid {('#23654e' if status == 'PASS' else '#713b49')};background:{('#102f2a' if status == 'PASS' else '#351a2a')};padding:16px 18px;border-radius:16px}}
.pill{{padding:6px 10px;border-radius:99px;font-size:11px;font-weight:900;letter-spacing:.12em;background:{('#1a5a48' if status == 'PASS' else '#7b2b43')};color:#fff}}
.status strong{{font-size:18px}}.status small{{display:block;color:#c0ccdc;margin-top:2px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0 28px}}
.metric{{background:linear-gradient(150deg,#182843,#101a2e);border:1px solid var(--line);border-radius:16px;padding:17px}}
.metric span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.11em}}
.metric strong{{display:block;font-size:29px;letter-spacing:-.04em;margin-top:6px}}
.section-title{{font-size:21px;letter-spacing:-.02em;margin:28px 0 12px}}
.finding{{background:linear-gradient(145deg,#16243c,#111b30);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:10px 0}}
.finding-top{{display:flex;gap:9px;align-items:center}}.severity{{font-size:10px;text-transform:uppercase;letter-spacing:.12em;font-weight:900;padding:5px 8px;border-radius:99px}}
.severity.critical{{background:#642c3d;color:#ffc3cc}}.severity.high{{background:#5b3d28;color:#ffd9a1}}.severity.medium{{background:#294d66;color:#aee8f4}}
.rule{{font-size:11px;color:var(--muted);font-family:ui-monospace,monospace}}.finding h2{{font-size:17px;margin:12px 0 4px}}.relationship{{color:var(--cyan);font-weight:750;margin:5px 0 10px}}
.evidence{{font:12px/1.8 ui-monospace,monospace;background:#0b1425;border:1px solid #2b3b55;border-radius:10px;padding:10px 12px;color:#c5d2e4;overflow-wrap:anywhere}}
.empty{{text-align:center;padding:42px 20px;border-radius:17px;border:1px solid #255b4b;background:#102b29}}.check{{margin:auto;width:50px;height:50px;border-radius:50%;display:grid;place-items:center;background:#1c6b55;color:white;font-size:28px}}
.empty h2{{margin:14px 0 3px}}.empty p{{color:#b4c8c4}}
details{{background:#111d31;border:1px solid var(--line);border-radius:14px;padding:15px 18px;margin-top:22px}}summary{{cursor:pointer;font-weight:750}}li{{color:var(--muted);margin:7px 0}}
footer{{text-align:center;color:#8293ad;font-size:12px;margin-top:32px}}
@media(max-width:700px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}header{{padding:22px 18px}}}}
</style></head>
<body><header><div class="brand">RepoAtlas AI · Architecture guardrails</div>
<h1>{policy_name}</h1><div class="sub">{description}</div>
<div class="meta">{repository} &nbsp;·&nbsp; Snapshot {revision}</div></header>
<main><div class="status"><span class="pill">{status}</span><div><strong>{status_label}</strong><small>{html.escape(str(summary.get("violations", 0)))} findings across {html.escape(str(summary.get("rules_checked", 0)))} configured rules</small></div></div>
<section class="metrics">{card_html}</section>
<h2 class="section-title">Policy findings</h2>{violations_content}
<details><summary>Interpretation and limitations</summary><ul>{limitations}</ul></details>
<footer>Generated by RepoAtlas AI · Static analysis only · Repository source was not executed</footer></main></body></html>"""

    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination
