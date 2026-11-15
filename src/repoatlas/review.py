"""Committed and working-tree change review with static dependency impact."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

from repoatlas.analyzer import analyze_repository
from repoatlas.git import get_revision
from repoatlas.graph import build_graph, impact_analysis

_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def _run_git(root: Path, *args: str) -> str:
    """Run a bounded, non-interactive Git command without loading user configuration."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            env=_GIT_ENV,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "Git command failed.").strip()
        raise ValueError(f"Git change review failed: {detail}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Unable to complete Git change review: {exc}") from exc
    return result.stdout


def _validate_ref(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _REF_PATTERN.fullmatch(value)
        or ".." in value
        or value.endswith("/")
        or "@{" in value
    ):
        raise ValueError("base_ref must be a simple branch, tag, or commit reference.")
    return value


def _parse_name_status(output: str) -> dict[str, str]:
    """Parse NUL-delimited name/status output from Git."""
    tokens = output.split("\0")
    changes: dict[str, str] = {}
    index = 0
    while index < len(tokens) - 1:
        status = tokens[index]
        index += 1
        if not status:
            continue
        if status.startswith(("R", "C")):
            index += 1
        if index >= len(tokens):
            break
        path = tokens[index]
        index += 1
        if path:
            changes[path] = status[0]
    return changes


def _safe_relative_path(raw: str) -> str | None:
    path = PurePosixPath(raw)
    if path.is_absolute() or not raw or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _attention_level(affected_count: int, in_snapshot: bool) -> str:
    if not in_snapshot:
        return "Unmapped"
    if affected_count >= 10:
        return "High"
    if affected_count >= 4:
        return "Elevated"
    if affected_count:
        return "Focused"
    return "Local"


