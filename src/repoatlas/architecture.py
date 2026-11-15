"""Architecture-level repository metrics and a self-contained graph explorer."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _package_for(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


def _strongly_connected_components(
    nodes: list[str],
    adjacency: dict[str, set[str]],
    reverse: dict[str, set[str]],
) -> list[list[str]]:
    """Return deterministic strongly connected components without recursion."""
    visited: set[str] = set()
    order: list[str] = []

    for root in nodes:
        if root in visited:
            continue
        visited.add(root)
        stack: list[tuple[str, Any]] = [(root, iter(sorted(adjacency[root])))]
        while stack:
            node, neighbours = stack[-1]
            neighbour = next(neighbours, None)
            if neighbour is None:
                order.append(node)
                stack.pop()
            elif neighbour not in visited:
                visited.add(neighbour)
                stack.append((neighbour, iter(sorted(adjacency[neighbour]))))

    visited.clear()
    components: list[list[str]] = []
    for root in reversed(order):
        if root in visited:
            continue
        component: list[str] = []
        pending = [root]
        visited.add(root)
        while pending:
            node = pending.pop()
            component.append(node)
            for neighbour in sorted(reverse[node], reverse=True):
                if neighbour not in visited:
                    visited.add(neighbour)
                    pending.append(neighbour)
        if len(component) > 1 or root in adjacency[root]:
            components.append(sorted(component))

    return sorted(components, key=lambda component: (component[0], len(component)))


def build_architecture_report(analysis: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Summarise file dependencies, cycles, package boundaries and structural hotspots.

    Only statically resolved import edges between scanned files contribute to the
    dependency metrics. Unresolved imports remain visible as a separate count.
    """
    file_metadata = {item.path: item for item in analysis.files}
    paths = sorted(file_metadata)
    path_set = set(paths)
    symbols_by_file: dict[str, int] = {path: 0 for path in paths}
    for symbol in analysis.symbols:
        if symbol.path in symbols_by_file:
            symbols_by_file[symbol.path] += 1

    adjacency = {path: set() for path in paths}
    reverse = {path: set() for path in paths}
    unresolved_imports = 0
    for edge in graph.get("edges", []):
        if edge.get("kind") != "imports":
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if not edge.get("resolved") or source not in path_set or target not in path_set:
            unresolved_imports += 1
            continue
        adjacency[source].add(target)
        reverse[target].add(source)

    components = _strongly_connected_components(paths, adjacency, reverse)
    cycle_members = {path for component in components for path in component}
    files = []
    for path in paths:
        metadata = file_metadata[path]
        fan_in = len(reverse[path])
        fan_out = len(adjacency[path])
        files.append({
            "path": path,
            "package": _package_for(path),
            "language": metadata.language,
            "size_bytes": metadata.size_bytes,
            "line_count": metadata.line_count,
            "symbol_count": symbols_by_file[path],
            "fan_in": fan_in,
            "fan_out": fan_out,
            "structural_score": 2 * fan_in + fan_out,
            "in_cycle": path in cycle_members,
            "dependencies": sorted(adjacency[path]),
            "dependants": sorted(reverse[path]),
        })

    package_files: dict[str, list[str]] = {}
    package_symbols: dict[str, int] = {}
    package_edges: dict[tuple[str, str], int] = {}
    for item in files:
        package = item["package"]
        package_files.setdefault(package, []).append(item["path"])
        package_symbols[package] = package_symbols.get(package, 0) + item["symbol_count"]
        for target in item["dependencies"]:
            target_package = _package_for(target)
            if target_package != package:
                pair = (package, target_package)
                package_edges[pair] = package_edges.get(pair, 0) + 1

    package_dependencies = [
        {"source": source, "target": target, "edge_count": count}
        for (source, target), count in sorted(package_edges.items())
    ]
    package_outgoing: dict[str, set[str]] = {package: set() for package in package_files}
    package_incoming: dict[str, set[str]] = {package: set() for package in package_files}
    package_outgoing_edges = {package: 0 for package in package_files}
    package_incoming_edges = {package: 0 for package in package_files}
    for dependency in package_dependencies:
        source = dependency["source"]
        target = dependency["target"]
        count = dependency["edge_count"]
        package_outgoing[source].add(target)
        package_incoming[target].add(source)
        package_outgoing_edges[source] += count
        package_incoming_edges[target] += count
    package_cycle_files = {
        package: sum(
            item["in_cycle"] for item in files if item["package"] == package
        )
        for package in package_files
    }
    packages = [
        {
            "name": package,
            "file_count": len(package_files[package]),
            "symbol_count": package_symbols[package],
            "dependency_count": len(package_outgoing[package]),
            "dependant_count": len(package_incoming[package]),
            "cross_package_imports": package_outgoing_edges[package],
            "cross_package_dependant_imports": package_incoming_edges[package],
            "cycle_file_count": package_cycle_files[package],
            "dependency_packages": sorted(package_outgoing[package]),
            "dependant_packages": sorted(package_incoming[package]),
            "files": package_files[package],
        }
        for package in sorted(package_files)
    ]

    hubs = sorted(
        files,
        key=lambda item: (-item["fan_in"], -item["structural_score"], item["path"]),
    )[:20]
    dependency_heavy = sorted(
        files,
        key=lambda item: (-item["fan_out"], -item["structural_score"], item["path"]),
    )[:20]
    isolated = [item["path"] for item in files if item["fan_in"] == 0 and item["fan_out"] == 0]
    resolved_dependency_count = sum(len(targets) for targets in adjacency.values())

    return {
        "repository": Path(analysis.root).name or "repository",
        "revision": analysis.revision,
        "snapshot_id": analysis.snapshot_id,
        "stats": {
            "files": len(files),
            "symbols": len(analysis.symbols),
            "packages": len(packages),
            "resolved_dependencies": resolved_dependency_count,
            "unresolved_imports": unresolved_imports,
            "dependency_cycles": len(components),
            "files_in_cycles": len(cycle_members),
            "isolated_files": len(isolated),
        },
        "files": files,
        "packages": packages,
        "package_dependencies": package_dependencies,
        "cycles": components[:50],
        "total_cycles": len(components),
        "isolated_files": isolated[:100],
        "hubs": hubs,
        "dependency_heavy_files": dependency_heavy,
        "limitations": [
            "Dependencies include only statically resolved file imports.",
            "Dynamic imports, runtime dependency injection, reflection, and generated code are not modelled.",
            "A dependency cycle is a structural warning, not proof of a runtime defect.",
            "Structural scores prioritise review; they are not maintainability or risk scores.",
            "Files with no resolved import edges may still be runtime entry points or be referenced dynamically.",
        ],
        "warnings": list(analysis.warnings),
    }


