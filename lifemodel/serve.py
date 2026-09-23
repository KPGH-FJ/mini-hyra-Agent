"""M4 Serve: probe -> answer, with honest byte metering.

`_probe_bytes` counts the serialized bytes the answer actually consulted
(the slot entry, its prov list, or the bundle) — not self-declared
constants. This is the run-1 honesty fix made structural: cost is a
function of what the code touched, so an implementation can't fake it
without also being cheap.
"""
from __future__ import annotations

import json

_probe_bytes = 0


def _meter(obj) -> None:
    global _probe_bytes
    _probe_bytes += len(json.dumps(obj, ensure_ascii=False))


def probe_bytes() -> int:
    return _probe_bytes


def reset_meter() -> None:
    global _probe_bytes
    _probe_bytes = 0


def answer(store, probe: dict) -> str:
    t, slot = probe["type"], probe["slot"]
    ckpt = probe.get("ckpt", 10**9)
    if t == "prov":
        vals = store.prov.get(slot, [])
        _meter(vals)
        said = probe.get("value") in vals
        return "本人" if said else "非本人"
    if t == "transfer":
        slots = probe.get("slots")
        vals = store.live_bundle(ckpt, slots)
        _meter(vals)
        return ",".join(vals) if vals else "未知"
    # state / stale / retract: current value at ckpt
    e = store.state.get(slot)
    _meter(e)
    v = store.live(slot, ckpt)
    if t == "retract":
        return "已删除" if v is None else str(v)
    return str(v) if v is not None else "未知"