def review_changes(root: Path, *, base_ref: str = "main", max_depth: int = 5) -> dict:
    """Compare a base commit with the current working tree and trace import dependants.

    The operation is read-only. It includes committed changes, staged and unstaged
    tracked changes, and non-ignored untracked files. The graph is built from the
    current working-tree snapshot.
    """
    if not 1 <= max_depth <= 20:
        raise ValueError("max_depth must be between 1 and 20")
    validated_ref = _validate_ref(base_ref)
    try:
        repository = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Repository path is not accessible: {root}") from exc
    if not repository.is_dir():
        raise ValueError("Repository path must be a directory.")

    git_root = Path(_run_git(repository, "rev-parse", "--show-toplevel").strip()).resolve()
    if git_root != repository:
        raise ValueError("Review path must be the Git repository root, not a subdirectory.")

    base_revision = _run_git(
        repository, "rev-parse", "--verify", f"{validated_ref}^{{commit}}"
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", base_revision):
        raise ValueError("Git did not resolve base_ref to a commit.")

    tracked_changes = _parse_name_status(
        _run_git(
            repository, "diff", "--no-ext-diff", "--no-renames",
            "--name-status", "-z", base_revision, "--",
        )
    )
    untracked = _run_git(
        repository, "ls-files", "--others", "--exclude-standard", "-z"
    ).split("\0")
    for raw_path in untracked:
        safe_path = _safe_relative_path(raw_path)
        if safe_path:
            tracked_changes.setdefault(safe_path, "A")

    changes = []
    untracked_set = set(untracked)
    for raw_path, status in sorted(tracked_changes.items()):
        safe_path = _safe_relative_path(raw_path)
        if safe_path:
            changes.append({
                "path": safe_path,
                "status": status,
                "tracked": safe_path not in untracked_set,
            })

    analysis = analyze_repository(repository)
    graph = build_graph(analysis)
    graph_nodes = set(graph.get("nodes", []))
    affected_by: dict[str, dict] = defaultdict(lambda: {"distance": 99, "changed_by": []})

    for change in changes:
        path = change["path"]
        in_snapshot = path in graph_nodes
        impacted = (
            impact_analysis(graph, path, max_depth=max_depth)["affected"]
            if in_snapshot else []
        )
        impacted = sorted(impacted, key=lambda item: (item["distance"], item["path"]))
        change["in_snapshot"] = in_snapshot
        change["affected"] = impacted
        change["affected_count"] = len(impacted)
        change["attention"] = _attention_level(len(impacted), in_snapshot)
        for item in impacted:
            entry = affected_by[item["path"]]
            entry["distance"] = min(entry["distance"], int(item["distance"]))
            entry["changed_by"].append(path)

    affected_files = [
        {
            "path": path,
            "distance": data["distance"],
            "changed_by": sorted(set(data["changed_by"])),
        }
        for path, data in sorted(
            affected_by.items(), key=lambda item: (item[1]["distance"], item[0])
        )
    ]
    stats = {
        "changed_files": len(changes),
        "added_files": sum(item["status"] == "A" for item in changes),
        "modified_files": sum(item["status"] in {"M", "T"} for item in changes),
        "deleted_files": sum(item["status"] == "D" for item in changes),
        "unmapped_changes": sum(not item["in_snapshot"] for item in changes),
        "affected_files": len(affected_files),
        "high_attention_changes": sum(
            item["attention"] in {"High", "Elevated"} for item in changes
        ),
        "resolved_import_edges": graph["stats"]["resolved_edges"],
        "unresolved_import_edges": graph["stats"]["unresolved_edges"],
        "scanned_files": len(analysis.files),
    }
    return {
        "schema_version": 1,
        "repository": repository.name,
        "repository_path": str(repository),
        "base_ref": validated_ref,
        "base_revision": base_revision,
        "head_revision": get_revision(repository),
        "analysis_mode": "working-tree",
        "max_depth": max_depth,
        "changes": changes,
        "affected_files": affected_files,
        "stats": stats,
        "scan_warnings": list(analysis.warnings),
        "limitations": [
            "Impact is a static estimate over resolved file-import edges in the current working tree.",
            "Dynamic imports, reflection, dependency injection, generated code and runtime configuration are not modelled.",
            "Deleted or excluded files cannot be resolved in the current snapshot; their dependant impact is marked Unmapped.",
            "Untracked files are included when they are not ignored by Git and are readable by the bounded repository scanner.",
            "Attention levels are transparent review queues based on the count of statically identified dependants, not defect probabilities.",
        ],
    }


def render_change_review_html(report: dict, output_path: Path) -> Path:
    """Write a polished, self-contained, offline change-review dashboard."""
    destination = output_path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(report, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    document = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#080d1c">
<title>RepoAtlas · Change Review</title>
<style>
:root{color-scheme:dark;--bg:#080d1c;--panel:#101a2d;--line:#263653;--ink:#edf4ff;--muted:#91a4c1;--cyan:#61e4e1;--violet:#a78bfa;--green:#55d6a3;--amber:#f7bd68;--red:#fb7185}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 82% -10%,rgba(99,102,241,.22),transparent 35%),radial-gradient(ellipse at 0% 22%,rgba(20,184,166,.12),transparent 30%),var(--bg);color:var(--ink);font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,input,select{font:inherit}.shell{max-width:1500px;margin:auto;padding:28px clamp(16px,4vw,52px) 56px}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:38px}.brand{display:flex;align-items:center;gap:12px;font-weight:750;letter-spacing:.02em}.mark{width:36px;height:36px;border-radius:12px;background:linear-gradient(135deg,#61e4e1,#818cf8 65%,#a78bfa);display:grid;place-items:center;color:#07111f;font-weight:900;box-shadow:0 0 30px #61e4e144}.eyebrow{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--cyan);font-weight:800}.topnote{color:var(--muted);font-size:12px}.hero{padding:34px 38px;border:1px solid #4c5d7d66;border-radius:25px;background:linear-gradient(115deg,#172b43ef,#18213bef 53%,#34285aee);position:relative;overflow:hidden;box-shadow:0 24px 80px #0005}.hero:after{content:"";position:absolute;width:380px;height:380px;border-radius:50%;right:-110px;top:-220px;background:radial-gradient(circle,#61e4e177,transparent 68%);pointer-events:none}.hero h1{font-size:clamp(30px,4vw,48px);letter-spacing:-.045em;line-height:1.05;margin:12px 0}.hero p{color:#c6d4e9;max-width:760px;margin:0;font-size:15px}.meta{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}.pill{border:1px solid #7185a466;background:#ffffff0a;color:#dce8fb;border-radius:99px;padding:6px 11px;font-size:11px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0 26px}.metric,.panel{background:linear-gradient(160deg,#111d31,#0e1728);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 40px #0002}.metric{padding:19px 20px;min-height:112px}.metric .label{color:var(--muted);font-size:11px;letter-spacing:.1em;text-transform:uppercase}.metric .value{font-size:31px;letter-spacing:-.04em;font-weight:800;margin-top:6px}.metric .hint{color:var(--muted);font-size:11px}.layout{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(320px,.8fr);gap:16px}.panel{padding:22px;margin-bottom:16px}.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:17px}.panel h2{font-size:16px;letter-spacing:-.015em;margin:0 0 4px}.sub{color:var(--muted);font-size:12px;margin:0}.tag{font-size:10px;color:var(--cyan);background:#61e4e114;border:1px solid #61e4e133;border-radius:30px;padding:5px 9px;white-space:nowrap}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 13px}.toolbar input,.toolbar select{background:#0a1426;border:1px solid var(--line);color:var(--ink);padding:10px 12px;border-radius:10px;outline:none}.toolbar input{flex:1;min-width:190px}.toolbar input:focus,.toolbar select:focus{border-color:var(--cyan);box-shadow:0 0 0 3px #61e4e122}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:540px}th{text-align:left;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;padding:11px 10px;border-bottom:1px solid var(--line)}td{padding:13px 10px;border-bottom:1px solid #26365388;font-size:12px}tbody tr{cursor:pointer;transition:background .15s}tbody tr:hover,tbody tr.selected{background:#61e4e10d}td.path{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#d7e8ff}.badge{display:inline-flex;padding:4px 8px;border-radius:30px;font-size:10px;font-weight:800;letter-spacing:.04em}.high{color:#ff9aa9;background:#fb71851c}.elevated{color:#ffcf87;background:#f7bd681c}.focused{color:#86ece0;background:#61e4e11c}.local{color:#b6c5dc;background:#91a4c11c}.unmapped{color:#d6baff;background:#a78bfa20}.detail{min-height:250px}.detail-title{font-family:ui-monospace,monospace;word-break:break-all;color:#e2ecff;font-size:13px}.detail-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:15px 0}.detail-stat{background:#0a1426;padding:10px;border-radius:10px}.detail-stat strong{display:block;font-size:18px}.detail-stat span{font-size:10px;color:var(--muted)}.impact-list{list-style:none;padding:0;margin:12px 0 0}.impact-list li{padding:9px 10px;border-left:2px solid #61e4e188;background:#0a1426;margin:6px 0;border-radius:0 8px 8px 0;font:11px ui-monospace,monospace;color:#d8e4f7}.empty{color:var(--muted);padding:20px 0;font-size:12px}.risk-row{display:grid;grid-template-columns:74px 1fr 32px;gap:10px;align-items:center;margin:12px 0;font-size:11px;color:var(--muted)}.track{height:7px;border-radius:20px;background:#25344e;overflow:hidden}.fill{height:100%;border-radius:20px}.map{width:100%;height:auto;min-height:260px;background:radial-gradient(ellipse,#16294377,#0a1426);border:1px solid #243654;border-radius:14px}.map text{font:10px ui-monospace,monospace;fill:#d7e5f8}.map .muted{fill:#8298b7;font-size:9px}.map .edge{stroke:#5e789d;stroke-opacity:.48;stroke-width:1.4}.map .changed{fill:#61e4e1;stroke:#ccffff;stroke-width:2}.map .dependent{fill:#a78bfa;stroke:#e5dcff;stroke-width:1.5}.limits{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.limit{padding:12px;border:1px solid var(--line);border-radius:12px;color:var(--muted);font-size:11px;background:#0a1426}.limit strong{color:#dce8fb;display:block;margin-bottom:4px}.btn{border:1px solid #54718e;background:#192b43;color:var(--ink);padding:9px 12px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700}.btn:hover{border-color:var(--cyan);color:var(--cyan)}.footer{margin-top:22px;color:#7285a2;font-size:11px;text-align:center}@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}}@media(max-width:560px){.shell{padding:16px 12px 36px}.hero{padding:25px 21px}.grid{gap:9px}.metric{padding:14px}.metric .value{font-size:25px}.limits{grid-template-columns:1fr}.topnote{display:none}}
</style>
</head>
<body>
<div class="shell">
<header class="topbar"><div class="brand"><span class="mark">R</span><span>REPOATLAS <span style="color:#8ba0bd;font-weight:500">/ INTELLIGENCE</span></span></div><div class="topnote">LOCAL ANALYSIS · OFFLINE REPORT · READ-ONLY</div></header>
<section class="hero"><div class="eyebrow">ENGINEERING CHANGE REVIEW</div><h1>Change impact,<br>made visible.</h1><p>Trace changed files to their statically identified dependants. Prioritise review with evidence from the repository graph—not guesswork or opaque risk scores.</p><div class="meta"><span class="pill" id="repo-name">Repository</span><span class="pill" id="base-ref">Base reference</span><span class="pill" id="head-sha">Working-tree snapshot</span></div></section>
<section class="grid" id="metrics"></section>
<div class="layout">
<main>
<section class="panel"><div class="panel-head"><div><h2>Change surface</h2><p class="sub">Select a changed file to inspect its dependent modules.</p></div><span class="tag">INTERACTIVE</span></div><div class="toolbar"><input id="search" type="search" placeholder="Find a changed path…"><select id="risk-filter"><option value="all">All attention levels</option><option>High</option><option>Elevated</option><option>Focused</option><option>Local</option><option>Unmapped</option></select><button class="btn" id="export">Export JSON</button></div><div class="table-wrap"><table><thead><tr><th>Changed file</th><th>Status</th><th>Attention</th><th>Dependants</th></tr></thead><tbody id="change-rows"></tbody></table></div><div class="empty" id="no-changes" hidden>No changed files match this filter.</div></section>
<section class="panel"><div class="panel-head"><div><h2>Dependency impact map</h2><p class="sub">A compact view of changed modules and the dependants found downstream.</p></div><span class="tag">STATIC IMPORTS</span></div><svg id="impact-map" class="map" viewBox="0 0 900 330" role="img" aria-label="Changed modules connected to affected dependants"></svg><p class="sub" id="map-note" style="margin-top:10px"></p></section>
<section class="panel"><div class="panel-head"><div><h2>Analysis boundaries</h2><p class="sub">What the report can—and cannot—establish.</p></div></div><div class="limits" id="limitations"></div></section>
</main>
<aside>
<section class="panel detail"><div class="panel-head"><div><h2>Module inspector</h2><p class="sub">Evidence-led review detail</p></div><span class="tag">DETAIL</span></div><div id="detail-content" class="empty">Choose a changed file from the table to inspect its downstream impact.</div></section>
<section class="panel"><div class="panel-head"><div><h2>Review attention</h2><p class="sub">Count-based triage; not a defect probability.</p></div></div><div id="risk-breakdown"></div></section>
<section class="panel"><div class="panel-head"><div><h2>Scan quality</h2><p class="sub">Graph coverage context</p></div></div><div id="scan-quality"></div></section>
</aside>
</div>
<div class="footer">RepoAtlas AI · Generated locally from a bounded source snapshot · No source code uploaded by this report</div>
</div>
<script id="report-data" type="application/json">__REPORT_DATA__</script>
<script>
"use strict";
const report=JSON.parse(document.getElementById("report-data").textContent);
const $=id=>document.getElementById(id);
const make=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
const fmt=n=>Number(n||0).toLocaleString();
$("repo-name").textContent=report.repository;
$("base-ref").textContent="BASE · "+report.base_ref;
$("head-sha").textContent="WORKTREE · "+(report.head_revision||"uncommitted").slice(0,12);
const metricData=[
 ["Files changed",report.stats.changed_files,"Tracked, staged, unstaged + untracked"],
 ["Potential dependants",report.stats.affected_files,"Unique statically identified files"],
 ["Priority changes",report.stats.high_attention_changes,"High or elevated attention"],
 ["Resolved import edges",report.stats.resolved_import_edges,"Graph relationships used"]
];
for(const item of metricData){const card=make("article","metric");card.append(make("div","label",item[0]),make("div","value",fmt(item[1])),make("div","hint",item[2]));$("metrics").append(card);}
const tone=v=>String(v||"unmapped").toLowerCase();
let selected=null;
function renderRows(){
 const query=$("search").value.trim().toLowerCase(),risk=$("risk-filter").value;
 const rows=report.changes.filter(c=>(!query||c.path.toLowerCase().includes(query))&&(risk==="all"||c.attention===risk));
 $("change-rows").replaceChildren();$("no-changes").hidden=rows.length>0;
 for(const item of rows){
  const tr=make("tr",selected===item.path?"selected":"");tr.addEventListener("click",()=>{selected=item.path;renderRows();showDetail(item);});
  const attention=make("td","");attention.append(make("span","badge "+tone(item.attention),item.attention));
  tr.append(make("td","path",item.path),make("td","",item.status),attention,make("td","",fmt(item.affected_count)));$("change-rows").append(tr);
 }
}
function showDetail(item){
 const box=$("detail-content");box.replaceChildren();box.append(make("div","detail-title",item.path));
 box.append(make("p","sub","Status "+item.status+" · "+(item.tracked?"tracked":"untracked")+" · "+(item.in_snapshot?"included in source snapshot":"not represented in source graph")));
 const stats=make("div","detail-stats");
 for(const pair of [[item.affected_count,"Dependants"],[item.affected.filter(x=>x.distance===1).length,"Direct"],[item.affected.filter(x=>x.distance>1).length,"Transitive"]]){
  const d=make("div","detail-stat");d.append(make("strong","",fmt(pair[0])),make("span","",pair[1]));stats.append(d);
 }
 box.append(stats,make("span","badge "+tone(item.attention),item.attention+" attention"));
 if(item.affected.length){
  box.append(make("p","sub","Downstream dependants (nearest first)"));const list=make("ul","impact-list");
  for(const dep of item.affected){list.append(make("li","",dep.path+" · "+dep.distance+" hop"+(dep.distance===1?"":"s")));}
  box.append(list);
 }else{box.append(make("p","empty",item.in_snapshot?"No resolved import dependants were found.":"This file is outside the current static source graph."));}
}
$("search").addEventListener("input",renderRows);$("risk-filter").addEventListener("change",renderRows);
$("export").addEventListener("click",()=>{
 const blob=new Blob([JSON.stringify(report,null,2)],{type:"application/json"});
 const url=URL.createObjectURL(blob),a=make("a");a.href=url;a.download="repoatlas-change-review.json";a.click();URL.revokeObjectURL(url);
});
const riskOrder=["High","Elevated","Focused","Local","Unmapped"];
const riskColors={High:"#fb7185",Elevated:"#f7bd68",Focused:"#61e4e1",Local:"#91a4c1",Unmapped:"#a78bfa"};
for(const label of riskOrder){
 const count=report.changes.filter(c=>c.attention===label).length,row=make("div","risk-row");
 const track=make("div","track"),fill=make("div","fill");
 fill.style.width=(report.changes.length?count/report.changes.length*100:0)+"%";fill.style.background=riskColors[label];track.append(fill);
 row.append(make("span","",label),track,make("strong","",fmt(count)));$("risk-breakdown").append(row);
}
for(const pair of [["Files scanned",report.stats.scanned_files],["Unmapped changed files",report.stats.unmapped_changes],["Unresolved graph edges",report.stats.unresolved_import_edges],["Analysis depth",report.max_depth]]){
 const line=make("div","risk-row");line.style.gridTemplateColumns="1fr auto";line.append(make("span","",pair[0]),make("strong","",fmt(pair[1])));$("scan-quality").append(line);
}
for(const entry of report.limitations.entries()){
 const card=make("div","limit");card.append(make("strong","","BOUNDARY 0"+(entry[0]+1)),make("span","",entry[1]));$("limitations").append(card);
}
function renderMap(){
 const svg=$("impact-map"),ns="http://www.w3.org/2000/svg";
 const changes=report.changes.filter(c=>c.in_snapshot).slice(0,8),deps=report.affected_files.slice(0,18);
 const h=Math.max(300,Math.max(changes.length,deps.length,1)*31+76);svg.setAttribute("viewBox","0 0 900 "+h);
 const node=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const pair of Object.entries(attrs||{}))n.setAttribute(pair[0],pair[1]);if(text)n.textContent=text;svg.append(n);return n;};
 node("text",{x:30,y:24,class:"muted"},"CHANGED MODULES");node("text",{x:645,y:24,class:"muted"},"AFFECTED DEPENDANTS");
 const leftY=new Map(),rightY=new Map();
 changes.forEach((c,i)=>leftY.set(c.path,48+(i+0.5)*(h-66)/Math.max(changes.length,1)));
 deps.forEach((d,i)=>rightY.set(d.path,48+(i+0.5)*(h-66)/Math.max(deps.length,1)));
 for(const d of deps){for(const p of d.changed_by){if(leftY.has(p))node("line",{x1:265,y1:leftY.get(p),x2:625,y2:rightY.get(d.path),class:"edge"});}}
 for(const c of changes){const y=leftY.get(c.path);node("circle",{cx:250,cy:y,r:6,class:"changed"});node("text",{x:235,y:y-11,"text-anchor":"end"},c.path.length>34?"…"+c.path.slice(-32):c.path);}
 for(const d of deps){const y=rightY.get(d.path);node("circle",{cx:640,cy:y,r:5,class:"dependent"});node("text",{x:655,y:y+3},d.path.length>34?"…"+d.path.slice(-32):d.path);}
 $("map-note").textContent="Showing up to "+changes.length+" changed modules and "+deps.length+" affected files. JSON export retains the complete result.";
 if(!changes.length){node("text",{x:450,y:h/2,"text-anchor":"middle"},"No changed source modules are available to map.");}
}
renderRows();renderMap();
if(report.changes.length){selected=report.changes[0].path;showDetail(report.changes[0]);renderRows();}
</script>
</body>
</html>"""
    destination.write_text(document.replace("__REPORT_DATA__", payload), encoding="utf-8")
    return destination
