"""hyra serve: zero-dependency web dashboard over a --work directory.

    hyra serve --work run_out --port 8000

Reads the Experience Bank (eb/index.json + eb/solutions/*), report.json and
hyra.log live from disk, so it works both while a run is in progress and
afterwards. Single-file frontend, no external assets.
"""
from __future__ import annotations

import json
import logging
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


def build_status(work: Path) -> dict:
    idx = _read_json(work / "eb" / "index.json", [])
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
    }


INDEX_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Hyra — Experience Bank</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;
--acc:#58a6ff;--good:#3fb950;--bad:#f85149;--warn:#d29922}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,
Roboto,"Helvetica Neue",monospace-ui,sans-serif;padding:14px}
h1{font-size:17px;display:flex;align-items:center;gap:10px;margin-bottom:12px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--dim);display:inline-block}
.dot.on{background:var(--good);box-shadow:0 0 8px var(--good)}
.dot.done{background:var(--acc)}
.stats{display:flex;gap:18px;flex-wrap:wrap;color:var(--dim);margin:6px 0 14px;
font-size:13px}
.stats b{color:var(--fg);font-weight:600}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:12px;min-width:0}
.panel h2{font-size:12px;color:var(--dim);text-transform:uppercase;
letter-spacing:.06em;margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:var(--dim);text-align:left;font-weight:500;padding:4px 6px;
border-bottom:1px solid var(--line)}
td{padding:4px 6px;border-bottom:1px solid #21262d;white-space:nowrap;
max-width:340px;overflow:hidden;text-overflow:ellipsis}
tr.sel td{background:#1f2a3a}
tr:hover td{background:#1b2330;cursor:pointer}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.tag{display:inline-block;padding:0 6px;border-radius:10px;font-size:11px;
border:1px solid var(--line);color:var(--dim)}
svg{display:block;width:100%}
pre{background:#0a0d12;border:1px solid var(--line);border-radius:6px;
padding:10px;overflow:auto;max-height:300px;font-size:12px;white-space:pre}
.files{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.fbtn{background:#21262d;border:1px solid var(--line);border-radius:6px;
padding:2px 9px;font-size:12px;cursor:pointer;color:var(--fg)}
.fbtn.on{border-color:var(--acc);color:var(--acc)}
.best{color:var(--good);font-weight:600}
.neg{color:var(--bad)}
.logbox{max-height:220px}
.node{cursor:pointer}
.node text{font-size:9px;fill:var(--dim)}
.small{font-size:12px;color:var(--dim)}
#detail{display:none;margin-top:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<h1><span class="dot" id="runDot"></span> Hyra — Experience Bank
 <span class="small" id="taskName"></span></h1>
<div class="stats" id="stats"></div>
<div class="grid">
  <div class="panel"><h2>Score 进化曲线</h2><svg id="curve" height="240"></svg>
    <div class="small" id="legend"></div></div>
  <div class="panel"><h2>解谱系（点击节点查看解）</h2><svg id="tree" height="240"></svg></div>
</div>
<div id="detail" class="panel">
  <h2 id="detTitle">Solution</h2>
  <div class="files" id="detFiles"></div>
  <pre class="mono" id="detBody"></pre>
</div>
<div class="grid" style="margin-top:14px">
  <div class="panel"><h2>Experience Bank 明细</h2>
    <div style="max-height:320px;overflow:auto"><table id="tbl">
      <thead><tr><th>id</th><th>score</th><th>dir</th><th>parents</th>
      <th>eval_v</th><th>feedback / error</th></tr></thead><tbody></tbody></table>
    </div></div>
  <div class="panel"><h2>Harness 日志</h2>
    <pre class="mono logbox" id="log">loading…</pre></div>
</div>
<script>
const DC={seed:'#8b949e',exploit:'#58a6ff',explore:'#3fb950',fresh:'#bc8cff',
repair:'#e08a00',hybrid:'#39c5cf',err:'#f85149'};
let sel=null;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=v=>v==null?'—':(typeof v==='number'?v.toPrecision(6):v);
const col=d=>DC[d]||'#8b949e';

async function j(u){const r=await fetch(u);return r.json()}

function drawCurve(svg,idx){
  const el=document.getElementById(svg);el.innerHTML='';
  const W=el.clientWidth||560,H=240,P=26;
  el.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const pts=idx.filter(e=>e.score!=null);
  if(!pts.length){el.innerHTML='<text x="20" y="120" fill="#8b949e">no scored solutions yet</text>';return}
  const ys=pts.map(e=>e.score),lo=Math.min(...ys),hi=Math.max(...ys);
  const y=v=>H-P-(v-lo)/((hi-lo)||1)*(H-2*P);
  const x=i=>P+i/Math.max(idx.length-1,1)*(W-2*P);
  let g='';
  [lo,hi].forEach(v=>{g+=`<line x1="${P}" x2="${W-P}" y1="${y(v)}" y2="${y(v)}"
    stroke="#30363d" stroke-dasharray="3"/><text x="2" y="${y(v)+4}"
    fill="#8b949e" font-size="9">${v.toPrecision(4)}</text>`});
  let best=-1e18,bpath='';
  idx.forEach((e,i)=>{if(e.score!=null&&e.score>best){best=e.score;
    bpath+=`${i?'L':'M'}${x(i)},${y(best)} `}});
  g+=`<path d="${bpath}" fill="none" stroke="#3fb950" stroke-width="1.2"
    stroke-dasharray="4 3" opacity=".7"/>`;
  g+='<path d="'+idx.map((e,i)=>e.score==null?'':
    `${i?'L':'M'}${x(i)},${y(e.score)}`).filter(s=>s).join(' ')+
    '" fill="none" stroke="#58a6ff" stroke-width="1.4" opacity=".85"/>';
  idx.forEach((e,i)=>{if(e.score==null)return;
    g+=`<circle class="node" data-sid="${e.id}" cx="${x(i)}" cy="${y(e.score)}"
      r="4.5" fill="${col(e.direction)}"><title>${e.id} ${e.score}</title></circle>`});
  el.innerHTML=g;
  el.querySelectorAll('.node').forEach(n=>n.onclick=()=>pick(n.dataset.sid));
  document.getElementById('legend').innerHTML=
    Object.keys(DC).map(k=>`<span class="tag" style="border-color:${col(k)};color:${col(k)}">${k}</span>`).join(' ');
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
    return n===1?H/2:30+ord[id]/(n-1)*(H-60)};
  let g='';
  idx.forEach(e=>(e.parents||[]).forEach(p=>{if(dep[p]==null)return;
    g+=`<line x1="${px(p)}" y1="${py(p)}" x2="${px(e.id)}" y2="${py(e.id)}"
      stroke="#30363d" stroke-width="1"/>`}));
  const best=document._best;
  idx.forEach(e=>{const r=e.id===best?7:5;
    g+=`<g class="node" data-sid="${e.id}"><circle cx="${px(e.id)}" cy="${py(e.id)}"
      r="${r}" fill="${e.score==null?DC.err:col(e.direction)}"
      ${e.id===best?'stroke="#3fb950" stroke-width="2"':''}></circle>
      <text x="${px(e.id)+8}" y="${py(e.id)+3}">${e.id}</text></g>`});
  el.setAttribute('viewBox',`0 0 ${W} ${H}`);el.innerHTML=g;
  el.querySelectorAll('.node').forEach(n=>n.onclick=()=>pick(n.dataset.sid));
}

async function pick(sid){
  sel=sid;
  const d=await j('/api/solution/'+sid);
  document.getElementById('detail').style.display='block';
  document.getElementById('detTitle').textContent=
    `Solution ${sid}  ·  score=${fmt(d.meta&&d.meta.score)}  ·  ${d.meta?d.meta.direction:''}`;
  const fs=document.getElementById('detFiles');fs.innerHTML='';
  const names=Object.keys(d.files);
  names.forEach(n=>{const b=document.createElement('button');
    b.className='fbtn';b.textContent=n;
    b.onclick=()=>{fs.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('on'));
      b.classList.add('on');document.getElementById('detBody').textContent=d.files[n]};
    fs.appendChild(b)});
  if(names.length)fs.children[0].click();
  else document.getElementById('detBody').textContent='(no readable files)';
}

