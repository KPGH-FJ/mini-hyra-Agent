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


def _v(claimer, about=None):
    """claimer|about vertex name — about=None is the self entity."""
    return f"{claimer}|{about}" if about else claimer


def answer(store, probe: dict, journal=()) -> str:
    t, slot = probe["type"], probe["slot"]
    ckpt = probe.get("ckpt", 10**9)
    about = probe.get("about")
    if t == "ops":
        # audit: which control ops ran (the journal is the only
        # place these are knowable — post-import it must still be there)
        _meter(list(journal))
        if probe.get("op") == "forget_range":
            hits = [f"{e['scope']['day_gte']}-{e['scope']['day_lte']}"
                    for e in journal
                    if e.get("op") == "forget"
                    and isinstance(e.get("scope"), dict)
                    and e["scope"].get("day_gte") is not None]
        else:
            hits = [(e.get("slot") or e.get("purpose"))
                    for e in journal
                    if e.get("op") == probe.get("op")
                    and (e.get("slot") or e.get("purpose"))]
        return hits[0] if hits else "无"
    if t == "drvprov":
        # premise citation: the premise registry must be inspectable
        e = store.drv.get(slot)
        if not e:
            return "无"
        vals = [f"{ps}:{pv}" for ps, pv in e["premises"].items()]
        _meter(vals)
        return ",".join(vals)
    if t == "duration":
        # streak of the live value — walk the self-vertex edges back
        edges = sorted(store.hist.get(f"{_v('self', about)}|{slot}", []),
                       key=lambda e: e[1])
        _meter(edges)
        live_val, start = None, None
        for e in reversed(edges):
            if e[1] > ckpt:
                continue
            if e[2] == "retraction":
                break
            if live_val is None:
                live_val, start = e[0], e[1]
            elif e[0] == live_val:
                start = e[1]
            else:
                break
        if live_val is None:
            return "无"
        return f"{ckpt - start}天"
    if t == "nchange":
        edges = sorted(store.hist.get(f"{_v('self', about)}|{slot}", []),
                       key=lambda e: e[1])
        _meter(edges)
        n, prev = 0, None
        for e in edges:
            if e[1] > ckpt:
                break
            if e[2] == "retraction":
                prev = None
                continue
            if prev is not None and e[0] != prev:
                n += 1
            prev = e[0]
        return str(n)
    if t == "conf":
        # epistemic grade: self-authoritative knowledge vs hearsay
        person = probe.get("person")
        if person:
            seen = []
            for f in store.forms_of(person):
                seen += store.edges_of(_v(f, about), slot)
            _meter(seen)
            live = [e for e in seen
                    if e[1] <= ckpt and e[2] != "retraction"]
            return "低" if live else "无"
        _meter(store.edges_of(_v("self", about), slot))
        return "高" if store.live_at(_v("self", about), slot, ckpt) \
            is not None else "无"
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
        # person merges with known aliases; latest day wins across forms
        best, bd, seen = None, -1, []
        for f in store.forms_of(person):
            edges = store.edges_of(_v(f, about), slot)
            seen += edges
            for e in edges:
                if (e[1] <= ckpt and e[2] != "retraction"
                        and e[1] > bd):
                    best, bd = e[0], e[1]
        _meter(seen)
        return str(best) if best is not None else "未知"
    if t in ("purpose", "revoked"):
        # purpose withdrawal: the use is revoked, not the data — refuse
        # the view even though the slots stay live elsewhere
        _meter(sorted(store.revoked))
        if probe.get("purpose") in store.revoked:
            return "已撤回"
        # task-conditioned view: live values of the purpose's slots only
        vals = store.live_bundle(ckpt, probe.get("purpose_slots"))
        _meter(vals)
        return ",".join(str(v) for v in vals) if vals else "未知"
    if t == "budget":
        # budgeted packing: values of the listed slots, in slot order —
        # the scorer reads only the first `budget` bytes
        vals = store.live_bundle(ckpt, probe.get("slots"))
        _meter(vals)
        return ",".join(str(v) for v in vals) if vals else "未知"
    if t == "prov2":
        rid = store.rvid.get(slot)
        _meter(rid)
        return str(rid) if rid else "未知"
    # state / stale / retract / cascade / derive / as_of: self vertex
    # first, then the live derived registry (M3 fold)
    day = probe.get("day", ckpt) if t == "as_of" else ckpt
    edges = store.edges_of(_v("self", about), slot)
    v = store.live_at(_v("self", about), slot, day)
    if v is None:
        # the derived registry is self-domain only — an about-probe
        # that finds no vertex edge is honestly unknown
        d = None if about else store.drv.get(slot)
        _meter([edges, d])
        if d is not None and t != "as_of":
            return str(d["value"])
        return "已删除" if t in ("retract", "cascade", "derive") \
            else "未知"
    _meter(edges)
    return str(v)
