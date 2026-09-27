"""Life Model asset: contract-first ingest/serve with uniform history traversal."""

import copy
import json

WRITE_KINDS = ("statement", "update", "correction")
CLAIM_KINDS = ("hearsay", "statement", "update", "correction")
ENTITY_SOURCES = ("self", "other", "assistant", "doc")

_STATE = {
    "version": "life-model-serve-run-edge",
    "records": {},
    "alias_events": [],
    "aliases": {},
    "journal": [],
    "revoked_purposes": [],
    "erased_rids": [],
    "current_day": 0,
    "arrival": 0,
    "probe_bytes": 0,
    "llm_tokens": 0,
}

_CONSULTED = []
_CONSULTED_SEEN = set()


def _fresh():
    return {
        "version": "life-model-serve-run-edge",
        "records": {},
        "alias_events": [],
        "aliases": {},
        "journal": [],
        "revoked_purposes": [],
        "erased_rids": [],
        "current_day": 0,
        "arrival": 0,
        "probe_bytes": 0,
        "llm_tokens": 0,
    }


def _ensure():
    global _STATE
    if not isinstance(_STATE, dict):
        _STATE = _fresh()
    _STATE.setdefault("records", {})
    _STATE.setdefault("alias_events", [])
    _STATE.setdefault("aliases", {})
    _STATE.setdefault("journal", [])
    _STATE.setdefault("revoked_purposes", [])
    _STATE.setdefault("erased_rids", [])
    _STATE.setdefault("current_day", 0)
    _STATE.setdefault("arrival", 0)
    _STATE.setdefault("probe_bytes", 0)
    _STATE.setdefault("llm_tokens", 0)


def _records():
    _ensure()
    if not isinstance(_STATE.get("records"), dict):
        _STATE["records"] = {}
    return _STATE["records"]


def _journal():
    _ensure()
    if not isinstance(_STATE.get("journal"), list):
        _STATE["journal"] = []
    return _STATE["journal"]


def _as_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _norm(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = [_norm(x) for x in value]
        parts = [x for x in parts if x is not None]
        return ",".join(parts) if parts else None
    if isinstance(value, dict):
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return None
        return " ".join(text.split())
    text = str(value)
    return " ".join(text.split())


def _same(a, b):
    return _norm(a) == _norm(b)


def _day(rec):
    return _as_int(rec.get("day"), 0)


def _arrival(rec):
    return _as_int(rec.get("arrival"), 0)


def _slot(rec):
    return _norm(rec.get("slot"))


def _about(rec):
    return _norm(rec.get("about"))


def _source(rec):
    return _norm(rec.get("source"))


def _kind(rec):
    return _norm(rec.get("kind"))


def _value(rec):
    return _norm(rec.get("value"))


def _expired(rec, read_day):
    if rec.get("expires_day") is None:
        return False
    return _as_int(read_day, 0) > _as_int(rec.get("expires_day"), 0)


def _erased(rec):
    return bool(rec.get("erased")) or rec.get("id") in _STATE.get("erased_rids", [])


def _supports(rec):
    raw = rec.get("supports")
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw if x is not None]
    return [str(raw)]


def _consult_obj(obj):
    try:
        rid = obj.get("id")
    except Exception:
        return
    if rid is None or rid in _CONSULTED_SEEN:
        return
    _CONSULTED_SEEN.add(rid)
    _CONSULTED.append(obj)


def _consult(rid):
    rec = _records().get(rid)
    if rec is not None:
        _consult_obj(rec)


def _meter():
    _ensure()
    if _CONSULTED:
        payload = [
            {
                "id": x.get("id"),
                "day": x.get("day"),
                "slot": x.get("slot"),
                "kind": x.get("kind"),
                "source": x.get("source"),
                "value": x.get("value"),
            }
            for x in _CONSULTED
        ]
        _STATE["probe_bytes"] = _as_int(_STATE.get("probe_bytes"), 0) + len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    _CONSULTED.clear()
    _CONSULTED_SEEN.clear()


def _canonical_name(name):
    if name is None:
        return None
    text = _norm(name)
    if not text:
        return None
    aliases = _STATE.get("aliases") or {}
    reverse = aliases.get("reverse") or {}
    if text in reverse:
        return reverse[text]
    return text


def _alias_names_from(rec):
    canonical = _value(rec)
    names = set()
    if canonical:
        names.add(canonical)
    for key in ("person", "subject", "target", "claimer", "slot"):
        val = _norm(rec.get(key))
        if val:
            names.add(val)
    text = _norm(rec.get("text"))
    if text and "=" in text:
        left, right = text.split("=", 1)
        for val in (left, right):
            val = _norm(val)
            if val:
                names.add(val)
    return canonical, names


def _rebuild_aliases():
    _ensure()
    mapping = {}
    events = []
    for rec in _records().values():
        if _kind(rec) != "alias" or _erased(rec):
            continue
        canonical, names = _alias_names_from(rec)
        if not canonical:
            continue
        events.append({"day": _day(rec), "canonical": canonical, "names": sorted(names)})
        mapping.setdefault(canonical, set()).update(names)
    for ev in _STATE.get("alias_events") or []:
        canonical = _norm(ev.get("canonical"))
        names = ev.get("names") or []
        if not canonical:
            continue
        mapping.setdefault(canonical, set()).update([str(x) for x in names])
    reverse = {}
    for canonical, names in mapping.items():
        reverse[canonical] = canonical
        for name in names:
            reverse[str(name)] = canonical
    _STATE["aliases"] = {
        "forward": {k: sorted(v) for k, v in mapping.items()},
        "reverse": reverse,
    }
    _STATE["alias_events"] = events


def _names_for(name):
    canonical = _canonical_name(name)
    if not canonical:
        return set()
    forward = (_STATE.get("aliases") or {}).get("forward") or {}
    names = set(forward.get(canonical, []))
    names.add(canonical)
    if name is not None:
        names.add(_norm(name))
    return {x for x in names if x}


def _is_write(rec, about=None):
    if _erased(rec) or _kind(rec) not in WRITE_KINDS:
        return False
    src = _source(rec)
    if about is None:
        return src == "self" and _about(rec) is None
    if _canonical_name(_about(rec)) != _canonical_name(about):
        return False
    return src in ENTITY_SOURCES


def _is_entity_claim(rec, about=None):
    if _erased(rec) or _kind(rec) not in CLAIM_KINDS:
        return False
    src = _source(rec)
    if src in ("system", "inference") or _kind(rec) == "suggestion":
        return False
    if about is not None and _canonical_name(_about(rec)) != _canonical_name(about):
        return False
    if about is None and _about(rec) is not None:
        return False
    return True


def _derived_records(slot=None, read_day=None, about=None):
    out = []
    for rid, rec in _records().items():
        if _erased(rec) or _kind(rec) != "derived":
            continue
        if slot is not None and _slot(rec) != slot:
            continue
        if about is None and _about(rec) is not None:
            continue
        if about is not None and _canonical_name(_about(rec)) != _canonical_name(about):
            continue
        if _day(rec) > _as_int(read_day, 0):
            continue
        out.append(rec)
    return out


def _live_value_at(slot, read_day, about=None, include_derived=True):
    edges = _run_edges(slot, read_day=read_day, about=about, include_derived=include_derived)
    if not edges:
        return None
    return edges[-1].get("value")


def _premise_snapshot(rec, support):
    snaps = rec.get("premise_values")
    if isinstance(snaps, dict):
        val = snaps.get(support.get("id"))
        if val is not None:
            return _norm(val)
    return _value(support)


def _derived_alive(rec, read_day, seen=None):
    if _erased(rec) or _kind(rec) != "derived":
        return False
    if _expired(rec, read_day):
        return False
    rid = rec.get("id")
    seen = seen or set()
    if rid in seen:
        return False
    seen.add(rid)
    if _value(rec) is None:
        return False
    if _live_value_at(_slot(rec), read_day, about=_about(rec), include_derived=False) is None:
        return False
    supports = _supports(rec)
    if not supports:
        return True
    for rid in supports:
        _consult(rid)
        support = _records().get(rid)
        if support is None or _erased(support):
            return False
        if _kind(support) == "retraction":
            return False
        if _expired(support, read_day):
            return False
        if _kind(support) == "derived" and not _derived_alive(support, min(read_day, _day(support)), seen):
            return False
        snapshot = _premise_snapshot(rec, support)
        current = _live_value_at(
            _slot(support),
            read_day,
            about=_about(support),
            include_derived=_kind(support) == "derived",
        )
        if not _same(snapshot, current):
            return False
    return True


def _collect(slot, read_day, about=None, include_derived=True, include_retraction=True):
    if slot is None:
        return []
    read_day = _as_int(read_day, 0)
    out = []
    for rec in _records().values():
        _consult(rec.get("id"))
        if _erased(rec):
            continue
        kind = _kind(rec)
        if kind in ("alias", "suggestion"):
            continue
        if _day(rec) > read_day:
            continue
        if _expired(rec, read_day):
            continue
        if _slot(rec) != slot:
            continue
        if about is None and _about(rec) is not None:
            continue
        if about is not None and _canonical_name(_about(rec)) != _canonical_name(about):
            continue
        if kind == "retraction":
            if not include_retraction:
                continue
            src = _source(rec)
            if about is None and src not in ("self", None):
                continue
            out.append(rec)
        elif _is_write(rec, about):
            out.append(rec)
        elif kind == "derived" and include_derived and _derived_alive(rec, read_day):
            out.append(rec)
    return out


def _sort_events(recs):
    return sorted(recs, key=lambda r: (_day(r), _arrival(r)))


def _authority(rec, about=None):
    src = _source(rec)
    if _kind(rec) == "derived":
        return "derived"
    if about is None:
        return "self"
    return src or "unknown"


def _run_edges(slot, read_day=None, about=None, upto=None, include_derived=True):
    _ensure()
    if read_day is None:
        read_day = _STATE.get("current_day", 0)
    read_day = _as_int(read_day, 0)
    as_of = read_day if upto is None else min(read_day, _as_int(upto, 0))
    events = _sort_events(_collect(slot, as_of, about=about, include_derived=include_derived))
    last_retraction = -1
    for idx, rec in enumerate(events):
        if _kind(rec) == "retraction":
            last_retraction = idx
    run = [r for r in events[last_retraction + 1:] if _kind(r) != "retraction"]
    return [
        {
            "day": _day(r),
            "value": _value(r),
            "rid": r.get("id"),
            "authority": _authority(r, about),
            "alive": True,
        }
        for r in run
    ]


def _claim_events(person=None, about=None, slot=None, read_day=None):
    read_day = _as_int(read_day, 0)
    person_canonical = _canonical_name(person)
    events = []
    for rec in _records().values():
        _consult(rec.get("id"))
        if _erased(rec) or _kind(rec) not in CLAIM_KINDS and _kind(rec) != "retraction":
            continue
        if _kind(rec) in ("alias", "suggestion", "derived"):
            continue
        if _day(rec) > read_day:
            continue
        if _expired(rec, read_day):
            continue
        if slot is not None and _slot(rec) != slot:
            continue
        if about is not None and _canonical_name(_about(rec)) != _canonical_name(about):
            continue
        if about is None and _about(rec) is not None and person is not None:
            continue
        claimer = _norm(rec.get("claimer")) or _norm(rec.get("person")) or _source(rec)
        subject = _norm(rec.get("person")) or _about(rec) or _source(rec)
        if person_canonical is not None:
            if (
                _canonical_name(claimer) != person_canonical
                and _canonical_name(subject) != person_canonical
                and _canonical_name(_source(rec)) != person_canonical
            ):
                continue
        events.append(rec)
    return _sort_events(events)


def _latest_claim(person=None, about=None, slot=None, read_day=None):
    events = _claim_events(person, about, slot, read_day)
    last_retraction = -1
    for idx, rec in enumerate(events):
        if _kind(rec) == "retraction":
            last_retraction = idx
    for rec in reversed(events[last_retraction + 1:]):
        if _kind(rec) == "retraction":
            continue
        return rec
    return None


def _retraction_active(slot, read_day, about=None):
    events = _sort_events(_collect(slot, read_day, about=about, include_derived=False))
    last_write = -1
    last_retraction = -1
    for idx, rec in enumerate(events):
        if _kind(rec) == "retraction":
            last_retraction = idx
        else:
            last_write = idx
    return last_retraction > last_write


def _journal_latest(op):
    entries = [x for x in _journal() if x.get("op") == op]
    if not entries:
        return None
    return max(entries, key=lambda x: (_as_int(x.get("day"), 0), _as_int(x.get("arrival"), 0)))


def _journal_append(op, scope, day=None):
    _ensure()
    entry = {
        "id": "op-%s-%s" % (op, _STATE.get("arrival", 0) + 1),
        "op": op,
        "day": _as_int(day if day is not None else _STATE.get("current_day"), 0),
        "arrival": _as_int(_STATE.get("arrival"), 0) + 1,
        "scope": copy.deepcopy(scope) if isinstance(scope, dict) else {},
    }
    _journal().append(entry)
    _consult_obj(entry)
    return entry


def ingest(rec):
    _ensure()
    if not isinstance(rec, dict):
        return None
    records = _records()
    rid = _norm(rec.get("id")) or ("rec-%s" % (_as_int(_STATE.get("arrival"), 0) + 1))
    if rid in records:
        return None
    day = _as_int(rec.get("day"), _as_int(_STATE.get("current_day"), 0))
    arrival = _as_int(_STATE.get("arrival"), 0) + 1
    out = {"id": rid, "day": day, "arrival": arrival}
    for key in (
        "source", "kind", "slot", "value", "expires_day", "about", "supports",
        "purpose", "person", "claimer", "subject", "target",
    ):
        if rec.get(key) is not None:
            out[key] = rec[key]
    if _kind(out) == "alias" or "alias" in str(rec.get("text") or ""):
        out["text"] = rec.get("text")
    records[rid] = out
    _STATE["arrival"] = arrival
    _STATE["current_day"] = max(_as_int(_STATE.get("current_day"), 0), day)
    if _kind(out) == "derived" and out.get("premise_values") is None:
        snaps = {}
        for support_id in _supports(out):
            support = records.get(support_id)
            if support is None:
                continue
            snaps[support_id] = _premise_snapshot(out, support)
        out["premise_values"] = snaps
    _rebuild_aliases()
    return None


def forget(scope):
    _ensure()
    scope = copy.deepcopy(scope) if isinstance(scope, dict) else {}
    day = _as_int(scope.get("day"), _STATE.get("current_day", 0))
    a = scope.get("a", scope.get("start", scope.get("from_day")))
    b = scope.get("b", scope.get("end", scope.get("to_day")))
    op = "forget_range" if (a is not None and b is not None) else "forget"
    targets = []
    if scope.get("rid"):
        targets.append(_norm(scope.get("rid")))
    slots = []
    if scope.get("slot"):
        slots.append(_norm(scope.get("slot")))
    if scope.get("slots"):
        slots.extend([_norm(x) for x in scope.get("slots") if x is not None])
    about = scope.get("about")
    for rid, rec in _records().items():
        if rid in targets:
            rec["erased"] = True
            continue
        if about is not None and _canonical_name(_about(rec)) == _canonical_name(about):
            rec["erased"] = True
            continue
        if a is not None and b is not None and _as_int(a, 0) <= _day(rec) <= _as_int(b, 0):
            rec["erased"] = True
            continue
        if slots and _slot(rec) in slots:
            if about is None and _about(rec) is None:
                rec["erased"] = True
            elif about is not None and _canonical_name(_about(rec)) == _canonical_name(about):
                rec["erased"] = True
    erased = [rid for rid, rec in _records().items() if rec.get("erased")]
    _STATE["erased_rids"] = sorted(set(_STATE.get("erased_rids") or []) | set(erased))
    _STATE["current_day"] = max(_as_int(_STATE.get("current_day"), 0), day)
    _journal_append(op, scope, day=day)
    _rebuild_aliases()
    return None


def correct(slot, value, **kwargs):
    _ensure()
    day = _as_int(kwargs.get("day"), _as_int(_STATE.get("current_day"), 0))
    arrival = _as_int(_STATE.get("arrival"), 0) + 1
    rid = "correct-%s" % arrival
    rec = {
        "id": rid,
        "day": day,
        "arrival": arrival,
        "source": "self",
        "kind": "correction",
        "slot": _norm(slot),
        "value": _norm(value),
    }
    if rec["slot"] is None:
        return None
    _records()[rid] = rec
    _STATE["arrival"] = arrival
    _STATE["current_day"] = max(_as_int(_STATE.get("current_day"), 0), day)
    _journal_append("correct", {"slot": rec["slot"], "value": rec["value"]}, day=day)
    return None


def revoke_purpose(purpose, **kwargs):
    _ensure()
    purpose = _norm(purpose)
    if purpose and purpose not in _STATE.get("revoked_purposes", []):
        _STATE.setdefault("revoked_purposes", []).append(purpose)
    _journal_append("revoke_purpose", {"purpose": purpose})
    return None


def _scoped_doc(scope, read_day=None):
    _ensure()
    if not isinstance(scope, dict):
        if scope is None:
            return {}
        if isinstance(scope, str):
            scope = {"slots": [scope]}
        elif isinstance(scope, (list, tuple)):
            scope = {"slots": list(scope)}
        else:
            return {}
    purpose = _norm(scope.get("purpose"))
    if purpose and purpose in (_STATE.get("revoked_purposes") or []):
        return {}
    slots = []
    for key in ("purpose_slots", "slots"):
        if scope.get(key):
            slots = [x for x in scope.get(key) if x is not None]
            break
    if not slots and scope.get("slot"):
        slots = [scope.get("slot")]
    if not slots:
        return {}
    day = read_day
    if day is None:
        day = scope.get("day", scope.get("ckpt", _STATE.get("current_day", 0)))
    about = scope.get("about")
    doc = {}
    for slot in slots:
        slot = _norm(slot)
        if not slot:
            continue
        value = _live_value_at(slot, day, about=about)
        doc[slot] = value if value is not None else "未知"
    return doc


def state(scope=None, *args, **kwargs):
    _ensure()
    if scope is not None:
        return _scoped_doc(scope)
    return copy.deepcopy(_STATE)


def import_state(d):
    global _STATE
    _ensure()
    if not d:
        _STATE = _fresh()
        return None
    if not isinstance(d, dict):
        return None
    records = d.get("records")
    if not isinstance(records, dict):
        records = {}
    clean = {}
    for rid, rec in records.items():
        if not isinstance(rec, dict):
            continue
        out = copy.deepcopy(rec)
        out["id"] = str(rid)
        clean[str(rid)] = out
    _STATE = {
        "version": d.get("version", "life-model-serve-run-edge"),
        "records": clean,
        "alias_events": d.get("alias_events") if isinstance(d.get("alias_events"), list) else [],
        "aliases": d.get("aliases") if isinstance(d.get("aliases"), dict) else {},
        "journal": d.get("journal") if isinstance(d.get("journal"), list) else [],
        "revoked_purposes": d.get("revoked_purposes") if isinstance(d.get("revoked_purposes"), list) else [],
        "erased_rids": d.get("erased_rids") if isinstance(d.get("erased_rids"), list) else [],
        "current_day": _as_int(d.get("current_day"), 0),
        "arrival": _as_int(d.get("arrival"), 0),
        "probe_bytes": _as_int(d.get("probe_bytes"), 0),
        "llm_tokens": _as_int(d.get("llm_tokens"), 0),
    }
    if not _STATE["alias_events"] or not _STATE["aliases"]:
        _rebuild_aliases()
    _ensure()
    return None


def probe_bytes():
    _ensure()
    return _as_int(_STATE.get("probe_bytes"), 0)


def stats():
    _ensure()
    snapshot = state()
    asset_bytes = len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {
        "asset_bytes": asset_bytes,
        "probe_bytes": probe_bytes(),
        "llm_tokens": _as_int(_STATE.get("llm_tokens"), 0),
        "records": len(_records()),
        "current_day": _as_int(_STATE.get("current_day"), 0),
    }


def _read_day(probe):
    current = _as_int(probe.get("ckpt"), _as_int(_STATE.get("current_day"), 0))
    explicit = _as_int(probe.get("day"), current)
    qtype = _norm(probe.get("type")) or ""
    if qtype in ("as_of", "subject", "window", "absent"):
        return explicit
    return current


def _probe_slot(probe):
    if probe.get("slot") is not None:
        return _norm(probe.get("slot"))
    slots = probe.get("slots") or []
    if isinstance(slots, (list, tuple)) and slots:
        return _norm(slots[0])
    return _norm(probe.get("name"))


def _probe_slots(probe):
    if probe.get("slots"):
        return [_norm(x) for x in probe.get("slots") if x is not None]
    if probe.get("purpose_slots"):
        return [_norm(x) for x in probe.get("purpose_slots") if x is not None]
    slot = _probe_slot(probe)
    return [slot] if slot else []


def _probe_slot2(probe):
    for key in ("slot2", "slot_2", "other", "other_slot", "with", "join_slot"):
        if probe.get(key) is not None:
            return _norm(probe.get(key))
    slots = probe.get("slots") or []
    if isinstance(slots, (list, tuple)) and len(slots) >= 2:
        return _norm(slots[1])
    return None


def _probe_range(probe):
    a = probe.get("a", probe.get("start", probe.get("from_day")))
    b = probe.get("b", probe.get("end", probe.get("to_day")))
    if a is None:
        a = 30
    if b is None:
        b = 60
    return _as_int(a, 0), _as_int(b, 0)


def _values_join(values):
    values = [x for x in values if x is not None]
    return ",".join(values) if values else "未知"


def _answer_state(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    if slot is None:
        return "未知"
    value = _live_value_at(slot, day, about=about)
    return value if value is not None else "未知"


def _answer_retract(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    value = _live_value_at(slot, day, about=about)
    if value is not None:
        return value
    if _retraction_active(slot, day, about=about):
        return "已删除"
    return "未知"


def _derived_dead_by_erasure(slot, read_day, about=None):
    for rec in _derived_records(slot, read_day, about=about):
        if _derived_alive(rec, read_day):
            continue
        for rid in _supports(rec):
            if rid in (_STATE.get("erased_rids") or []):
                return True
            support = _records().get(rid)
            if support is None or _erased(support):
                return True
            entry = _journal_latest("forget") or _journal_latest("forget_range")
            if entry and _norm(entry.get("scope", {}).get("slot")) == _slot(support):
                return True
    return False


def _answer_cascade(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    value = _live_value_at(slot, day, about=about)
    if value is not None:
        return value
    entry = _journal_latest("forget") or _journal_latest("forget_range")
    if entry and (_norm(entry.get("scope", {}).get("slot")) == slot or _norm(entry.get("scope", {}).get("about")) == about):
        return "已删除"
    if _derived_dead_by_erasure(slot, day, about=about):
        return "已删除"
    if _retraction_active(slot, day, about=about):
        return "已删除"
    return "未知"


def _answer_derive(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    derived = _derived_records(slot, day, about=about)
    if not derived:
        return "未知"
    latest = max(derived, key=lambda r: (_day(r), _arrival(r)))
    if _derived_alive(latest, day):
        return _value(latest) or "未知"
    return "已删除"


def _answer_prov(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    claimed = _norm(probe.get("value"))
    edges = _run_edges(slot, read_day=day, about=about)
    if not edges:
        return "非本人"
    for edge in reversed(edges):
        if edge.get("authority") == "self" or (about is not None and edge.get("authority") == "self"):
            return "本人" if _same(edge.get("value"), claimed) else "非本人"
    return "非本人"


def _answer_prov2(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    edges = _run_edges(slot, read_day=day, about=about)
    if not edges:
        return "未知"
    return edges[-1].get("rid") or "未知"


def _answer_drvprov(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    derived = _derived_records(slot, day, about=about)
    if not derived:
        return "未知"
    latest = max(derived, key=lambda r: (_day(r), _arrival(r)))
    if not _derived_alive(latest, day):
        return "未知"
    supports = _supports(latest)
    return ",".join(supports) if supports else (latest.get("id") or "未知")


def _answer_subject(probe):
    person = probe.get("person")
    about = probe.get("about")
    slot = _probe_slot(probe)
    day = _read_day(probe)
    rec = _latest_claim(person=person, about=about, slot=slot, read_day=day)
    if rec is None:
        return "未知"
    return _value(rec) or "未知"


def _answer_transfer(probe):
    day = _read_day(probe)
    about = probe.get("about")
    values = []
    for slot in _probe_slots(probe):
        value = _live_value_at(slot, day, about=about)
        if value is not None:
            values.append(value)
    return _values_join(values)


def _answer_budget(probe):
    day = _read_day(probe)
    about = probe.get("about")
    known = []
    unknown = []
    for slot in _probe_slots(probe):
        value = _live_value_at(slot, day, about=about)
        if value is None:
            unknown.append("未知")
        else:
            known.append(value)
    return _values_join(known + unknown)


def _answer_purpose(probe):
    purpose = _norm(probe.get("purpose"))
    if purpose and purpose in (_STATE.get("revoked_purposes") or []):
        return "已撤回"
    probe = dict(probe)
    if probe.get("purpose_slots"):
        probe["slots"] = probe.get("purpose_slots")
    return _answer_transfer(probe)


def _answer_revoked(probe):
    purpose = _norm(probe.get("purpose"))
    if purpose and purpose in (_STATE.get("revoked_purposes") or []):
        return "已撤回"
    return _answer_purpose(probe)


def _answer_partial(probe):
    scope = probe.get("scope") or {"slots": _probe_slots(probe)}
    if probe.get("purpose"):
        scope = dict(scope)
        scope["purpose"] = probe.get("purpose")
    if probe.get("purpose_slots"):
        scope = dict(scope)
        scope["purpose_slots"] = probe.get("purpose_slots")
    doc = _scoped_doc(scope, read_day=_read_day(probe))
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def _answer_as_of(probe):
    return _answer_state(probe)


def _answer_first(probe):
    edges = _run_edges(_probe_slot(probe), read_day=_read_day(probe), about=probe.get("about"))
    if not edges:
        return "未知"
    return edges[0].get("value") or "未知"


def _answer_order(probe):
    edges = _run_edges(_probe_slot(probe), read_day=_read_day(probe), about=probe.get("about"))
    values = []
    for edge in edges:
        value = edge.get("value")
        if value is None:
            continue
        if not values or values[-1] != value:
            values.append(value)
    return "→".join(values) if values else "未知"


def _answer_join(probe):
    slot1 = _probe_slot(probe)
    slot2 = _probe_slot2(probe)
    if slot1 is None or slot2 is None:
        return "未知"
    edges = _run_edges(slot1, read_day=_read_day(probe), about=probe.get("about"))
    if not edges:
        return "未知"
    day = edges[-1].get("day")
    value = _live_value_at(slot2, day, about=probe.get("about"))
    return value if value is not None else "未知"


def _answer_absent(probe):
    threshold = probe.get("after", probe.get("day", 40))
    edges = _run_edges(_probe_slot(probe), read_day=_read_day(probe), about=probe.get("about"))
    return "是" if all(_as_int(e.get("day"), 0) <= _as_int(threshold, 0) for e in edges) else "否"


def _answer_window(probe):
    slot = _probe_slot(probe)
    a, b = _probe_range(probe)
    about = probe.get("about")
    read_day = _read_day(probe)
    edges = _run_edges(slot, read_day=read_day, about=about, upto=b)
    prev = _live_value_at(slot, min(a - 1, read_day), about=about)
    out = []
    if prev is not None:
        out.append(prev)
    for edge in edges:
        if not (_as_int(a, 0) <= _as_int(edge.get("day"), 0) <= _as_int(b, 0)):
            continue
        value = edge.get("value")
        if value is None:
            continue
        if not out or out[-1] != value:
            out.append(value)
    return _values_join(out)


def _answer_nchange(probe):
    edges = _run_edges(_probe_slot(probe), read_day=_read_day(probe), about=probe.get("about"))
    changes = 0
    prev = None
    for edge in edges:
        value = edge.get("value")
        if value is None:
            continue
        if prev is not None and not _same(prev, value):
            changes += 1
        prev = value
    return str(changes)


def _answer_duration(probe):
    edges = _run_edges(_probe_slot(probe), read_day=_read_day(probe), about=probe.get("about"))
    if not edges:
        return "未知"
    return str(max(0, _as_int(_read_day(probe), 0) - _as_int(edges[0].get("day"), 0)))


def _answer_ops(probe):
    op = _norm(probe.get("op"))
    entry = _journal_latest(op) if op else None
    if not entry:
        return "无"
    scope = entry.get("scope") or {}
    if op == "revoke_purpose":
        return _norm(scope.get("purpose")) or "无"
    if op == "forget_range":
        a = scope.get("a", scope.get("start", scope.get("from_day")))
        b = scope.get("b", scope.get("end", scope.get("to_day")))
        if a is None or b is None:
            return "无"
        return "%s-%s" % (_as_int(a, 0), _as_int(b, 0))
    for key in ("slot", "about", "rid", "purpose"):
        if scope.get(key) is not None:
            return str(scope.get(key))
    return "无"


def _answer_isconf(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    self_value = _live_value_at(slot, day, include_derived=False)
    if self_value is None:
        return "否"
    claimers = {}
    for rec in _records().values():
        if not _is_entity_claim(rec) or _slot(rec) != slot or _about(rec) is not None:
            continue
        if _day(rec) > day:
            continue
        claimer = _source(rec) or _norm(rec.get("person")) or rec.get("id")
        claimers[claimer] = rec
    for rec in claimers.values():
        if not _same(_value(rec), self_value):
            return "是"
    return "否"


def _answer_conf(probe):
    slot = _probe_slot(probe)
    day = _read_day(probe)
    about = probe.get("about")
    if about is not None:
        claims = [x for x in _records().values() if _is_entity_claim(x, about) and _slot(x) == slot and _day(x) <= day]
        if any(_source(x) == "self" for x in claims):
            return "高"
        if claims:
            return "低"
        return "无"
    edges = _run_edges(slot, read_day=day)
    if any(e.get("authority") == "self" for e in edges):
        return "高"
    if edges:
        return "低"
    claims = [x for x in _records().values() if _is_entity_claim(x) and _slot(x) == slot and _day(x) <= day]
    return "低" if claims else "无"


def _answer_xcmp(probe):
    slot = _probe_slot(probe)
    about = probe.get("about")
    if slot is None or about is None:
        return "未知"
    day = _read_day(probe)
    self_value = _live_value_at(slot, day, include_derived=False)
    entity_value = _live_value_at(slot, day, about=about)
    if entity_value is None:
        return "未知"
    if self_value is None:
        return "未知"
    return "是" if _same(self_value, entity_value) else "否"


def _answer_unans(probe):
    return "未知"


def _answer_expdeny(probe):
    return _answer_state(probe)


def _answer_clarify(probe):
    return "未知"


DISPATCH = {
    "state": _answer_state,
    "stale": _answer_state,
    "prov": _answer_prov,
    "prov2": _answer_prov2,
    "drvprov": _answer_drvprov,
    "retract": _answer_retract,
    "transfer": _answer_transfer,
    "as_of": _answer_as_of,
    "subject": _answer_subject,
    "cascade": _answer_cascade,
    "derive": _answer_derive,
    "post_import": _answer_state,
    "post_partial": _answer_partial,
    "unans": _answer_unans,
    "purpose": _answer_purpose,
    "revoked": _answer_revoked,
    "budget": _answer_budget,
    "partial": _answer_partial,
    "ops": _answer_ops,
    "duration": _answer_duration,
    "nchange": _answer_nchange,
    "first": _answer_first,
    "order": _answer_order,
    "join": _answer_join,
    "absent": _answer_absent,
    "window": _answer_window,
    "isconf": _answer_isconf,
    "conf": _answer_conf,
    "xcmp": _answer_xcmp,
    "expdeny": _answer_expdeny,
    "clarify": _answer_clarify,
}


def answer(probe):
    _ensure()
    try:
        if not isinstance(probe, dict):
            return "未知"
        qtype = _norm(probe.get("type")) or _norm(probe.get("q")) or "state"
        if qtype == "post_import":
            inner = dict(probe)
            inner["type"] = probe.get("inner_type", "state")
            qtype = _norm(inner.get("type")) or "state"
            probe = inner
        handler = DISPATCH.get(qtype) or _answer_state
        return handler(probe)
    except Exception:
        return "未知"
    finally:
        _meter()