async function tick(){
  try{
    const s=await j('/api/status'),idx=await j('/api/eb');
    const dot=document.getElementById('runDot');
    dot.className='dot '+(s.running?'on':s.finished?'done':'');
    document._best=s.best?s.best.id:null;
    document.getElementById('stats').innerHTML=
      `<span>commits <b>${s.commits}</b></span><span>scored <b>${s.scored}</b></span>
       <span>failed <b class="neg">${s.failed}</b></span>
       <span>best <b class="best">${s.best?fmt(s.best.score)+' ('+s.best.id+')':'—'}</b></span>
       <span>eval_v ${s.eval_versions.join(',')}</span>
       <span>elapsed ${Math.round(s.elapsed)}s</span>`+
      (s.report&&s.report.llm_usage?
        `<span>llm ${s.report.llm_usage.calls} calls / ${s.report.llm_usage.completion_tokens} tok</span>`:'');
    drawCurve('curve',idx);drawTree(idx);
    const tb=document.querySelector('#tbl tbody');tb.innerHTML=idx.map(e=>
      `<tr class="${e.id===sel?'sel':''}" onclick="pick('${e.id}')"><td class="mono">${e.id}</td>
      <td class="mono ${e.score==null?'neg':''}">${e.score==null?(e.error?'ERR':'—'):Number(e.score).toPrecision(6)}</td>
      <td><span class="tag" style="color:${col(e.direction)};border-color:${col(e.direction)}">${e.direction||'?'}</span></td>
      <td class="mono">${(e.parents||[]).join(',')}</td><td>${e.eval_version}</td>
      <td class="small">${esc((e.feedback||e.error||'').slice(0,90))}</td></tr>`).join('');
    const lg=await j('/api/log?n=160');
    const lb=document.getElementById('log');
    const atEnd=lb.scrollTop+lb.clientHeight>=lb.scrollHeight-8;
    lb.textContent=lg.log;if(atEnd)lb.scrollTop=lb.scrollHeight;
  }catch(e){}
}
setInterval(tick,2000);tick();
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
            self._json(_read_json(self.work / "eb" / "index.json", []))
        elif path.startswith("/api/solution/"):
            sid = path.rsplit("/", 1)[-1]
            if not sid.replace("_", "").replace("-", "").isalnum():
                return self._json({"error": "bad id"}, 400)
            sol = self.work / "eb" / "solutions" / sid
            meta = _read_json(sol / "meta.json", None)
            self._json({"id": sid, "meta": meta,
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
