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
    forget(scope: dict)       # optional; user-control op — evaluator calls
                              #   forget({"slot": s}) once at a ckpt boundary;
                              #   missing it loses cascade-probe points
    stats() -> dict           # optional legacy; {"asset_bytes": int,
                              #            "probe_bytes": int (cumulative),
                              #            "llm_tokens": int}
    state() -> dict           # optional; serializable asset — MEASURED cost
    probe_bytes() -> int      # optional; cumulative consulted bytes

Probe types (v3): state | stale | prov | retract | transfer — plus
    as_of:   probe["day"]=D → value live at day D (history required)
    subject: probe["person"]=P → hearsay value attributed to P (self-state
             must NOT be polluted by it)
    cascade: fired after the evaluator's forget() call — every asserted
             value of the forgotten slot must be gone (state AND
             history, including DERIVED facts it supported)
    derive:  premise superseded (correction) → derived value must be gone
             (revision semantics; the gone-phrasing branch like cascade)
    derived records: kind="derived", source="inference", supports=[rec_ids]
             — live state probes expect them while premises hold
    export-import: after meta["export_day"] ckpt probes the evaluator does
             state() -> json -> import_state(); probes flagged
             post_import score 0 if the round-trip is missing/failed
             (asset must expose import_state(d) to earn them)

Cost is MEASURED, not self-reported (v1 fix: s0023 gamed stats()): when the
asset exposes state()/probe_bytes() the evaluator serializes them itself;
stats() values are only a fallback and are flagged as "reported".

solve.sh is a trivial no-op (`#!/bin/bash\nexit 0`) — the evaluator imports
asset.py itself and drives the whole lifecycle.

Scoring:
    quality = Σ per-probe score (1.0 hit / 0.5 partial / 0 miss /
              −0.5 stale-leak via must_not)
    cost    = asset_bytes_kb*0.002 + probe_bytes_kb*0.0002 + llm_tokens*0.0002
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
    if probe["type"] in ("retract", "cascade", "derive"):
        # any acceptable "gone" phrasing scores
        opts = expect if isinstance(expect, list) else [expect]
        return 1.0 if any(norm(v) in a for v in opts) else 0.0
    if probe["type"] == "budget":
        # only the first `budget` bytes of the answer count — ordering
        # under budget is the decision being scored
        a = norm(str(answer).encode()[:probe.get("budget", 10**9)]
                 .decode(errors="ignore"))
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


def drive(asset, records, probes, meta=None):
    """Run the lifecycle; return per-probe rows + cost + honesty flag.

    meta["forget"] = {"slot", "day"}: user-control event — after the last
    ckpt < day the evaluator calls asset.forget({"slot": slot}) (if the
    asset exposes it). Cascade probes afterwards score deletion depth.
    """
    by_ckpt = {}
    for p in probes:
        by_ckpt.setdefault(p["ckpt"], []).append(p)
    forget = (meta or {}).get("forget")
    correct = (meta or {}).get("correct")
    revoke = (meta or {}).get("revoke")
    export_day = (meta or {}).get("export_day")
    forget_fired = False
    correct_fired = False
    revoke_fired = False
    import_ok = None
    rows, cum_reported, answered = [], 0, False
    for i, ckpt in enumerate(CHECKPOINTS):
        for r in [x for x in records if x["day"] <= ckpt
                  and not x.get("_fed")]:
            asset.ingest(r)
            r["_fed"] = True
        for p in by_ckpt.get(ckpt, []):
            if p.get("post_import") and import_ok is False:
                ans = ""   # no working export->import: continuity lost
            else:
                ans = asset.answer(p)
            if str(ans).strip() not in ("", "未知"):
                answered = True
            st = asset.stats() if hasattr(asset, "stats") else {}
            if not hasattr(asset, "probe_bytes"):
                cum_reported += int(st.get("probe_bytes", 0))
            rows.append({"probe": p, "answer": str(ans),
                         "score": score_probe(p, ans)})
        next_ckpt = CHECKPOINTS[i + 1] if i + 1 < len(CHECKPOINTS) else 10**9
        if (forget and not forget_fired
                and ckpt < forget["day"] <= next_ckpt):
            if hasattr(asset, "forget"):
                try:
                    asset.forget({"slot": forget["slot"]})
                except Exception:
                    pass
            forget_fired = True
        if (correct and not correct_fired
                and ckpt < correct["day"] <= next_ckpt):
            # user-control write — assets lacking correct() lose the
            # probes expecting the corrected value, honestly
            if hasattr(asset, "correct"):
                try:
                    asset.correct(correct["slot"], correct["value"])
                except Exception:
                    pass
            correct_fired = True
        if (revoke and not revoke_fired
                and ckpt < revoke["day"] <= next_ckpt):
            # consent withdrawal — assets lacking revoke_purpose keep
            # serving the view and eat the must_not leak, honestly
            if hasattr(asset, "revoke_purpose"):
                try:
                    asset.revoke_purpose(revoke["purpose"])
                except Exception:
                    pass
            revoke_fired = True
        if export_day is not None and ckpt == export_day:
            # export -> import round-trip: state() snapshot serialized to
            # JSON and loaded into the same asset — then the remaining
            # stream keeps feeding it. Assets without import_state (or a
            # throwing one) forfeit every post_import probe.
            st_fn = getattr(asset, "state", None)
            im_fn = getattr(asset, "import_state", None)
            import_ok = False
            if callable(st_fn) and callable(im_fn):
                try:
                    snap = json.loads(json.dumps(st_fn(),
                                                 ensure_ascii=False))
                    im_fn(snap)
                    import_ok = True
                except Exception:
                    import_ok = False
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
def _replay(recs, day):
    """Replay day-ordered records to reconstruct self-state at `day`.
    LWW + retraction + expiry — the honest floor for as_of probes."""
    st, exp = {}, {}
    for r in recs:
        if r["day"] > day:
            break
        if (r["source"] == "self"
                and r["kind"] in ("statement", "update", "correction")):
            st[r["slot"]] = r["value"]
            if r.get("expires_day"):
                exp[r["slot"]] = r["expires_day"]
        elif r["kind"] == "retraction":
            st.pop(r["slot"], None)
            exp.pop(r["slot"], None)
    for s, d in list(exp.items()):
        if day > d:
            st.pop(s, None)
    return st


class RawBaseline:
    """All records kept; answer = most recent self record for the slot."""
    def __init__(self):
        self.recs = []

    def ingest(self, r):
        self.recs.append(r)

    def forget(self, scope):
        slot = scope.get("slot")
        self.recs = [r for r in self.recs if r["slot"] != slot]

    def state(self):
        return {"recs": self.recs}

    def import_state(self, d):
        self.recs = list(d["recs"])

    def answer(self, p):
        if p["type"] == "as_of":
            v = _replay(self.recs, p.get("day", 10**9)).get(p["slot"])
            return v if v is not None else "未知"
        if p["type"] == "subject":
            hits = [r for r in self.recs if r["kind"] == "hearsay"
                    and r["source"] == p.get("person")
                    and r["slot"] == p["slot"]
                    and r["day"] <= p.get("ckpt", 10**9)]
            return hits[-1]["value"] if hits else "未知"
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
    """Last-write-wins per slot from self records; no provenance control,
    no history (as_of honestly fails), no hearsay tracking (subject
    fails), no derived tracking (state/derive probes on them fail)."""
    def __init__(self):
        self.m = {}

    def ingest(self, r):
        if r["source"] == "self":
            if r["kind"] == "retraction":
                self.m.pop(r["slot"], None)
            elif "expires_day" not in r or True:
                self.m[r["slot"]] = (r["value"], r.get("expires_day"))

    def forget(self, scope):
        self.m.pop(scope.get("slot"), None)

    def state(self):
        return {"m": self.m}

    def import_state(self, d):
        self.m = {k: tuple(v) if isinstance(v, list) else v
                  for k, v in d["m"].items()}

    def answer(self, p):
        if p["type"] == "subject":
            return "未知"
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

    def forget(self, scope):
        slot = scope.get("slot")
        self.recs = [r for r in self.recs if r["slot"] != slot]

    def state(self):
        return {"recs": self.recs}

    def import_state(self, d):
        self.recs = list(d["recs"])

    def answer(self, p):
        hits = [r for r in self.recs if p["slot"] in r["text"]
                or r["slot"] == p["slot"]]
        if not hits:
            return "未知"
        if p["type"] == "as_of":
            v = _replay(hits, p.get("day", 10**9)).get(p["slot"])
            return v if v is not None else "未知"
        if p["type"] == "subject":
            hh = [r for r in hits if r["kind"] == "hearsay"
                  and r["source"] == p.get("person")
                  and r["day"] <= p.get("ckpt", 10**9)]
            return hh[-1]["value"] if hh else "未知"
        if p["type"] == "prov":
            said = any(r["source"] == "self" and r["value"] == p.get("value")
                       for r in hits)
            return "本人" if said else "非本人"
        return hits[-1]["value"]

    def stats(self):
        return {"asset_bytes": len(json.dumps(self.recs)),
                "probe_bytes": 5000, "llm_tokens": 0}