def _safe_json(value: Any) -> str:
    """Encode data safely for an inline application/json script element."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_architecture_html(
    report: dict[str, Any],
    output_path: str | Path,
    *,
    max_nodes: int = 180,
) -> Path:
    """Write a standalone, offline-capable interactive architecture explorer."""
    if type(max_nodes) is not int or not 20 <= max_nodes <= 500:
        raise ValueError("max_nodes must be an integer between 20 and 500")

    all_files = list(report.get("files", []))
    selected = sorted(
        all_files,
        key=lambda item: (
            -int(item.get("structural_score", 0)),
            -int(item.get("fan_in", 0)),
            item.get("path", ""),
        ),
    )[:max_nodes]
    selected_paths = {item["path"] for item in selected}
    map_nodes = [
        {key: item[key] for key in (
            "path", "package", "language", "symbol_count", "fan_in",
            "fan_out", "structural_score", "in_cycle",
        )}
        for item in selected
    ]
    map_edges = [
        {"source": item["path"], "target": target}
        for item in selected
        for target in item.get("dependencies", [])
        if target in selected_paths
    ]
    all_packages = list(report.get("packages", []))
    selected_packages = sorted(
        all_packages,
        key=lambda item: (
            -(int(item.get("cross_package_imports", 0))
              + int(item.get("cross_package_dependant_imports", 0))),
            -int(item.get("file_count", 0)),
            str(item.get("name", "")),
        ),
    )[:60]
    selected_package_names = {item["name"] for item in selected_packages}
    package_nodes = [
        {
            key: item.get(key, 0)
            for key in (
                "name", "file_count", "symbol_count", "dependency_count",
                "dependant_count", "cross_package_imports",
                "cross_package_dependant_imports", "cycle_file_count",
            )
        } | {
            "dependency_packages": item.get("dependency_packages", []),
            "dependant_packages": item.get("dependant_packages", []),
            "top_files": [
                file["path"]
                for file in sorted(
                    (candidate for candidate in all_files
                     if candidate["package"] == item["name"]),
                    key=lambda candidate: (
                        -int(candidate.get("structural_score", 0)),
                        candidate["path"],
                    ),
                )[:8]
            ]
        }
        for item in selected_packages
    ]
    package_map_edges = [
        edge for edge in report.get("package_dependencies", [])
        if edge["source"] in selected_package_names
        and edge["target"] in selected_package_names
    ]
    payload = {
        "repository": report.get("repository", "Repository"),
        "revision": report.get("revision"),
        "stats": report.get("stats", {}),
        "files": map_nodes,
        "edges": map_edges,
        "packages": package_nodes,
        "package_edges": package_map_edges,
        "cycles": report.get("cycles", []),
        "omitted_files": max(0, len(all_files) - len(selected)),
        "omitted_packages": max(0, len(all_packages) - len(selected_packages)),
    }
    embedded = _safe_json(payload)
    repo_name = html.escape(str(report.get("repository", "Repository")), quote=True)
    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Offline interactive repository architecture explorer generated by RepoAtlas AI">
<title>RepoAtlas Architecture Explorer</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#111a2e;--panel2:#17233a;--line:#293852;--text:#e7edf7;--muted:#9aa9bf;--cyan:#63d4e8;--amber:#f6bd60;--red:#ff7485;--green:#8bd5a7}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#172642 0,#0b1020 42%);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;padding:20px clamp(16px,3vw,34px);border-bottom:1px solid #30415f;background:#0b1020d9;position:sticky;top:0;z-index:4;backdrop-filter:blur(18px)}
.identity{display:flex;align-items:center;gap:12px}.brand-mark{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#63d4e8,#8b8cf7 70%,#c4a7ff);color:#07101e;font-weight:950;box-shadow:0 8px 26px #63d4e833}.brand{font-size:18px;font-weight:820;letter-spacing:-.025em}.brand span{color:var(--cyan)}.sub{font-size:12px;color:var(--muted);margin-top:2px}.meta{color:var(--muted);font-size:12px;text-align:right;line-height:1.7}
main{display:grid;grid-template-columns:275px minmax(400px,1fr) 290px;gap:16px;padding:18px clamp(10px,2vw,22px);min-height:calc(100vh - 84px)}
.panel{background:linear-gradient(155deg,#14213aee,#0f182bee);border:1px solid #344763;border-radius:18px;min-width:0;overflow:hidden;box-shadow:0 18px 52px #0003}.panel-head{padding:16px 17px;border-bottom:1px solid var(--line);font-weight:750;letter-spacing:-.01em}.panel-body{padding:16px}
label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin:12px 0 6px}
input,select{width:100%;background:#0b1426;border:1px solid #33445f;color:var(--text);border-radius:8px;padding:10px;font:inherit;outline:none}input:focus,select:focus{border-color:var(--cyan)}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{padding:12px;background:linear-gradient(145deg,#111f35,#0b1426);border:1px solid #2a3c58;border-radius:12px;box-shadow:inset 0 1px #ffffff08}.metric strong{display:block;font-size:22px;letter-spacing:-.04em}.metric span{font-size:10px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.list{margin-top:8px;display:grid;gap:5px;max-height:43vh;overflow:auto}.list button{width:100%;text-align:left;color:var(--text);background:#101c30;border:1px solid transparent;border-radius:7px;padding:8px;cursor:pointer;font:inherit;font-size:12px;overflow-wrap:anywhere}.list button:hover,.list button.active{border-color:var(--cyan);background:#16283e}
.canvas-panel{display:flex;flex-direction:column;min-height:650px}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:11px 14px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}.toolbar button{background:#17243a;border:1px solid #344763;color:var(--text);padding:7px 11px;border-radius:9px;cursor:pointer;transition:background .16s,border-color .16s,transform .16s}.toolbar button:hover{border-color:var(--cyan);transform:translateY(-1px)}.toolbar button.active{background:linear-gradient(135deg,#16516a,#30366f);border-color:#6bdbe6;color:#f5fdff;box-shadow:0 6px 18px #3ec4d522}.toolbar .spacer{flex:1}
#graph,#package-graph{width:100%;height:100%;min-height:600px;touch-action:none;background:radial-gradient(circle at 50% 45%,#1b3152 0,#111d32 42%,#0d1729 78%)}#package-graph{display:none}.package-edge{stroke:#7186aa;stroke-width:1.8;opacity:.45}.package-node{cursor:pointer;stroke:#dbeafe55;stroke-width:1.5;filter:drop-shadow(0 7px 15px #0008)}.package-node.selected{stroke:#fff;stroke-width:3}.package-label{fill:#e8f2ff;font-size:15px;font-weight:700;text-anchor:middle;pointer-events:none}.package-sub{fill:#a8bad4;font-size:10px;text-anchor:middle;pointer-events:none}.edge{stroke:#536985;stroke-width:1.4;opacity:.45}.node{cursor:pointer;stroke:#0b1020;stroke-width:2}.node.cycle{stroke:var(--red);stroke-width:3}.node.selected{stroke:#fff;stroke-width:3.5}.node-label{font-size:10px;fill:#cbd7e8;pointer-events:none}.detail-title{font-size:15px;font-weight:750;overflow-wrap:anywhere}.tag{display:inline-block;padding:3px 7px;border-radius:20px;background:#23344e;color:var(--cyan);font-size:11px;margin:3px 3px 3px 0}
.kv{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #24344c}.kv span{color:var(--muted)}.detail-list{font-size:12px;overflow-wrap:anywhere;color:#cad5e5}.empty{color:var(--muted);font-size:12px;padding:8px 0}.warning{border-left:3px solid var(--amber);padding:9px 10px;background:#322b1f55;color:#e7d2a5;border-radius:4px;font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:9px;padding:10px 14px;color:var(--muted);font-size:11px;border-top:1px solid var(--line)}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
@media(max-width:1100px){main{grid-template-columns:230px minmax(300px,1fr)}.detail-panel{grid-column:1/-1}.detail-panel .panel-body{display:grid;grid-template-columns:1fr 1fr;gap:15px}}
@media(max-width:720px){header{padding:14px}main{grid-template-columns:1fr;padding:8px}.canvas-panel{grid-row:1;min-height:550px}#graph{min-height:480px}.detail-panel{grid-column:auto}.detail-panel .panel-body{display:block}.list{max-height:220px}.meta{display:none}}
</style>
</head>
<body>
<header><div class="identity"><div class="brand-mark">RA</div><div><div class="brand">RepoAtlas <span>Architecture Observatory</span></div><div class="sub">Explore the shape of your codebase · Static analysis · No repository code executed</div></div></div><div class="meta">__REPOSITORY__<br>Snapshot · __REVISION__</div></header>
<main>
<aside class="panel">
  <div class="panel-head">Repository overview</div>
  <div class="panel-body">
    <div class="metrics" id="metrics"></div>
    <label for="search">Find a file</label><input id="search" placeholder="Search paths, e.g. auth">
    <label for="language">Language</label><select id="language"><option value="">All languages</option></select>
    <label for="package">Package</label><select id="package"><option value="">All packages</option></select>
    <div class="list" id="file-list"></div>
  </div>
</aside>
<section class="panel canvas-panel">
  <div class="toolbar"><button id="show-modules" class="active" type="button">Module map</button><button id="show-packages" type="button">Package map</button><span id="graph-count">Dependency graph</span><span class="spacer"></span><button id="reset">Reset view</button><button id="fit">Fit</button></div>
  <svg id="graph" viewBox="0 0 1200 760" role="img" aria-label="Interactive resolved import dependency graph">
    <defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#536985"/></marker></defs>
    <g id="world"><g id="edges"></g><g id="nodes"></g></g>
  </svg>
  <svg id="package-graph" viewBox="0 0 1200 760" role="img" aria-label="Interactive package dependency topology">
    <defs><marker id="package-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L7,4 L0,8" fill="#8096bb"/></marker><radialGradient id="package-fill"><stop offset="0" stop-color="#344d79"/><stop offset="1" stop-color="#17243d"/></radialGradient></defs>
    <g id="package-world"><g id="package-edges"></g><g id="package-nodes"></g></g>
  </svg>
  <div class="legend"><span><i class="dot" style="background:#63d4e8"></i>Python</span><span><i class="dot" style="background:#f6bd60"></i>JavaScript / TypeScript</span><span><i class="dot" style="background:#8bd5a7"></i>Other languages</span><span><i class="dot" style="background:#ff7485"></i>Dependency cycle</span><span>Circle size = structural importance</span></div>
</section>
<aside class="panel detail-panel">
  <div class="panel-head">Module inspector</div>
  <div class="panel-body" id="detail"><div class="empty">Select a module in the graph or file list to inspect its dependencies and dependants.</div></div>
</aside>
</main>
<script id="architecture-data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
const data=JSON.parse(document.getElementById("architecture-data").textContent);
const svg=document.getElementById("graph"), world=document.getElementById("world");
const edgeLayer=document.getElementById("edges"), nodeLayer=document.getElementById("nodes");
const byPath=new Map(data.files.map(n=>[n.path,n]));
const coords=new Map(), nodeEls=new Map(), edgeEls=[];
let selected=null, scale=1, tx=0, ty=0, pan=null;
const W=1200,H=760;
const palette=n=>{const l=(n.language||"").toLowerCase();if(l==="python")return "#63d4e8";if(l.includes("javascript")||l.includes("typescript"))return "#f6bd60";return "#8bd5a7";};
const esc=(v)=>String(v??"");
const degree=n=>Number(n.fan_in||0)+Number(n.fan_out||0);
const fmt=n=>Number(n||0).toLocaleString();
function setView(){world.setAttribute("transform","translate("+tx+" "+ty+") scale("+scale+")");}
function showDetails(path){
 selected=path;const n=byPath.get(path);if(!n)return;
 document.getElementById("detail").replaceChildren();
 const box=document.createElement("div");
 const title=document.createElement("div");title.className="detail-title";title.textContent=n.path;box.appendChild(title);
 const tag=document.createElement("span");tag.className="tag";tag.textContent=n.language;box.appendChild(tag);
 const cycle=document.createElement("span");cycle.className="tag";cycle.textContent=n.in_cycle?"Cycle member":"No detected cycle";box.appendChild(cycle);
 for(const [label,value] of [["Package",n.package],["Symbols",fmt(n.symbol_count)],["Fan-in",fmt(n.fan_in)],["Fan-out",fmt(n.fan_out)],["Structural score",fmt(n.structural_score)]]){
   const row=document.createElement("div");row.className="kv";
   const a=document.createElement("span");a.textContent=label;const b=document.createElement("strong");b.textContent=value;
   row.append(a,b);box.appendChild(row);
 }
 for(const [label,items] of [["Depends on",n.dependencies],["Used by",n.dependants]]){
   const h=document.createElement("label");h.textContent=label;box.appendChild(h);
   const ul=document.createElement("div");ul.className="detail-list";
   ul.textContent=items.length?items.join("\n"):"None detected";box.appendChild(ul);
 }
 document.getElementById("detail").appendChild(box);
 for(const [key,el] of nodeEls)el.querySelector("circle").classList.toggle("selected",key===path);
 for(const [key,el] of nodeEls)el.querySelector("circle").classList.toggle("selected",key===path);
 document.querySelectorAll("#file-list button").forEach(b=>b.classList.toggle("active",b.dataset.path===path));
}
function populateFilters(){
 const langs=[...new Set(data.files.map(n=>n.language))].sort();
 const packs=[...new Set(data.files.map(n=>n.package))].sort();
 const language=document.getElementById("language"),pkg=document.getElementById("package");
 langs.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;language.appendChild(o);});
 packs.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;pkg.appendChild(o);});
 const stats=data.stats||{};
 const metrics=[["Files",stats.files],["Symbols",stats.symbols],["Cycles",stats.dependency_cycles],["Packages",stats.packages],["Unresolved",stats.unresolved_imports],["Isolated",stats.isolated_files]];
 metrics.forEach(([label,value])=>{const d=document.createElement("div");d.className="metric";const s=document.createElement("strong");s.textContent=fmt(value);const t=document.createElement("span");t.textContent=label;d.append(s,t);document.getElementById("metrics").appendChild(d);});
 document.getElementById("graph-count").textContent=data.files.length+" modules · "+data.edges.length+" resolved import edges";
 if(data.omitted_files){const w=document.createElement("div");w.className="warning";w.textContent=fmt(data.omitted_files)+" lower-ranked files omitted from the visual map. Full metrics are retained in the architecture report.";document.getElementById("metrics").after(w);}
}
function buildGraph(){
 const nodes=[...data.files];const n=nodes.length;
 nodes.forEach((item,i)=>{const angle=2*Math.PI*i/Math.max(n,1);const radius=190+Math.min(230,degree(item)*8);coords.set(item.path,{x:W/2+Math.cos(angle)*radius,y:H/2+Math.sin(angle)*radius});});
 // Deterministic force layout with bounded iterations.
 for(let step=0;step<125;step++){
   const force=new Map(nodes.map(item=>[item.path,{x:0,y:0}]));
   for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
     const a=coords.get(nodes[i].path),b=coords.get(nodes[j].path),dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(dx*dx+dy*dy,36),d=Math.sqrt(d2);
     const push=Math.min(95,5000/d2),fx=dx/d*push,fy=dy/d*push;
     force.get(nodes[i].path).x+=fx;force.get(nodes[i].path).y+=fy;force.get(nodes[j].path).x-=fx;force.get(nodes[j].path).y-=fy;
   }
   data.edges.forEach(e=>{const a=coords.get(e.source),b=coords.get(e.target);if(!a||!b||e.source===e.target)return;const dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1;const pull=(d-125)*.008;force.get(e.source).x+=dx/d*pull;force.get(e.source).y+=dy/d*pull;force.get(e.target).x-=dx/d*pull;force.get(e.target).y-=dy/d*pull;});
   nodes.forEach(item=>{const p=coords.get(item.path),f=force.get(item.path);f.x+=(W/2-p.x)*.002;f.y+=(H/2-p.y)*.002;p.x=Math.max(35,Math.min(W-35,p.x+Math.max(-8,Math.min(8,f.x))));p.y=Math.max(35,Math.min(H-35,p.y+Math.max(-8,Math.min(8,f.y))));});
 }
 data.edges.forEach(e=>{
   const line=document.createElementNS("http://www.w3.org/2000/svg","line");line.classList.add("edge");line.setAttribute("marker-end","url(#arrow)");line.dataset.source=e.source;line.dataset.target=e.target;edgeLayer.appendChild(line);edgeEls.push(line);
 });
 nodes.forEach(item=>{
   const g=document.createElementNS("http://www.w3.org/2000/svg","g");g.dataset.path=item.path;
   const circle=document.createElementNS("http://www.w3.org/2000/svg","circle");circle.classList.add("node");if(item.in_cycle)circle.classList.add("cycle");
   const r=6+Math.min(13,degree(item)*1.25);circle.setAttribute("r",r);circle.setAttribute("fill",palette(item));circle.addEventListener("click",()=>showDetails(item.path));
   const title=document.createElementNS("http://www.w3.org/2000/svg","title");title.textContent=item.path+" · fan-in "+item.fan_in+" · fan-out "+item.fan_out;circle.appendChild(title);
   const label=document.createElementNS("http://www.w3.org/2000/svg","text");label.classList.add("node-label");label.setAttribute("x",r+4);label.setAttribute("y",4);label.textContent=item.path.split("/").pop().slice(0,22);
   g.append(circle,label);nodeLayer.appendChild(g);nodeEls.set(item.path,g);
 });
 updatePositions();renderList();applyFilters();
}
function updatePositions(){
 data.files.forEach(item=>{const p=coords.get(item.path),g=nodeEls.get(item.path);if(g)g.setAttribute("transform","translate("+p.x+" "+p.y+")");});
 edgeEls.forEach(line=>{const a=coords.get(line.dataset.source),b=coords.get(line.dataset.target);if(a&&b){line.setAttribute("x1",a.x);line.setAttribute("y1",a.y);line.setAttribute("x2",b.x);line.setAttribute("y2",b.y);}});
}
function renderList(){
 const list=document.getElementById("file-list");list.replaceChildren();
 [...data.files].sort((a,b)=>b.structural_score-a.structural_score||a.path.localeCompare(b.path)).forEach(item=>{
   const b=document.createElement("button");b.dataset.path=item.path;b.textContent=(item.in_cycle?"↻ ":"")+item.path+"  ·  "+item.fan_in+"/"+item.fan_out;b.addEventListener("click",()=>{showDetails(item.path);const p=coords.get(item.path);tx=W/2-p.x*scale;ty=H/2-p.y*scale;setView();});list.appendChild(b);
 });
}
function applyFilters(){
 const q=document.getElementById("search").value.toLowerCase(),lang=document.getElementById("language").value,pkg=document.getElementById("package").value;
 const shown=new Set();
 data.files.forEach(item=>{const ok=item.path.toLowerCase().includes(q)&&(!lang||item.language===lang)&&(!pkg||item.package===pkg);if(ok)shown.add(item.path);const g=nodeEls.get(item.path);if(g)g.style.opacity=ok?"1":".08";});
 edgeEls.forEach(line=>{const ok=shown.has(line.dataset.source)&&shown.has(line.dataset.target);line.style.opacity=ok?".48":".025";});
 document.querySelectorAll("#file-list button").forEach(b=>{const item=byPath.get(b.dataset.path);b.style.display=shown.has(item.path)?"block":"none";});
}
document.getElementById("search").addEventListener("input",applyFilters);
document.getElementById("language").addEventListener("change",applyFilters);
document.getElementById("package").addEventListener("change",applyFilters);
document.getElementById("reset").addEventListener("click",()=>{scale=1;tx=0;ty=0;setView();});
document.getElementById("fit").addEventListener("click",()=>{scale=1;tx=0;ty=0;setView();});
svg.addEventListener("pointerdown",event=>{if(event.target===svg||event.target.tagName==="rect"){pan={x:event.clientX-tx,y:event.clientY-ty};svg.setPointerCapture(event.pointerId);}});
svg.addEventListener("pointermove",event=>{if(pan){tx=event.clientX-pan.x;ty=event.clientY-pan.y;setView();}});
svg.addEventListener("pointerup",()=>{pan=null;});
svg.addEventListener("wheel",event=>{event.preventDefault();const factor=event.deltaY<0?1.08:.92;scale=Math.max(.35,Math.min(2.8,scale*factor));setView();},{passive:false});
function buildPackageGraph(){
 const packages=data.packages||[], edges=data.package_edges||[];
 const layer=document.getElementById("package-edges"), nodesLayer=document.getElementById("package-nodes");
 const coords=new Map(), nodeElements=new Map();
 const count=packages.length, radius=Math.min(270,155+count*2.2);
 packages.forEach((pkg,index)=>{
   const angle=(2*Math.PI*index/Math.max(count,1))-(Math.PI/2);
   coords.set(pkg.name,{x:600+Math.cos(angle)*radius,y:380+Math.sin(angle)*radius});
 });
 edges.forEach(edge=>{
   const a=coords.get(edge.source),b=coords.get(edge.target);if(!a||!b)return;
   const line=document.createElementNS("http://www.w3.org/2000/svg","line");
   line.classList.add("package-edge");
   line.setAttribute("x1",a.x);line.setAttribute("y1",a.y);
   line.setAttribute("x2",b.x);line.setAttribute("y2",b.y);
   line.setAttribute("stroke-width",String(1+Math.min(3,Number(edge.edge_count||0)*.25)));
   line.setAttribute("marker-end","url(#package-arrow)");
   const title=document.createElementNS("http://www.w3.org/2000/svg","title");
   title.textContent=edge.source+" imports "+edge.target+" · "+edge.edge_count+" resolved edges";
   line.appendChild(title);layer.appendChild(line);
 });
 packages.forEach(pkg=>{
   const p=coords.get(pkg.name),g=document.createElementNS("http://www.w3.org/2000/svg","g");
   const circle=document.createElementNS("http://www.w3.org/2000/svg","circle");
   circle.classList.add("package-node");
   const r=21+Math.min(21,Math.sqrt(Number(pkg.file_count||0))*3);
   circle.setAttribute("r",r);circle.setAttribute("cx",p.x);circle.setAttribute("cy",p.y);
   circle.setAttribute("fill","url(#package-fill)");
   const title=document.createElementNS("http://www.w3.org/2000/svg","title");
   title.textContent=pkg.name+" · "+pkg.file_count+" files · "+pkg.dependency_count+" package dependencies";
   circle.appendChild(title);circle.addEventListener("click",()=>showPackageDetails(pkg.name));
   const label=document.createElementNS("http://www.w3.org/2000/svg","text");
   label.classList.add("package-label");label.setAttribute("x",p.x);label.setAttribute("y",p.y+r+20);
   label.textContent=pkg.name.length>22?pkg.name.slice(0,20)+"…":pkg.name;
   const sub=document.createElementNS("http://www.w3.org/2000/svg","text");
   sub.classList.add("package-sub");sub.setAttribute("x",p.x);sub.setAttribute("y",p.y+r+36);
   sub.textContent=fmt(pkg.file_count)+" files";
   g.append(circle,label,sub);nodesLayer.appendChild(g);nodeElements.set(pkg.name,circle);
 });
 window.repoatlasSelectPackage=name=>{
   for(const [key,node] of nodeElements)node.classList.toggle("selected",key===name);
 };
 if(data.omitted_packages){
   const note=document.createElement("div");note.className="warning";
   note.textContent=fmt(data.omitted_packages)+" lower-importance packages omitted from this visual map; full metrics remain in the JSON report.";
   document.getElementById("graph-count").after(note);
 }
}
function showPackageDetails(name){
 const pkg=(data.packages||[]).find(item=>item.name===name);if(!pkg)return;
 document.getElementById("detail").replaceChildren();
 const box=document.createElement("div");
 const title=document.createElement("div");title.className="detail-title";title.textContent=pkg.name;box.appendChild(title);
 const tag=document.createElement("span");tag.className="tag";tag.textContent="Package boundary";box.appendChild(tag);
 for(const [label,value] of [
   ["Files",fmt(pkg.file_count)],["Symbols",fmt(pkg.symbol_count)],
   ["Depends on",fmt(pkg.dependency_count)],["Depended on by",fmt(pkg.dependant_count)],
   ["Outgoing cross-package imports",fmt(pkg.cross_package_imports)],
   ["Incoming cross-package imports",fmt(pkg.cross_package_dependant_imports)],
   ["Files in detected cycles",fmt(pkg.cycle_file_count)],
 ]){
   const row=document.createElement("div");row.className="kv";
   const a=document.createElement("span");a.textContent=label;
   const b=document.createElement("strong");b.textContent=value;row.append(a,b);box.appendChild(row);
 }
 for(const [label,items] of [
   ["Depends on",pkg.dependency_packages||[]],
   ["Depended on by",pkg.dependant_packages||[]],
   ["Highest-importance modules",pkg.top_files||[]],
 ]){
   const heading=document.createElement("label");heading.textContent=label;box.appendChild(heading);
   const list=document.createElement("div");list.className="detail-list";
   list.textContent=items.length?items.join("\n"):"None detected";box.appendChild(list);
 }
 document.getElementById("detail").appendChild(box);
 if(window.repoatlasSelectPackage)window.repoatlasSelectPackage(name);
}
function setMode(mode){
 const modules=mode==="modules";
 document.getElementById("graph").style.display=modules?"block":"none";
 document.getElementById("package-graph").style.display=modules?"none":"block";
 document.getElementById("show-modules").classList.toggle("active",modules);
 document.getElementById("show-packages").classList.toggle("active",!modules);
 if(!modules&&data.packages&&data.packages.length){
   document.getElementById("graph-count").textContent=data.packages.length+" packages · "+data.package_edges.length+" cross-package links";
   showPackageDetails(data.packages[0].name);
 }else if(modules){
   document.getElementById("graph-count").textContent=data.files.length+" modules · "+data.edges.length+" resolved import edges";
   if(selected)showDetails(selected);
 }
}
document.getElementById("show-modules").addEventListener("click",()=>setMode("modules"));
document.getElementById("show-packages").addEventListener("click",()=>setMode("packages"));
buildPackageGraph();
populateFilters();buildGraph();
if(data.files.length)showDetails(data.files[0].path);
})();
</script>
</body></html>"""
    document = document.replace("__REPOSITORY__", repo_name)
    document = document.replace("__REVISION__", str(report.get("revision") or "working tree"))
    document = document.replace("__DATA__", embedded)

    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination
