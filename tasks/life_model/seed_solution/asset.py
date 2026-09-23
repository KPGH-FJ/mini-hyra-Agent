"""Seed asset: minimal-but-correct temporal ledger.

Keeps all records; state = last self-authored statement/update/correction
per slot; honors retractions and expiry; provenance = "did the person say
THIS slot=value". Correct semantics, no compression — the baseline to beat
on quality-per-cost.
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
    v = _current(slot)
    return v if v is not None else "未知"


def stats() -> dict:
    return {"asset_bytes": len(json.dumps(_records)),
            "probe_bytes": _probe_bytes, "llm_tokens": 0}
