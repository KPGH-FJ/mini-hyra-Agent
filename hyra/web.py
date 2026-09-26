"""hyra serve: zero-dependency web dashboard over a --work directory.

    hyra serve --work run_out --port 8000

Reads the Experience Bank (eb/index.json + eb/solutions/*), report.json and
hyra.log live from disk, so it works both while a run is in progress and
afterwards. Single-file frontend, no external assets.
"""
from __future__ import annotations

import ast
import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("hyra.web")

MAX_FILE_CHARS = 60_000
TEXT_EXTS = {".py", ".sh", ".md", ".txt", ".json", ".c", ".cc", ".cpp", ".h",
             ".rs", ".go", ".js", ".ts", ".jsx", ".tsx", ".yaml", ".yml",
             ".toml", ".cfg", ".ini", ".log", ".csv", ".html", ".css"}


def _tail(path: Path, n: int = 300) -> str:
    try:
        data = path.read_text(errors="replace")
        lines = data.splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _solution_files(sol_dir: Path) -> dict:
    out = {}
    if not sol_dir.is_dir():
        return out
    for p in sorted(sol_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        rel = str(p.relative_to(sol_dir))
        try:
            txt = p.read_text(errors="replace")
        except Exception:
            continue
        out[rel] = txt[:MAX_FILE_CHARS]
        if len(out) >= 40:
            break
    return out


_FB_QUALITY = re.compile(r"quality=(-?[\d.eE+]+)")
_FB_DICT = re.compile(r"(cost|breakdown|baselines)=(\{.*?\})(?=[ )]|$)")
_FB_COSTHOW = re.compile(r"cost_how=(\w+)")


def parse_feedback(fb: str | None) -> dict | None:
    """Extract structured fields from an evaluator feedback string such as
    ``quality=77.0 cost={'asset_bytes': 123} breakdown={...} baselines={...}``.
    Tolerates plain-text feedback (returns None then)."""
    if not fb or not isinstance(fb, str):
        return None
    out: dict = {}
    m = _FB_QUALITY.search(fb)
    if m:
        try:
            out["quality"] = float(m.group(1))
        except ValueError:
            pass
    for key, lit in _FB_DICT.findall(fb):
        try:
            out[key] = ast.literal_eval(lit)
        except Exception:
            continue
    m = _FB_COSTHOW.search(fb)
    if m:
        out["cost_how"] = m.group(1)
    return out or None


def err_kind(err: str | None) -> str:
    e = (err or "").lower()
    if "proposal error" in e:
        if any(x in e for x in ("502", "503", "504", "bad gateway",
                                "http error", "timed out", "timeout",
                                "connection", "llm")):
            return "api/llm"
        return "proposal"
    if "evaluator" in e:
        return "evaluator"
    if "timeout" in e:
        return "timeout"
    if "solve.sh" in e or "exit" in e or "docker" in e:
        return "solve.sh"
    return "other"


def _research(work: Path) -> dict:
    """Optional research-state file: <work>/research.json then cwd.
    Powers the architecture/stage panels; dashboard stays generic without it."""
    for p in (work / "research.json", Path.cwd() / "research.json"):
        r = _read_json(p, None)
        if r:
            return r
    return {}


def _enrich(idx: list) -> list:
    """In-place: add parsed quality/cost_how onto each index entry."""
    for e in idx:
        fb = parse_feedback(e.get("feedback"))
        if fb:
            e["quality"] = fb.get("quality")
            e["cost_how"] = fb.get("cost_how")
    return idx


def build_status(work: Path) -> dict:
    idx = _enrich(_read_json(work / "eb" / "index.json", []))
    scored = [e for e in idx if e.get("score") is not None]
    best = max(scored, key=lambda e: e["score"], default=None)
    report = _read_json(work / "report.json", None)
    created = [e.get("created", 0) for e in idx]
    idx_mtime = 0.0
    try:
        idx_mtime = (work / "eb" / "index.json").stat().st_mtime
    except OSError:
        pass
    running = report is None and idx_mtime > time.time() - 30
    baselines: dict = {}
    seed_score = None
    error_kinds: dict = {}
    suspicious = 0
    for e in idx:
        if e.get("error"):
            k = err_kind(e["error"])
            error_kinds[k] = error_kinds.get(k, 0) + 1
        fb = parse_feedback(e.get("feedback"))
        if fb:
            if fb.get("cost_how") == "suspicious":
                suspicious += 1
            if not baselines and isinstance(fb.get("baselines"), dict):
                baselines = fb["baselines"]
        if e.get("direction") == "seed" and e.get("score") is not None:
            seed_score = e["score"]
    return {
        "running": running,
        "finished": report is not None,
        "commits": len(idx),
        "scored": len(scored),
        "failed": len(idx) - len(scored),
        "best": best,
        "eval_versions": sorted({e.get("eval_version", 0) for e in idx}),
        "elapsed": (max(created) - min(created)) if created else 0,
        "now": time.time(),
        "report": report,
        "baselines": baselines,
        "seed_score": seed_score,
        "error_kinds": error_kinds,
        "suspicious": suspicious,
    }


INDEX_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>LifeModel 研究看板</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;
--acc:#58a6ff;--good:#3fb950;--bad:#f85149;--warn:#d29922}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,Segoe UI,
Roboto,"Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif;padding:14px 22px 20px}
h1{font-size:17px;display:flex;align-items:center;gap:10px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--dim);display:inline-block}
.dot.on{background:var(--good);box-shadow:0 0 8px var(--good)}
.dot.done{background:var(--acc)}
.small{font-size:12px;color:var(--dim)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
section{scroll-margin-top:64px}
/* —— 顶部导航 —— */
.topnav{position:sticky;top:0;z-index:50;background:rgba(13,17,23,.92);backdrop-filter:blur(6px);
margin:-14px -22px 12px;padding:9px 22px;border-bottom:1px solid var(--line);
display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.topnav .brand{font-weight:700;font-size:13.5px;margin-right:12px}
.topnav a{color:var(--dim);text-decoration:none;font-size:12px;padding:4px 9px;border-radius:6px}
.topnav a:hover{color:var(--fg);background:#21262d}
.topnav a.on{color:var(--acc);background:rgba(88,166,255,.12)}
/* —— 状态横幅 —— */
.banner{display:flex;gap:20px;align-items:center;background:#161b22;border:1px solid var(--line);
border-left:4px solid var(--acc);border-radius:10px;padding:11px 16px;margin-bottom:8px;flex-wrap:wrap}
.banner .verdict{font-size:15px;font-weight:600}
.banner .seg{color:var(--dim);font-size:12px}
.banner .seg b{color:var(--fg)}
.pulse{width:9px;height:9px;border-radius:50%;background:var(--good);flex:none;
box-shadow:0 0 0 3px rgba(63,185,80,.25);animation:p 2s infinite}
@keyframes p{50%{box-shadow:0 0 0 6px rgba(63,185,80,.06)}}
/* —— 名词解释：首读者悬停即释义 —— */
.term{border-bottom:1px dotted var(--dim);cursor:help}
.glossary{display:flex;gap:5px 18px;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);
border-radius:10px;padding:8px 14px;margin-bottom:12px;font-size:12px;color:var(--dim)}
.glossary b{color:var(--fg);font-weight:600}
/* —— 实时统计行 —— */
.stats{display:flex;gap:22px;flex-wrap:wrap;color:var(--dim);font-size:12.5px;margin-bottom:14px}
.stats>span{display:inline-flex;gap:6px;align-items:center}
.stats b{color:var(--fg);font-weight:600}
/* —— 面板（可折叠） —— */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;min-width:0;overflow:hidden;margin-bottom:14px}
.grid .panel{margin-bottom:0}
.panel>h2{font-size:13px;font-weight:600;color:var(--fg);margin-bottom:10px;
cursor:pointer;user-select:none;display:flex;align-items:center;gap:7px}
.panel>h2:before{content:'▾';color:var(--dim);font-size:11px;transition:transform .15s}
.panel.closed>h2:before{transform:rotate(-90deg)}
.panel.closed>h2{margin-bottom:0}
.panel>.body{transition:opacity .15s}
.panel.closed>.body{display:none}
/* —— 架构图 —— */
.mod{cursor:pointer}
.mod rect.frame{transition:stroke .15s}
.mod:hover rect.frame{stroke:var(--acc)}
.mod.sel rect.frame{stroke:var(--acc);stroke-width:2.6}
/* —— 阶段 —— */
.strow{display:flex;gap:9px;align-items:baseline;margin:5px 0;font-size:13px}
.strow .tag{min-width:44px;text-align:center;flex:none}
.rnd{margin:2px 0 2px 52px;font-size:12.5px;color:var(--dim)}
.rnd b{color:var(--fg)}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;
border:1px solid var(--line);color:var(--dim)}
.exp table{font-size:12.5px}
.exp td{padding:3px 8px;border-bottom:1px solid #21262d}
/* —— 研究脉络 —— */
.tl{margin-top:4px}
.tlit{position:relative;padding:3px 0 10px 18px;border-left:1px solid #30363d;margin-left:6px}
.tlit:before{content:'';position:absolute;left:-5px;top:10px;width:8px;height:8px;border-radius:50%;background:var(--acc)}
.tlit .tw{font-size:11px;color:var(--dim)}
.tlit b{font-size:13px}
.tlit .tt{font-size:12.5px;color:var(--dim);white-space:normal}
/* —— 当前轮卡片 —— */
.roundcard{display:flex;gap:14px;flex-wrap:wrap}
.rc{flex:1;min-width:165px;background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:9px 12px}
.rc .k{font-size:11px;color:var(--dim);margin-bottom:3px}
.rc .v{font-size:13.5px;font-weight:600}
.pbar{height:6px;background:#21262d;border-radius:3px;margin-top:8px;overflow:hidden}
.pbar i{display:block;height:100%;background:var(--acc);border-radius:3px}
/* —— 差距地图 —— */
table.gap{border-collapse:collapse;font-size:12px;width:100%}
table.gap th,table.gap td{padding:5px 8px;text-align:center;border:1px solid #21262d}
table.gap th{background:#0d1117;font-weight:600;position:sticky;top:0}
table.gap td.fam{text-align:left;color:var(--dim);cursor:default;white-space:nowrap}
.cell{border-radius:4px;display:inline-block;min-width:46px;padding:2px 6px;cursor:pointer}
.cell:hover{outline:2px solid var(--acc)}
.legend{display:flex;gap:14px;margin-top:8px;font-size:11.5px;color:var(--dim);flex-wrap:wrap}
.legend .cell{cursor:default;min-width:38px}
.gapdetail{margin-top:10px;padding:9px 12px;background:#0d1117;border:1px solid var(--line);
border-radius:8px;font-size:12.5px;display:none}
/* —— 排行榜 —— */
table.rank{border-collapse:collapse;font-size:12.5px;width:100%}
table.rank th{color:var(--dim);font-weight:600;text-align:left;padding:5px 8px;border-bottom:1px solid var(--line)}
table.rank td{padding:5px 8px;border-bottom:1px solid #21262d}
table.rank tbody tr{transition:background .1s}
table.rank tbody tr:hover{background:#1c2128}
.lead td:first-child{color:var(--good);font-weight:600}
/* —— 证据区（EB 实时面板） —— */
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--dim);text-align:left;font-weight:500;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:5px 8px;border-bottom:1px solid #21262d;white-space:nowrap;
max-width:460px;overflow:hidden;text-overflow:ellipsis}
tr.sel td{background:#1f2a3a}
tbody tr:hover td{background:#1b2330;cursor:pointer}
svg{display:block;width:100%}
pre{background:#0a0d12;border:1px solid var(--line);border-radius:6px;
padding:12px;overflow:auto;max-height:340px;font-size:12.5px;white-space:pre}
.files{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 8px}
.fbtn{background:#21262d;border:1px solid var(--line);border-radius:6px;
padding:3px 11px;font-size:12.5px;cursor:pointer;color:var(--fg)}
.fbtn.on{border-color:var(--acc);color:var(--acc)}
.best{color:var(--good);font-weight:600}
.neg{color:var(--bad)}
.logbox{max-height:220px}
.node{cursor:pointer}
.node text{font-size:11px;fill:var(--dim)}
.brow{display:flex;align-items:center;gap:10px;margin:4px 0;font-size:12.5px}
.blab{width:70px;color:var(--dim);text-align:right;flex:none}
.bwrap{flex:1;height:11px;background:#21262d;border-radius:6px;overflow:hidden}
.bfill{height:100%;background:var(--acc);border-radius:6px}
.bval{width:48px;color:var(--dim);flex:none}
.fb{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 10px}
#detail{display:none;margin-bottom:14px}
.totop{position:fixed;right:20px;bottom:20px;background:var(--panel);border:1px solid var(--line);
border-radius:8px;padding:7px 12px;font-size:12px;color:var(--dim);cursor:pointer;display:none;z-index:60}
.totop:hover{color:var(--fg)}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>

<nav class="topnav">
  <h1 style="margin:0"><span class="dot" id="runDot"></span><span class="brand">LifeModel 研究看板</span></h1>
  <a href="#sec-sys">系统</a><a href="#sec-road">脉络</a><a href="#sec-now">当前轮</a>
  <a href="#sec-gap">差距地图</a><a href="#sec-rank">排行榜</a><a href="#sec-evi">证据</a>
  <span class="small" id="taskName" style="margin-left:auto"></span>
</nav>

<div class="banner" id="banner" style="display:none"></div>
<div class="small" id="readhint" style="display:none;margin-bottom:8px">读法：从上往下 —— 先一句话结论，再系统、再历史、再当前在做什么、差在哪、证据在最后。板块标题可点击折叠；虚线下划线的词悬停有解释。</div>
<div class="glossary" id="glossary" style="display:none"></div>
<div class="stats" id="stats"></div>

<div id="research" style="display:none">
<div class="grid" id="sec-sys">
  <div class="panel"><h2>系统长什么样 —— 五模块，接口冻结，每次只优化一块</h2><div class="body">
    <svg id="arch" height="230"></svg>
    <div class="small" id="modInfo" style="margin-top:6px">点击任一模块看它当前的实现与下一步。</div></div></div>
  <div class="panel"><h2>研究分几步走</h2><div class="body"><div id="stages"></div><div id="experiment"></div></div></div>
</div>
<section id="sec-road"><div class="panel"><h2>研究脉络 —— 每一步留下了什么结论</h2><div class="body"><div class="tl" id="timeline"></div></div></div></section>
<section id="sec-now"><div class="panel" id="nowPanel" style="display:none"><h2>当前这一轮在做什么</h2><div class="body">
  <div class="roundcard" id="roundcard"></div></div></div></section>
<div class="grid">
  <div class="panel" id="gapPanel" style="display:none"><h2 id="sec-gap">差距地图 —— 哪类题还没人做对</h2><div class="body">
    <div class="small" style="margin-bottom:8px">点格子看"这题考什么"。红色 = 空白得分区，就是下一轮的目标。</div>
    <div style="max-height:340px;overflow:auto"><table class="gap" id="gapmap"></table></div>
    <div class="legend">
      <span><span class="cell" style="background:rgba(63,185,80,.85);color:#0d1117">✓</span> 满分</span>
      <span><span class="cell" style="background:rgba(210,153,34,.75);color:#0d1117">0.x</span> 半对</span>
      <span><span class="cell" style="background:rgba(248,81,73,.9)">0</span> 全错</span>
    </div>
    <div class="gapdetail" id="gapdetail"></div></div></div>
  <div class="panel" id="rankPanel" style="display:none"><h2 id="sec-rank">排行榜 <span class="small" style="font-weight:400">得分 = 答对题数 − 成本</span></h2><div class="body">
    <table class="rank" id="rank"></table></div></div>
</div>
</div>

<div class="grid" id="sec-evi">
  <div class="panel"><h2>得分走势 <span class="small" style="font-weight:400">蓝线=得分，虚线=答对数</span></h2><div class="body">
    <svg id="curve" height="240"></svg>
    <div class="small" id="legend" style="margin-top:6px"></div></div></div>
  <div class="panel"><h2>解的谱系 <span class="small" style="font-weight:400">谁从谁进化来 · 点击节点查看解</span></h2><div class="body">
    <svg id="tree" height="240"></svg></div></div>
</div>
<div id="detail" class="panel">
  <h2 id="detTitle">Solution</h2><div class="body">
  <div class="fb" id="detFb"></div>
  <div id="detBars"></div>
  <div class="files" id="detFiles"></div>
  <pre class="mono" id="detBody"></pre></div>
</div>
<div class="grid">
  <div class="panel"><h2>候选解明细</h2><div class="body">
    <div style="max-height:320px;overflow:auto"><table id="tbl">
      <thead><tr><th>编号</th><th>得分</th><th>策略</th><th>父代</th>
      <th>考题版本</th><th>评语 / 错误</th></tr></thead><tbody></tbody></table>
    </div></div></div>
  <div class="panel"><h2>运行日志</h2><div class="body">
    <pre class="mono logbox" id="log">loading…</pre></div></div>
</div>

<div class="totop" id="totop" onclick="scrollTo({top:0,behavior:'smooth'})">↑ 回顶部</div>

<script>
const DC={seed:'#8b949e',exploit:'#58a6ff',explore:'#3fb950',fresh:'#bc8cff',
repair:'#e08a00',hybrid:'#39c5cf',err:'#f85149'};
let sel=null;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=v=>v==null?'—':(typeof v==='number'?v.toPrecision(6):v);
const col=d=>DC[d]||'#8b949e';

async function j(u){const r=await fetch(u);return r.json()}

/* 可折叠面板 */
document.querySelectorAll('.panel>h2').forEach(h=>h.onclick=()=>h.parentElement.classList.toggle('closed'));

function drawCurve(svg,idx,s){
  const el=document.getElementById(svg);el.innerHTML='';
  const W=el.clientWidth||560,H=240,P=28,RM=76;
  el.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const pts=idx.filter(e=>e.score!=null);
  if(!pts.length){el.innerHTML='<text x="20" y="120" fill="#8b949e">还没有计分的解</text>';return}
  const refs=[];
  if(s&&s.seed_score!=null)refs.push(['seed',s.seed_score,'#8b949e']);
  if(s&&s.baselines)Object.entries(s.baselines).forEach(([k,v])=>{
    if(typeof v==='number')refs.push([k,v,'#d29922'])});
  const ys=[...pts.map(e=>e.score),...refs.map(r=>r[1])];
  const lo=Math.min(...ys),hi=Math.max(...ys);
  const y=v=>H-P-(v-lo)/((hi-lo)||1)*(H-2*P);
  const x=i=>P+i/Math.max(idx.length-1,1)*(W-P-RM);
  let g='';
  [lo,hi].forEach(v=>{g+=`<line x1="${P}" x2="${W-P}" y1="${y(v)}" y2="${y(v)}"
    stroke="#30363d" stroke-dasharray="3"/><text x="3" y="${y(v)+4}"
    fill="#8b949e" font-size="11">${v.toPrecision(4)}</text>`});
  refs.forEach(([k,v,c])=>{g+=`<line x1="${P}" x2="${W-RM}" y1="${y(v)}" y2="${y(v)}"
    stroke="${c}" stroke-dasharray="2 4" opacity=".6"/>
    <text x="${W-RM+5}" y="${y(v)+4}" font-size="11" fill="${c}">${k} ${v.toPrecision(4)}</text>`});
  let best=-1e18,bpath='';
  idx.forEach((e,i)=>{if(e.score!=null&&e.score>best){best=e.score;
    bpath+=`${i?'L':'M'}${x(i)},${y(best)} `}});
  g+=`<path d="${bpath}" fill="none" stroke="#3fb950" stroke-width="1.2"
    stroke-dasharray="4 3" opacity=".7"/>`;
  g+='<path d="'+idx.map((e,i)=>e.score==null?'':
    `${i?'L':'M'}${x(i)},${y(e.score)}`).filter(s=>s).join(' ')+
    '" fill="none" stroke="#58a6ff" stroke-width="1.4" opacity=".85"/>';
  const qp=idx.map((e,i)=>e.quality==null?'':
    `${i?'L':'M'}${x(i)},${y(e.quality)}`).filter(s=>s).join(' ');
  if(qp)g+=`<path d="${qp}" fill="none" stroke="#bc8cff" stroke-width="1"
    stroke-dasharray="2 3" opacity=".6"/>`;
  idx.forEach((e,i)=>{if(e.score==null)return;
    g+=`<circle class="node" data-sid="${e.id}" cx="${x(i)}" cy="${y(e.score)}"
      r="5.5" fill="${col(e.direction)}"><title>${e.id} ${e.score}</title></circle>`});
  el.innerHTML=g;
  el.querySelectorAll('.node').forEach(n=>n.onclick=()=>pick(n.dataset.sid));
  document.getElementById('legend').innerHTML=
    Object.keys(DC).map(k=>`<span class="tag" style="border-color:${col(k)};color:${col(k)}">${k}</span>`).join(' ')+
    '<span class="tag" style="border-color:#bc8cff;color:#bc8cff">答对数</span>';
}

function drawTree(idx){
  const el=document.getElementById('tree');el.innerHTML='';
  const W=el.clientWidth||560,H=240;
  const dep={},ord={};
  idx.forEach(e=>{dep[e.id]=e.parents&&e.parents.length?
    Math.max(...e.parents.map(p=>(dep[p]??0)))+1:0});
  const byD={};idx.forEach(e=>(byD[dep[e.id]]=byD[dep[e.id]]||[]).push(e.id));
  const D=Math.max(...Object.values(dep),0);
  Object.keys(byD).forEach(d=>byD[d].sort().forEach((id,i)=>ord[id]=i));
  const px=id=>40+dep[id]/Math.max(D,1)*(W-80);
  const py=id=>{const n=byD[dep[id]].length;
    return n===1?H/2:34+ord[id]/(n-1)*(H-68)};
  let g='';
  idx.forEach(e=>(e.parents||[]).forEach(p=>{if(dep[p]==null)return;
    g+=`<line x1="${px(p)}" y1="${py(p)}" x2="${px(e.id)}" y2="${py(e.id)}"
      stroke="#30363d" stroke-width="1"/>`}));
  const best=document._best;
  idx.forEach(e=>{const r=e.id===best?8:5.5;
    g+=`<g class="node" data-sid="${e.id}"><circle cx="${px(e.id)}" cy="${py(e.id)}"
      r="${r}" fill="${e.score==null?DC.err:col(e.direction)}"
      ${e.id===best?'stroke="#3fb950" stroke-width="2"':''}></circle>
      <text x="${px(e.id)+8}" y="${py(e.id)+3}">${e.id}</text></g>`});
  el.setAttribute('viewBox',`0 0 ${W} ${H}`);el.innerHTML=g;
  el.querySelectorAll('.node').forEach(n=>n.onclick=()=>pick(n.dataset.sid));
}

function fbView(d){
  const f=d.fb,out=document.getElementById('detFb'),
        bars=document.getElementById('detBars');
  out.innerHTML='';bars.innerHTML='';
  if(!f)return;
  const s=d.meta&&d.meta.score;
  let h='';
  if(f.quality!=null)h+=`<span class="tag">答对 ${f.quality.toPrecision(5)}</span>`;
  if(f.cost)h+='<span class="tag">成本 '+Object.entries(f.cost).map(([k,v])=>
    k==='llm_tokens'?`${k}=${v}`:`${k}=${(v/1024).toFixed(1)}KB`).join(' ')+'</span>';
  if(f.cost_how){const ch=f.cost_how,
    c=ch==='measured'?'var(--good)':ch==='suspicious'?'var(--bad)':'var(--warn)';
    h+=`<span class="tag" style="color:${c};border-color:${c}" title="成本记账是否可信：measured=实测/reported=自报/suspicious=可疑">${ch}</span>`}
  if(f.baselines)h+=Object.entries(f.baselines).map(([k,v])=>{
    const beat=typeof v==='number'&&s!=null&&s>v;
    return `<span class="tag" style="color:${beat?'var(--good)':'var(--bad)'};border-color:${beat?'var(--good)':'var(--bad)'}">${k} ${typeof v==='number'?v.toPrecision(4):v} ${beat?'beat':'below'}</span>`}).join('');
  out.innerHTML=h;
  if(f.breakdown)bars.innerHTML='<h2 style="margin:4px 0;font-size:12.5px">各类题型得分</h2>'+
    Object.entries(f.breakdown).map(([k,v])=>{const pct=Math.max(0,Math.min(1,v))*100;
      return `<div class="brow"><span class="blab">${k}</span>
      <div class="bwrap"><div class="bfill" style="width:${pct}%;background:${pct>=99?'var(--good)':pct<50?'var(--warn)':'var(--acc)'}"></div></div>
      <span class="bval">${pct.toFixed(0)}%</span></div>`}).join('');
}

async function pick(sid){
  sel=sid;
  const d=await j('/api/solution/'+sid);
  document.getElementById('detail').style.display='block';
  document.getElementById('detTitle').textContent=
    `解 ${sid}  ·  得分=${fmt(d.meta&&d.meta.score)}  ·  ${d.meta?d.meta.direction:''}`;
  fbView(d);
  const fs=document.getElementById('detFiles');fs.innerHTML='';
  const names=Object.keys(d.files);
  names.forEach(n=>{const b=document.createElement('button');
    b.className='fbtn';b.textContent=n;
    b.onclick=()=>{fs.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('on'));
      b.classList.add('on');document.getElementById('detBody').textContent=d.files[n]};
    fs.appendChild(b)});
  if(names.length)fs.children[0].click();
  else document.getElementById('detBody').textContent='(no readable files)';
  document.getElementById('detail').scrollIntoView({behavior:'smooth',block:'nearest'});
}

const MC={done:'#3fb950',v0:'#8b949e',next:'#58a6ff',current:'#d29922',todo:'#6e7681'};
const SLBL={done:'已完成',v0:'v0 骨架',next:'下一轮',current:'进行中',todo:'未开始'};

function drawBanner(r){
  const c=r.current||{};
  const b=document.getElementById('banner');
  const segs=[['当前轮',c.round],['领跑',c.leader],['最强进化解',c.best_evolved],['剩余差距',c.remaining]]
    .filter(x=>x[1]);
  if(!(c.verdict||segs.length))return;
  b.style.display='flex';
  b.innerHTML='<div class="pulse"></div>'+
    (c.verdict?`<div class="verdict">${esc(c.verdict)}</div>`:'')+
    segs.map(([k,v])=>`<div class="seg">${k} <b>${esc(v)}</b></div>`).join('');
  document.getElementById('readhint').style.display='block';
  const gl=document.getElementById('glossary');
  if(r.glossary&&r.glossary.length){
    gl.style.display='flex';
    gl.innerHTML=r.glossary.map(([t,d])=>`<span><b class="term" title="${esc(d)}">${esc(t)}</b> ${esc(d)}</span>`).join('');
  }
}

function drawCurrent(r){
  const c=r.current,p=document.getElementById('nowPanel');
  if(!(c&&(c.goal||c.progress)))return;
  p.style.display='block';
  const card=(k,v,desc,extra='')=>`<div class="rc"><div class="k">${k}</div><div class="v">${v}</div>${desc?`<div class="small" style="margin-top:4px">${desc}</div>`:''}${extra}</div>`;
  document.getElementById('roundcard').innerHTML=
    card('本轮目标',esc(c.goal||''),esc(c.goal_desc||''))+
    card('对手线',esc(c.opponent||''),esc(c.opponent_desc||''))+
    card('进度',esc(c.progress||''),esc(c.window||''),
      c.progress_pct!=null?`<div class="pbar"><i style="width:${c.progress_pct}%"></i></div>`:'')+
    card('这一轮的打法',esc(c.approach||''),esc(c.approach_desc||''));
}

function drawGap(r){
  const tb=r.experiment&&r.experiment.table;
  if(tb){document.getElementById('rankPanel').style.display='block';
    document.getElementById('rank').innerHTML='<thead><tr><th>选手</th><th>说明</th><th>得分</th><th>答对题数</th></tr></thead><tbody>'+
    tb.map((row,i)=>`<tr class="${i===0?'lead':''}"><td class="mono">${esc(row[0])}</td>
      <td class="small" style="white-space:normal">${esc(row[1])}</td>
      <td class="mono"><b>${row[2]}</b></td><td>${row[3]}</td></tr>`).join('')+'</tbody>';}
  const gp=r.gap;if(!(gp&&gp.rows))return;
  document.getElementById('gapPanel').style.display='block';
  const gc=v=>v>=0.99?'rgba(63,185,80,.85)':v>=0.5?'rgba(210,153,34,.75)':v>0?'rgba(248,81,73,.55)':'rgba(248,81,73,.9)';
  const tc=v=>v>=0.5?'#0d1117':'#e6edf3';
  let h='<thead><tr><th style="text-align:left">题型</th>'+gp.cols.map(c=>`<th>${esc(c)}</th>`).join('')+'</tr></thead><tbody>';
  let lastGrp='';
  gp.rows.forEach(([grp,fam])=>{
    h+=`<tr><td class="fam">${grp!==lastGrp?`<b style="color:#8b949e">${esc(grp)}</b><br>`:''}${esc(fam)}</td>`;
    lastGrp=grp;
    (gp.vals[fam]||[]).forEach((v,ci)=>{h+=`<td><span class="cell" data-f="${esc(fam)}" data-c="${esc(gp.cols[ci])}" data-v="${v}"
      title="${esc(fam)} · ${esc(gp.cols[ci])} · 得分率 ${v}"
      style="background:${gc(v)};color:${tc(v)}">${v>=0.99?'✓':v===0?'0':v.toFixed(1)}</span></td>`});
    h+='</tr>'});
  document.getElementById('gapmap').innerHTML=h+'</tbody>';
  document.querySelectorAll('#gapmap .cell').forEach(c=>c.onclick=()=>{
    const d=document.getElementById('gapdetail');
    d.style.display='block';
    d.innerHTML=`<b>${esc(c.dataset.f)}</b> — ${esc((r.probeinfo||{})[c.dataset.f]||'')}`
      +`<br><span class="small">${esc(c.dataset.c)} 在此题得分率 <b>${c.dataset.v}</b></span>`;
  });
}

function drawResearch(r){
  document.getElementById('research').style.display='block';
  drawBanner(r);drawCurrent(r);drawGap(r);
  const pos={M1:[168,26],M3:[308,26],M2:[448,26],M4:[588,26]},bw=126,bh=100;
  const byId={};(r.modules||[]).forEach(m=>byId[m.id]=m);
  let g=`<defs><marker id="ar" markerWidth="7" markerHeight="7" refX="6" refY="3"
    orient="auto"><path d="M0,0 L6,3 L0,6" fill="none" stroke="#8b949e"/></marker></defs>
    <rect x="16" y="56" width="104" height="46" rx="8" fill="#21262d" stroke="#30363d"/>
    <text x="68" y="74" text-anchor="middle" font-size="13" fill="#e6edf3">原始记录</text>
    <text x="68" y="90" text-anchor="middle" font-size="11" fill="#8b949e">90 天合成人生</text>
    <rect x="762" y="56" width="104" height="46" rx="8" fill="#21262d" stroke="#30363d"/>
    <text x="814" y="74" text-anchor="middle" font-size="13" fill="#e6edf3">回答/视图</text>
    <text x="814" y="90" text-anchor="middle" font-size="11" fill="#8b949e">对用户</text>`;
  const link=(x1,x2)=>`<line x1="${x1}" y1="79" x2="${x2}" y2="79" stroke="#8b949e" stroke-width="1.4" marker-end="url(#ar)"/>`;
  g+=link(120,168)+link(168+126,308)+link(308+126,448)+link(448+126,588)+link(588+126,762);
  ['M1','M3','M2','M4'].forEach(id=>{const m=byId[id];if(!m)return;
    const[x,y]=pos[id],c=MC[m.status]||'#6e7681';
    g+=`<g class="mod" data-m="${id}"><rect class="frame" x="${x}" y="${y}"
      width="${bw}" height="${bh}" rx="9" fill="#161b22" stroke="${c}" stroke-width="1.6"/>
      <rect x="${x+bw-56}" y="${y+8}" width="48" height="18" rx="9" fill="none" stroke="${c}"/>
      <text x="${x+bw-32}" y="${y+21}" text-anchor="middle" font-size="10.5" fill="${c}">${SLBL[m.status]||m.status}</text>
      <text x="${x+10}" y="${y+24}" font-size="14.5" font-weight="600" fill="#e6edf3">${m.id} ${m.name.split(' ')[0]}</text>
      <text x="${x+10}" y="${y+42}" font-size="11" fill="#8b949e">${esc(m.role||'')}</text>
      <text x="${x+10}" y="${y+63}" font-size="10.5" font-family="ui-monospace,monospace" fill="#58a6ff">${esc((m.impl||'').slice(0,20))}</text>
      ${m.score?`<text x="${x+10}" y="${y+86}" font-size="11.5" fill="#3fb950">★ ${m.score}</text>`:
        `<text x="${x+10}" y="${y+86}" font-size="10.5" fill="#6e7681">${esc((m.next||'已定稿').slice(0,19))}</text>`}</g>`;});
  const m5=byId.M5;
  if(m5){const c=MC[m5.status]||'#6e7681',x=322,y=170,w=250,h=52;
    g+=`<line x1="${x+w*0.33}" y1="${y}" x2="392" y2="129" stroke="#8b949e" stroke-dasharray="3 3" marker-end="url(#ar)"/>
      <line x1="${x+w*0.66}" y1="${y}" x2="500" y2="129" stroke="#8b949e" stroke-dasharray="3 3" marker-end="url(#ar)"/>
      <g class="mod" data-m="M5"><rect class="frame" x="${x}" y="${y}" width="${w}" height="${h}" rx="9" fill="#161b22" stroke="${c}" stroke-width="1.6"/>
      <text x="${x+10}" y="${y+20}" font-size="14" font-weight="600" fill="#e6edf3">${m5.id} ${m5.name} <tspan font-size="11" fill="${c}">${SLBL[m5.status]||''}</tspan></text>
      <text x="${x+10}" y="${y+38}" font-size="11" fill="#8b949e">${esc(m5.role||'')} — ${esc((m5.impl||'').slice(0,24))}</text></g>`;}
  const el=document.getElementById('arch');el.innerHTML=g;
  el.setAttribute('viewBox','0 0 882 230');el.setAttribute('width','100%');
  el.querySelectorAll('.mod').forEach(n=>n.onclick=()=>{
    el.querySelectorAll('.mod').forEach(x=>x.classList.remove('sel'));
    n.classList.add('sel');
    const m=byId[n.dataset.m];if(!m)return;
    document.getElementById('modInfo').innerHTML=
      `<b>${m.id} ${esc(m.name)}</b> · ${esc(m.role||'')}<br>
       当前实现：<span class="mono">${esc(m.impl||'—')}</span>
       ${m.score?` · 得分 <b class="best">${m.score}</b>`:''}<br>
       ${m.note?esc(m.note)+'<br>':''}${m.next?'下一步：'+esc(m.next):''}`});
  const st=document.getElementById('stages');
  st.innerHTML=(r.stages||[]).map(s=>{
    const c=MC[s.status]||'#6e7681';
    return `<div class="strow"><span class="tag" style="color:${c};border-color:${c}">${s.id}</span>
      <b>${esc(s.name)}</b><span class="small">${esc(s.desc||'')}</span></div>`+
      (s.rounds||[]).map(rw=>{const rc=MC[rw.status]||'#6e7681';
        return `<div class="rnd">└ <b style="color:${rc}">${rw.id}</b> ${esc(rw.module)} — <span style="color:${rc}">${SLBL[rw.status]||rw.status}</span>${rw.result||rw.desc?`：${esc(rw.result||rw.desc)}`:''}</div>`}).join('');
  }).join('')+(r.tagline?`<div class="small" style="margin-top:8px">${esc(r.tagline)}</div>`:'');
  const tl=document.getElementById('timeline');
  tl.innerHTML=(r.timeline||[]).map(t=>
    `<div class="tlit"><div class="tw">${esc(t.when||'')}</div>
     <b>${esc(t.title)}</b><div class="tt">${esc(t.text||'')}</div></div>`).join('');
  const ex=r.experiment;
  document.getElementById('experiment').innerHTML=ex?`<div class="exp">
    <div class="small" style="margin:10px 0 4px"><b>${esc(ex.bench)}</b> · ${ex.probes} 题/种子
      · ${(ex.types||[]).join(' / ')}</div>
    <div class="small">得分规则：<span class="mono">${esc(ex.score)}</span></div></div>`:'';
}

async function tick(){
  try{
    const s=await j('/api/status'),idx=await j('/api/eb'),r=await j('/api/research');
    if(r&&r.modules)drawResearch(r);
    const dot=document.getElementById('runDot');
    dot.className='dot '+(s.running?'on':s.finished?'done':'');
    document._best=s.best?s.best.id:null;
    document.getElementById('taskName').textContent=s.task||'';
    document.getElementById('stats').innerHTML=
      `<span>提交 <b>${s.commits}</b></span><span>计分 <b>${s.scored}</b></span>
       <span>失败 <b class="neg">${s.failed}</b></span>
       <span>最优 <b class="best">${s.best?fmt(s.best.score)+' ('+s.best.id+')':'—'}</b></span>
       <span>考题版本 ${s.eval_versions.join(',')}</span>
       <span>已运行 ${Math.round(s.elapsed)}s</span>`+
      (s.suspicious?`<span><span class="tag" style="color:var(--bad);border-color:var(--bad)">可疑:${s.suspicious}</span></span>`:'')+
      (s.error_kinds&&Object.keys(s.error_kinds).length?
        '<span>错误 '+Object.entries(s.error_kinds).map(([k,n])=>
          `<span class="tag" style="color:var(--bad);border-color:var(--bad)">${k}:${n}</span>`).join(' ')+'</span>':'')+
      (s.report&&s.report.llm_usage?
        `<span>llm ${s.report.llm_usage.calls} 次调用 / ${s.report.llm_usage.completion_tokens} tok</span>`:'');
    drawCurve('curve',idx,s);drawTree(idx);
    const tb=document.querySelector('#tbl tbody');tb.innerHTML=idx.map(e=>
      `<tr class="${e.id===sel?'sel':''}" onclick="pick('${e.id}')"><td class="mono">${e.id}</td>
      <td class="mono ${e.score==null?'neg':''}">${e.score==null?(e.error?'ERR':'—'):Number(e.score).toPrecision(6)}${e.cost_how==='suspicious'?' <span class="neg" title="成本记账可疑">⚠</span>':''}</td>
      <td><span class="tag" style="color:${col(e.direction)};border-color:${col(e.direction)}">${e.direction||'?'}</span></td>
      <td class="mono">${(e.parents||[]).join(',')}</td><td>${e.eval_version}</td>
      <td class="small" style="white-space:normal">${esc((e.feedback||e.error||'').slice(0,90))}</td></tr>`).join('');
    const lg=await j('/api/log?n=160');
    const lb=document.getElementById('log');
    const atEnd=lb.scrollTop+lb.clientHeight>=lb.scrollHeight-8;
    lb.textContent=lg.log;if(atEnd)lb.scrollTop=lb.scrollHeight;
  }catch(e){}
}
setInterval(tick,2000);tick();

/* 滚动时高亮当前导航锚点 + 回顶部 */
const secs=['sys','road','now','gap','rank','evi'];
addEventListener('scroll',()=>{
  document.getElementById('totop').style.display=scrollY>500?'block':'none';
  let cur='';
  secs.forEach(id=>{const e=document.getElementById('sec-'+id);
    if(e&&e.getBoundingClientRect().top<90)cur=id});
  document.querySelectorAll('.topnav a').forEach(a=>
    a.classList.toggle('on',a.getAttribute('href')==='#sec-'+cur));
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    work: Path = Path("run_out")

    def _send(self, body: bytes, ctype: str = "application/json",
              code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        path = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)
        if path in ("/", "/index.html"):
            self._send(INDEX_HTML.encode(), "text/html; charset=utf-8")
        elif path == "/api/status":
            self._json(build_status(self.work))
        elif path == "/api/eb":
            self._json(_enrich(
                _read_json(self.work / "eb" / "index.json", [])))
        elif path == "/api/research":
            self._json(_research(self.work))
        elif path.startswith("/api/solution/"):
            sid = path.rsplit("/", 1)[-1]
            if not sid.replace("_", "").replace("-", "").isalnum():
                return self._json({"error": "bad id"}, 400)
            sol = self.work / "eb" / "solutions" / sid
            meta = _read_json(sol / "meta.json", None)
            self._json({"id": sid, "meta": meta,
                        "fb": parse_feedback((meta or {}).get("feedback")),
                        "files": _solution_files(sol)})
        elif path == "/api/log":
            n = int(q.get("n", ["300"])[0])
            self._json({"log": _tail(self.work / "hyra.log", min(n, 2000))})
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):  # quieter access log
        log.debug("http: " + fmt, *args)


def serve(work_dir: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    work = Path(work_dir).resolve()
    (work / "eb" / "solutions").mkdir(parents=True, exist_ok=True)
    Handler.work = work
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.current_thread().name = "hyra-web"
    print(f"hyra dashboard → http://{host}:{port}  (work={work})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