class FlatServeBaseline:
    """M4 deficient family: flat LWW store + naive whole-dump serve.
    No probe-type routing: purpose/budget leak everything, no
    provenance/history/derivations/rids (as_of, subject, prov2,
    cascade beyond the forgotten slot honestly fail)."""
    def __init__(self):
        self.m = {}
        self.b = 0

    def ingest(self, r):
        if r["source"] == "self" and r["kind"] != "retraction":
            self.m[r["slot"]] = r["value"]
        elif r["source"] == "self" and r["kind"] == "retraction":
            self.m.pop(r["slot"], None)

    def forget(self, scope):
        self.m.pop(scope.get("slot"), None)

    def state(self):
        return {"m": self.m}

    def import_state(self, d):
        self.m = dict(d["m"])

    def probe_bytes(self):
        return self.b

    def answer(self, p):
        # serves the whole flat map for anything that isn't a state probe —
        # the "everything is one context" serve strategy
        self.b += len(json.dumps(self.m, ensure_ascii=False))
        if p["type"] == "prov2":
            return "未知"
        if p["type"] in ("state", "stale", "as_of", "unans"):
            return self.m.get(p["slot"], "未知")
        if p["type"] == "subject":
            return "未知"
        return ",".join(str(v) for v in self.m.values()) or "未知"


# ---- M3 family baselines (hand-built for the family race; see
# docs/literature/m3_update.md) ----

class _Mixin:
    """Shared read-side semantics + metering for the M3 baselines."""
    SELF = "self"
    WRITES = {"statement", "update", "correction"}
    AUTH = WRITES | {"retraction"}

    def _meter(self, obj):
        self._pb += len(json.dumps(obj, ensure_ascii=False))

    def probe_bytes(self):
        return self._pb

    def _premises_of(self, r):
        """supports=[rec_ids] -> {slot: premised_value}; None on dangling."""
        out = {}
        for rid in r.get("supports") or []:
            if rid not in self._rec_slot_val:
                return None
            s, v = self._rec_slot_val[rid]
            out[s] = v
        return out

    @staticmethod
    def _pval(cur, slot):
        v = cur.get(slot)
        return v[0] if isinstance(v, tuple) else v

    def _prune(self, cur, drv, exp=None, now=10**9):
        """Kill drv entries whose premise is absent/diverged/expired."""
        exp = exp or {}
        moved = True
        while moved:
            moved = False
            for s, d in list(drv.items()):
                if any((ps in exp and now > exp[ps])
                       or self._pval(cur, ps) != pv
                       for ps, pv in d["premises"].items()):
                    del drv[s]
                    cur.pop(s, None)
                    moved = True

    def _answer_state(self, cur, p):
        v = cur.get(p["slot"])
        if v is None:
            return "已删除" if p["type"] in ("retract", "cascade",
                                            "derive") else "未知"
        return v[0] if isinstance(v, tuple) else v


class TMSBaseline(_Mixin):
    """Truth-maintenance: derived entries carry premises resolved from
    supports ids; every write event eagerly cascade-invalidates dependents
    (transitive). Reads answer from the maintained live state — the
    premise index is the asset, replay is only needed for as_of."""
    def __init__(self):
        self._pb = 0
        self.hist = {}            # "source|slot" -> [[value, day, kind, exp]]
        self.prov = {}
        self._rec_slot_val = {}   # rec id -> (slot, value)
        self.cur = {}             # slot -> (value, prov-kind)
        self.drv = {}             # dslot -> {"premises": {slot: val}}
        self._exp = {}            # slot -> expires_day (slot-scoped lease)
        self._now = 0             # latest ingested day (read-day clock)
        self._latest_rid = {}     # slot -> latest self-write record id
        self._wday = {}           # slot -> day of cur's write (OOO-safe)
        self.alias = {}           # alias -> canonical person (M1)
        self.revoked = set()      # purposes whose use is withdrawn (M5)

    def revoke_purpose(self, purpose):
        self.revoked.add(purpose)

    def _forms(self, person):
        forms = {person}
        for a, c in self.alias.items():
            if c == person:
                forms.add(a)
            elif a == person:
                forms.add(c)
        return forms

    def ingest(self, r):
        self._now = max(self._now, r["day"])
        if r["kind"] == "alias":
            self.alias[r["slot"]] = r["value"]
            return
        if r.get("id"):
            self._rec_slot_val[r["id"]] = (r["slot"], r["value"])
        self.hist.setdefault(f'{r["source"]}|{r["slot"]}', []).append(
            [r["value"], r["day"], r["kind"], r.get("expires_day")])
        if r["kind"] == "derived":
            pre = self._premises_of(r)
            if pre is not None:
                self.drv[r["slot"]] = {"premises": pre}
                self.cur[r["slot"]] = (r["value"], "inference")
        elif r["source"] == self.SELF and r["kind"] in self.WRITES:
            # day is authoritative, not arrival order
            if r["day"] >= self._wday.get(r["slot"], -1):
                self._wday[r["slot"]] = r["day"]
                self.cur[r["slot"]] = (r["value"], "self")
                if r.get("id"):
                    self._latest_rid[r["slot"]] = r["id"]
            vals = self.prov.setdefault(r["slot"], [])
            if r["value"] not in vals:
                vals.append(r["value"])
            if r.get("expires_day"):
                self._exp[r["slot"]] = r["expires_day"]
        elif r["kind"] == "retraction" and r["source"] == self.SELF:
            self.cur.pop(r["slot"], None)
            self._wday.pop(r["slot"], None)
        # expiry is judged at read day — keep cur but pass exp+now into
        # the premise sweep so dependents of a lapsed slot die now
        self._prune(self.cur, self.drv, self._exp, self._now)

    def forget(self, scope):
        slot = scope.get("slot")
        for k in [k for k in self.hist if k.split("|", 1)[1] == slot]:
            del self.hist[k]
        self.prov.pop(slot, None)
        self.cur.pop(slot, None)
        self._exp.pop(slot, None)
        self._latest_rid.pop(slot, None)
        self._prune(self.cur, self.drv, self._exp, self._now)

    def correct(self, slot, value):
        self.ingest({"id": None, "day": self._now, "source": "self",
                     "kind": "correction", "slot": slot,
                     "value": value, "text": ""})

    def _live_at(self, source, slot, day):
        edges = self.hist.get(f"{source}|{slot}", [])
        cur, lease = None, None
        for e in edges:
            if e[1] <= day and (cur is None or e[1] >= cur[1]):
                cur = e
            if e[1] <= day and e[3] is not None:
                lease = e[3]   # slot-scoped lease: last declared <= day
        if source == self.SELF:
            edges = [e for e in edges if e[2] in self.AUTH]
            cur, lease = None, None
            for e in edges:
                if e[1] <= day and (cur is None or e[1] >= cur[1]):
                    cur = e
                if e[1] <= day and e[3] is not None:
                    lease = e[3]
            if lease is not None and day > lease:
                return None
        if cur is None or cur[2] == "retraction":
            return None
        if cur[3] is not None and day > cur[3]:
            return None
        return cur[0]

    def answer(self, p):
        t, slot = p["type"], p["slot"]
        ckpt = p.get("ckpt", 10**9)
        if t == "prov":
            vals = self.prov.get(slot, [])
            self._meter(vals)
            return "本人" if p.get("value") in vals else "非本人"
        if t == "subject":
            best, bd = None, -1
            seen = []
            for f in self._forms(p.get("person")):
                edges = self.hist.get(f'{f}|{slot}', [])
                seen += edges
                for e in edges:
                    if e[1] <= ckpt and e[2] != "retraction" \
                            and e[1] > bd:
                        best, bd = e[0], e[1]
            self._meter(seen)
            return best if best is not None else "未知"
        if t == "transfer":
            vals = [v[0] for s, v in self.cur.items()
                    if v[1] == "self"
                    and not (s in self._exp and ckpt > self._exp[s])]
            self._meter(vals)
            return ",".join(vals) if vals else "未知"
        if t in ("purpose", "revoked"):
            self._meter(sorted(self.revoked))
            if p.get("purpose") in self.revoked:
                return "已撤回"
            vals = [self._pval(self.cur, s)
                    for s in p.get("purpose_slots", [])
                    if s in self.cur
                    and not (s in self._exp and ckpt > self._exp[s])]
            self._meter(vals)
            return ",".join(str(v) for v in vals if v) or "未知"
        if t == "budget":
            vals = [self._pval(self.cur, s) for s in p.get("slots", [])
                    if s in self.cur
                    and not (s in self._exp and ckpt > self._exp[s])]
            self._meter(vals)
            return ",".join(str(v) for v in vals if v) or "未知"
        if t == "prov2":
            self._meter(self.cur.get(slot))
            return self._latest_rid.get(slot, "未知")
        if t == "as_of":
            edges = self.hist.get(f"self|{slot}", [])
            self._meter(edges)
            v = self._live_at(self.SELF, slot, p.get("day", ckpt))
            return v if v is not None else "未知"
        self._meter(self.cur.get(slot))
        if slot in self._exp and ckpt > self._exp[slot]:
            return "已删除" if t in ("retract", "cascade", "derive") \
                else "未知"   # slot lease lapsed at read day
        return self._answer_state(self.cur, p)

    def state(self):
        return {"hist": self.hist, "prov": self.prov,
                "drv": self.drv, "cur": self.cur,
                "exp": self._exp, "rsv": self._rec_slot_val,
                "lrid": self._latest_rid, "wday": self._wday,
                "alias": self.alias, "revoked": sorted(self.revoked)}

    def import_state(self, d):
        self.hist = {k: [list(e) for e in v] for k, v in d["hist"].items()}
        self.prov = {k: list(v) for k, v in d["prov"].items()}
        self.drv = {k: {"premises": dict(v["premises"])}
                    for k, v in d["drv"].items()}
        self.cur = {k: tuple(v) for k, v in d["cur"].items()}
        self._exp = dict(d["exp"])
        self._rec_slot_val = {k: tuple(v) for k, v in d["rsv"].items()}
        self._latest_rid = dict(d["lrid"])
        self._wday = dict(d["wday"])
        self.alias = dict(d["alias"])
        self.revoked = set(d.get("revoked", []))


