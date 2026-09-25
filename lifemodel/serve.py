"""M4 Serve: probe -> answer, with honest byte metering.

`_probe_bytes` counts the serialized bytes the answer actually consulted
(the edge list for that (source, slot), the prov list, or the bundle) —
not self-declared constants. Cost is a function of what the code touched,
so an implementation can't fake it without also being cheap.

v1 handles all LifeStream v2 probe types against the TemporalGraph store:
    state/stale           -> self-vertex lookup at ckpt
    prov                  -> self's asserted values for the slot
    retract/cascade       -> gone answers ("已删除"/"未知")
    transfer              -> every live self-claim value (the bundle)
    as_of                 -> self-vertex lookup at probe["day"]
    subject               -> OTHER person's vertex at ckpt (hearsay)
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
        vals = store.live_bundle(ckpt, probe.get("slots"))
        _meter(vals)
        return ",".join(vals) if vals else "未知"
    if t == "subject":
        person = probe.get("person")
        edges = store.edges_of(person, slot)
        _meter(edges)
        v = store.live_at(person, slot, ckpt)
        return str(v) if v is not None else "未知"
    # state / stale / retract / cascade / derive / as_of: self vertex
    # first, then the live derived registry (M3 fold)
    day = probe.get("day", ckpt) if t == "as_of" else ckpt
    edges = store.edges_of("self", slot)
    v = store.live_at("self", slot, day)
    if v is None:
        d = store.drv.get(slot)
        _meter([edges, d])
        if d is not None and t != "as_of":
            return str(d["value"])
        return "已删除" if t in ("retract", "cascade", "derive") \
            else "未知"
    _meter(edges)
    return str(v)
