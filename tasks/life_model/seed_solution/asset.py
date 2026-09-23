"""Seed asset: minimal-but-correct temporal ledger.

Keeps all records; state = last self-authored statement/update/correction
per slot; honors retractions and expiry; provenance = "did the person say
THIS slot=value". v2: as_of/subject answered by naive full replay (correct
but expensive — leaves the cost pressure for evolution), forget() drops
all records of a slot. Correct semantics, no compression — the baseline
to beat on quality-per-cost.
"""
import json

_records = []
_state = {}          # slot -> (value, day, expires_day)
_probe_bytes = 0


def ingest(rec: dict) -> None:
    _records.append(rec)
    slot, kind, src = rec["slot"], rec["kind"], rec["source"]
    if kind == "retraction" and src == "self":
        _state.pop(slot, None)
    elif src == "self" and kind in ("statement", "update", "correction"):
        _state[slot] = (rec["value"], rec["day"], rec.get("expires_day"))


def forget(scope: dict) -> None:
    slot = scope.get("slot")
    global _records
    _records = [r for r in _records if r["slot"] != slot]
    _state.pop(slot, None)


def _replay(day: int) -> dict:
    """Reconstruct self-state at `day` from full history (naive, costly)."""
    st, exp = {}, {}
    for r in _records:
        if r["day"] > day:
            continue
        if (r["source"] == "self"
                and r["kind"] in ("statement", "update", "correction")):
            st[r["slot"]] = r["value"]
            exp[r["slot"]] = r.get("expires_day")
        elif r["kind"] == "retraction":
            st.pop(r["slot"], None)
            exp.pop(r["slot"], None)
    for s, d in list(exp.items()):
        if d and day > d:
            st.pop(s, None)
    return st


def _current(slot, day=10**9):
    e = _state.get(slot)
    if not e or (e[2] and day > e[2]):
        return None
    return e[0]


def answer(probe: dict) -> str:
    global _probe_bytes
    slot, t = probe["slot"], probe["type"]
    _probe_bytes += len(json.dumps(_records))  # naive: consults everything
    if t == "prov":
        said = any(r["source"] == "self" and r["slot"] == slot
                   and r["value"] == probe.get("value")
                   and r["kind"] in ("statement", "update", "correction")
                   for r in _records)
        return "本人" if said else "非本人"
    if t == "transfer":
        vals = [v[0] for v in _state.values()
                if not (v[2] and probe.get("ckpt", 10**9) > v[2])]
        return ",".join(vals) if vals else "未知"
    if t == "as_of":
        v = _replay(probe.get("day", 10**9)).get(slot)
        return v if v is not None else "未知"
    if t == "subject":
        hits = [r for r in _records if r["kind"] == "hearsay"
                and r["source"] == probe.get("person")
                and r["slot"] == slot
                and r["day"] <= probe.get("ckpt", 10**9)]
        return hits[-1]["value"] if hits else "未知"
    v = _current(slot)
    return v if v is not None else "未知"


def stats() -> dict:
    return {"asset_bytes": len(json.dumps(_records)),
            "probe_bytes": _probe_bytes, "llm_tokens": 0}