class ESRBaseline(_Mixin):
    """Event-sourced re-derivation: raw event log only; every answer
    replays the whole stream and recomputes live state incl. derived
    validity. Correct by construction — pays replay bytes per probe."""
    def __init__(self):
        self._pb = 0
        self.recs = []
        self.revoked = set()

    def ingest(self, r):
        self.recs.append(r)

    def forget(self, scope):
        slot = scope.get("slot")
        self.recs = [r for r in self.recs if r["slot"] != slot]

    def correct(self, slot, value):
        self.recs.append({"id": None, "day": max(
            [r["day"] for r in self.recs] or [0]),
            "source": "self", "kind": "correction",
            "slot": slot, "value": value, "text": ""})

    def _replay(self, day):
        cur, drv, exp, lrid, alias = {}, {}, {}, {}, {}
        # day is authoritative — arrival order may shuffle within a
        # checkpoint window
        for r in sorted(self.recs, key=lambda x: x["day"]):
            if r["day"] > day:
                continue
            if r["kind"] == "alias":
                alias[r["slot"]] = r["value"]
                continue
            if r["kind"] == "derived":
                pre = self._premises_of(r)
                if pre is not None:
                    drv[r["slot"]] = {"premises": pre}
                    cur[r["slot"]] = (r["value"], "inference")
            elif r["source"] == "self" and r["kind"] in self.WRITES:
                cur[r["slot"]] = (r["value"], "self")
                if r.get("expires_day"):
                    exp[r["slot"]] = r["expires_day"]
                if r.get("id"):
                    lrid[r["slot"]] = r["id"]
            elif r["kind"] == "retraction":
                cur.pop(r["slot"], None)
            self._prune(cur, drv, exp, r["day"])
        for s, d in list(exp.items()):
            if day > d:
                cur.pop(s, None)
        self._prune(cur, drv, exp, day)
        return cur, lrid, alias

    def _premises_of(self, r):
        # returns None when a support is dangling (its record was forgotten
        # or never arrived): an unsupported derived is dead, not vacuous
        out = {}
        by_id = {x["id"]: x for x in self.recs if x.get("id")}
        for rid in r.get("supports") or []:
            if rid not in by_id:
                return None
            out[by_id[rid]["slot"]] = by_id[rid]["value"]
        return out

    def answer(self, p):
        self._meter(self.recs)   # honest: replay consults the whole log
        t, slot = p["type"], p["slot"]
        ckpt = p.get("ckpt", 10**9)
        if t == "prov":
            vals = [r["value"] for r in self.recs
                    if r["source"] == "self" and r["slot"] == slot
                    and r["kind"] in self.WRITES]
            return "本人" if p.get("value") in vals else "非本人"
        if t == "subject":
            _c, _l, alias = self._replay(ckpt)
            forms = {p.get("person")}
            for a, c in alias.items():
                if c == p.get("person"):
                    forms.add(a)
                elif a == p.get("person"):
                    forms.add(c)
            hits = [r for r in self.recs if r["kind"] == "hearsay"
                    and r["source"] in forms
                    and r["slot"] == slot and r["day"] <= ckpt]
            hits.sort(key=lambda x: x["day"])
            return hits[-1]["value"] if hits else "未知"
        if t == "as_of":
            cur_d, _lr, _a = self._replay(p.get("day", ckpt))
            v = cur_d.get(slot)
            return self._answer_state({slot: v} if v else {}, p)
        _c2, lrid, _a2 = self._replay(ckpt)
        cur = _c2
        if t == "transfer":
            vals = [v[0] for v in cur.values() if v[1] == "self"]
            return ",".join(vals) if vals else "未知"
        if t in ("purpose", "revoked"):
            if p.get("purpose") in self.revoked:
                return "已撤回"
            vals = [self._pval(cur, s) for s in p.get("purpose_slots", [])
                    if s in cur]
            return ",".join(str(v) for v in vals if v) or "未知"
        if t == "budget":
            vals = [self._pval(cur, s) for s in p.get("slots", [])
                    if s in cur]
            return ",".join(str(v) for v in vals if v) or "未知"
        if t == "prov2":
            return lrid.get(slot, "未知")
        return self._answer_state(cur, p)

    def revoke_purpose(self, purpose):
        self.revoked.add(purpose)

    def state(self):
        return {"recs": self.recs, "revoked": sorted(self.revoked)}

    def import_state(self, d):
        self.recs = list(d["recs"])
        self.revoked = set(d.get("revoked", []))


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
        rows, cost, how = drive(asset, recs, probes, meta)
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
                      ("rag", RAGBaseline), ("flat", FlatServeBaseline),
                      ("tms", TMSBaseline), ("esr", ESRBaseline)]:
        rr = copy.deepcopy(records)
        try:
            rws, _c, _h = drive(cls(), rr, probes, meta)
            bl[name] = round(sum(r["score"] for r in rws), 3)
        except Exception as e:
            bl[name] = f"err:{e!r}"

    fb = (f"quality={quality:.2f} cost={cost} cost_how={how}"
          f" breakdown={quality_breakdown(rows)}"
          f" baselines={bl} meta={meta}")
    print(json.dumps({"score": score, "feedback": fb}))


if __name__ == "__main__":
    main()
