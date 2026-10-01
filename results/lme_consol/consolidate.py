#!/usr/bin/env python3
"""Offline per-vertex edge consolidation of cached new-ingest models.

For each cached model export, ask Atria to merge same-fact/overlapping
edges inside each vertex (target: old-stack ~55-rec density, no info
loss), then write a drop-in model cache for the lme_variants harness.
"""
import asyncio
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "tasks", "life_model", "external")))
from lifemodel import reader  # noqa: E402
from hyra.llm import OpenAICompatLLM  # noqa: E402

SRC = "results/lme_catfix/models"
DST = "results/lme_consol/models"
os.makedirs(DST, exist_ok=True)

_llm = OpenAICompatLLM(
    model=os.environ.get("OPENAI_MODEL", "Atria-Dawn-Preview"),
    base_url=os.environ.get("OPENAI_BASE_URL",
                            "https://api.atria-asi.ai/v1"),
    api_key=os.environ.get("OPENAI_API_KEY") or
    os.environ.get("ATRIA_API_KEY", ""),
    max_tokens=16384)

_KINDS = ("statement", "suggestion", "update", "question",
          "contradiction", "plan")

SYS = ("You are a memory-store consolidator. Precise JSON output only.")

PROMPT = """You consolidate a fragmented memory store. Each VERTEX below is a memory slot with dated edges; many edges restate the same or overlapping fact.

For EACH vertex, merge edges describing the same fact/topic into as few records as possible WITHOUT losing distinct information:
- keep every DISTINCT value, item, amount, date or status change (never drop a fact that only appears once)
- an updated/superseded value may collapse to the newest phrasing + newest date
- keep each record's date = the date the fact was (last) true
- keep "kind" from the source edges; assistant-advice vertices keep kind "suggestion"; user facts keep "statement"

Return ONLY JSON: {"<vertex key>": [{"val": "...", "date": "YYYY-MM-DD", "kind": "statement"}...]}
Every vertex key must be present exactly once. No extra keys, no prose.

VERTICES:
@@LISTING@@"""


def _iso(ordinal):
    return _dt.date.fromordinal(int(ordinal)).isoformat()


def _listing(hist):
    lines = []
    for k, edges in hist.items():
        lines.append(f"- {k} ({reader._label(k)}):")
        for i, e in enumerate(edges, 1):
            tag = "" if e[2] in ("statement",) else f"[{e[2]}]"
            lines.append(f"  #{i} {e[0]} @{_iso(e[1])}{tag}")
    return "\n".join(lines)


def _parse_obj(text):
    t = text.strip()
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            v = json.loads(t[i:j + 1])
            return v if isinstance(v, dict) else None
        except Exception:
            return None
    return None


async def _consolidate(hist):
    prompt = PROMPT.replace("@@LISTING@@", _listing(hist))
    for _try in range(3):
        t = await _llm.complete(SYS, prompt)
        obj = _parse_obj(t)
        if obj and set(obj) == set(hist):
            out, ok = {}, True
            for k, recs in obj.items():
                if not isinstance(recs, list) or not recs:
                    ok = False
                    break
                edges = []
                for r in recs:
                    try:
                        day = _dt.date.fromisoformat(
                            str(r["date"])[:10]).toordinal()
                        edges.append([str(r["val"]), day,
                                      r.get("kind") if r.get("kind") in
                                      _KINDS else "statement"])
                    except Exception:
                        ok = False
                        break
                if not ok:
                    break
                out[k] = edges
            if ok:
                return out, t
    return None, None


_sem = asyncio.Semaphore(4)


async def _one(f):
    async with _sem:
        packed = json.load(open(os.path.join(SRC, f)))
        exported = packed["export"]
        hist = exported["asset"]["hist"]
        before = sum(len(v) for v in hist.values())
        dst = os.path.join(DST, f)
        if os.path.exists(dst):
            after = sum(len(v) for v in json.load(open(dst))["export"]
                        ["asset"]["hist"].values())
            return (f, before, after, "cached"), []
        merged, raw = await _consolidate(hist)
        tag = "ok" if merged is not None else "FALLBACK"
        if merged is None:
            merged = hist
        after = sum(len(v) for v in merged.values())
        exported["asset"]["hist"] = merged
        json.dump({"n_records": after, "export": exported},
                  open(dst, "w"), ensure_ascii=False)
        ex = []
        for k in merged:
            if len(hist[k]) >= 3 and len(merged[k]) < len(hist[k]):
                ex.append((f, k, hist[k], merged[k]))
        print(f"{f} {before}->{after} {tag}", flush=True)
        return (f, before, after, tag), ex


async def main():
    stats, examples = [], []
    tasks = [_one(f) for f in sorted(os.listdir(SRC))
             if f.endswith(".json")]
    for st, ex in await asyncio.gather(*tasks):
        stats.append(st)
        examples.extend(ex)
    with open("results/lme_consol/consol_stats.json", "w") as fh:
        json.dump({"per_model": stats,
                   "examples": examples[:8]}, fh, ensure_ascii=False,
                  indent=1)
    med_b = sorted(s[1] for s in stats)[len(stats) // 2]
    med_a = sorted(s[2] for s in stats)[len(stats) // 2]
    print(f"models={len(stats)} median recs {med_b} -> {med_a}")
    for f, b, a, tag in stats:
        print(f"  {f[:-5]} {b}->{a} {tag}")


if __name__ == "__main__":
    asyncio.run(main())
