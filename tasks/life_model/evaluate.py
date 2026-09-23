#!/usr/bin/env python3
"""LifeStream lifecycle evaluator for the life_model task.

Driven-by-evaluator protocol (anti reward-hacking: truth never touches the
solution's filesystem):

    for each phase (streams split at CHECKPOINT days):
        for each record in the phase:  asset.ingest(record)
        for each probe due at the checkpoint:  asset.answer(probe)

The solution dir must contain `asset.py` exposing module-level:

    ingest(rec: dict) -> None
    answer(probe: dict) -> str
    stats() -> dict           # optional legacy; {"asset_bytes": int,
                              #            "probe_bytes": int (cumulative),
                              #            "llm_tokens": int}
    state() -> dict           # optional; serializable asset — MEASURED cost
    probe_bytes() -> int      # optional; cumulative consulted bytes

Cost is MEASURED, not self-reported (v1 fix: s0023 gamed stats()): when the
asset exposes state()/probe_bytes() the evaluator serializes them itself;
stats() values are only a fallback and are flagged as "reported".

solve.sh is a trivial no-op (`#!/bin/bash\nexit 0`) — the evaluator imports
asset.py itself and drives the whole lifecycle.

Scoring:
    quality = Σ per-probe score (1.0 hit / 0.5 partial / 0 miss /
              −0.5 stale-leak via must_not)
    cost    = asset_bytes_kb*0.001 + probe_bytes_kb*0.002 + llm_tokens*0.0001
    score   = quality − cost          (higher better)
    also runs the 3 baselines on the same stream for the feedback digest.

Usage: python3 evaluate.py <solution_dir>   → prints {"score", "feedback"}
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bench"))
from generator import CHECKPOINTS, generate  # noqa: E402

EVAL_SEED = 7
COST_ASSET = 0.002    # per KB of retained asset
COST_PROBE = 0.0002   # per KB consulted across all probes
COST_TOK = 0.0002     # per LLM token (0 for deterministic impls)


def norm(s: str) -> str:
    return "".join(unicodedata.normalize("NFKC", str(s)).split()).lower()


def score_probe(probe, answer):
    a = norm(answer)
    expect = probe["expect"]
    for bad in probe.get("must_not", []):
        if norm(bad) and norm(bad) in a:
            return -0.5
    if probe["type"] == "retract":
        # any acceptable "gone" phrasing scores
        opts = expect if isinstance(expect, list) else [expect]
        return 1.0 if any(norm(v) in a for v in opts) else 0.0
    if isinstance(expect, list):
        if not expect:
            return 0.0
        hits = sum(1 for v in expect if norm(v) in a)
        return hits / len(expect)
    return 1.0 if norm(expect) in a else 0.0


def measure_cost(asset, cum_probe_bytes_reported: int, answered: bool):
    """Measure cost honestly: state()/probe_bytes() beat stats() self-report.
    Returns (cost_dict, how: 'measured'|'reported')."""
    how = "reported"
    st = asset.stats() if hasattr(asset, "stats") else {}
    try:
        asset_bytes = int(st.get("asset_bytes", 0))
    except Exception:
        asset_bytes = 0
    probe_bytes = cum_probe_bytes_reported or int(st.get("probe_bytes", 0))
    llm = int(st.get("llm_tokens", 0))
    if hasattr(asset, "state"):
        try:
            asset_bytes = len(json.dumps(asset.state(), ensure_ascii=False))
            how = "measured"
        except Exception:
            pass
    if hasattr(asset, "probe_bytes"):
        try:
            probe_bytes = int(asset.probe_bytes())
            how = "measured"
        except Exception:
            pass
    if answered and probe_bytes <= 0:
        # answered something yet claims zero retrieval cost — flag it
        how = "suspicious"
    return {"asset_bytes": asset_bytes, "probe_bytes": probe_bytes,
            "llm_tokens": llm}, how


def drive(asset, records, probes):
    """Run the lifecycle; return per-probe rows + cost + honesty flag."""
    by_ckpt = {}
    for p in probes:
        by_ckpt.setdefault(p["ckpt"], []).append(p)
    rows, cum_reported, answered = [], 0, False
    for ckpt in CHECKPOINTS:
        for r in [x for x in records if x["day"] <= ckpt
                  and not x.get("_fed")]:
            asset.ingest(r)
            r["_fed"] = True
        for p in by_ckpt.get(ckpt, []):
            ans = asset.answer(p)
            if str(ans).strip() not in ("", "未知"):
                answered = True
            st = asset.stats() if hasattr(asset, "stats") else {}
            if not hasattr(asset, "probe_bytes"):
                cum_reported += int(st.get("probe_bytes", 0))
            rows.append({"probe": p, "answer": str(ans),
                         "score": score_probe(p, ans)})
    cost, how = measure_cost(asset, cum_reported, answered)
    return rows, cost, how


def load_asset(sol: Path):
    f = sol / "asset.py"
    if not f.exists():
        return None
    spec = importlib.util.spec_from_file_location("lm_asset", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ----------------- baselines (same stream, same probes) -----------------
class RawBaseline:
    """All records kept; answer = most recent self record for the slot."""
    def __init__(self):
        self.recs = []

    def ingest(self, r):
        self.recs.append(r)

    def answer(self, p):
        hits = [r for r in self.recs if r["slot"] == p["slot"]
                and r["source"] == "self" and r["kind"] != "retraction"]
        if p["type"] == "prov":
            said = any(r["source"] == "self" and r["value"] == p.get("value")
                       for r in hits)
            return "本人" if said else "非本人"
        return hits[-1]["value"] if hits else "未知"

    def stats(self):
        return {"asset_bytes": len(json.dumps(self.recs)),
                "probe_bytes": len(json.dumps(self.recs)), "llm_tokens": 0}


class LedgerBaseline:
    """Last-write-wins per slot from self records; no provenance control."""
    def __init__(self):
        self.m = {}

    def ingest(self, r):
        if r["source"] == "self":
            if r["kind"] == "retraction":
                self.m.pop(r["slot"], None)
            elif "expires_day" not in r or True:
                self.m[r["slot"]] = (r["value"], r.get("expires_day"))

    def answer(self, p):
        if p["type"] == "prov":
            v = self.m.get(p["slot"])
            return "本人" if v and v[0] == p.get("value") else "非本人"
        v = self.m.get(p["slot"])
        return v[0] if v else "未知"

    def stats(self):
        return {"asset_bytes": len(json.dumps(self.m)),
                "probe_bytes": len(json.dumps(self.m)), "llm_tokens": 0}


class RAGBaseline:
    """Keyword retrieval over raw records; answer from top hit."""
    def __init__(self):
        self.recs = []

    def ingest(self, r):
        self.recs.append(r)

    def answer(self, p):
        hits = [r for r in self.recs if p["slot"] in r["text"]
                or r["slot"] == p["slot"]]
        if not hits:
            return "未知"
        if p["type"] == "prov":
            said = any(r["source"] == "self" and r["value"] == p.get("value")
                       for r in hits)
            return "本人" if said else "非本人"
        return hits[-1]["value"]

    def stats(self):
        return {"asset_bytes": len(json.dumps(self.recs)),
                "probe_bytes": 5000, "llm_tokens": 0}


def quality_breakdown(rows):
    agg = {}
    for r in rows:
        agg.setdefault(r["probe"]["type"], []).append(r["score"])
    return {k: round(sum(v) / len(v), 3) for k, v in agg.items()}


def main():
    sol = Path(sys.argv[1])
    records, probes, truth, meta = generate(EVAL_SEED)
    # fresh copies per driver so _fed flags don't leak
    import copy

    asset = load_asset(sol)
    if asset is None or not hasattr(asset, "ingest"):
        print(json.dumps({"score": -1e9,
                          "feedback": "no asset.py with ingest()/answer()"}))
        return

    recs = copy.deepcopy(records)
    try:
        rows, cost, how = drive(asset, recs, probes)
    except Exception as e:
        print(json.dumps({"score": -1e9,
                          "feedback": f"asset raised: {e!r}"}))
        return

    quality = sum(r["score"] for r in rows)
    cost_pen = (cost["asset_bytes"] / 1024 * COST_ASSET +
                cost["probe_bytes"] / 1024 * COST_PROBE +
                cost["llm_tokens"] * COST_TOK)
    score = round(quality - cost_pen, 4)

    # baselines for the feedback digest
    bl = {}
    for name, cls in [("raw", RawBaseline), ("ledger", LedgerBaseline),
                      ("rag", RAGBaseline)]:
        rr = copy.deepcopy(records)
        try:
            rws, _c, _h = drive(cls(), rr, probes)
            bl[name] = round(sum(r["score"] for r in rws), 3)
        except Exception as e:
            bl[name] = f"err:{e!r}"

    fb = (f"quality={quality:.2f} cost={cost} cost_how={how}"
          f" breakdown={quality_breakdown(rows)}"
          f" baselines={bl} meta={meta}")
    print(json.dumps({"score": score, "feedback": fb}))


if __name__ == "__main__":
    main()
