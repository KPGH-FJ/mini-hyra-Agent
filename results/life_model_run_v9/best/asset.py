#!/usr/bin/env python3
"""Life Model asset — event-sourced journal + run_edges serve primitive.

Design (greenfield, contract-first):
  * one append-only journal of records; every fact is a (subject,slot) temporal
    edge.  Day is authoritative, arrival order breaks same-day ties.
  * erasure (forget) REWRITES the log; retraction starts a NEW write-run;
    derived aliveness is recomputed from the surviving log, so a derived fact
    pruned by a killer that was itself erased comes back alive.
  * ONE serve primitive run_edges(slot, read_day, about) returns the surviving
    write-run as ordered edges; every deep-history answer is a thin fold over
    it (duration/first/order/nchange/window/absent/before/join/xcmp), and the
    traversal meters ONLY the requested edge list (probe_bytes).
  * state(scope=...) produces a leak-free scoped export doc and REFUSES
    (empty doc) for a revoked purpose; the op journal carries full scope dicts
    and survives export->import.
"""
import json
import re
import threading

_LOCK = threading.RLock()

_EVENTS = []      # the record log; erasure rewrites this list in place
_OPS = []         # operation journal: {"op":..., "scope":{...}, "day":...}
_REVOKED = []     # revoked purposes
_ALIASES = {}     # name -> canonical name
_ARR = 0          # arrival counter
_PB = 0           # cumulative consulted bytes

_WRITE_KINDS = ("statement", "update", "correction")


# ------------------------------------------------------------------ utilities
def _i(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _same_about(e, about):
    ea = e.get("about")
    if about is None:
        return ea is None
    return ea == about


def _is_write(e):
    if e.get("kind") in _WRITE_KINDS and e.get("src") == "self":
        return True
    if e.get("kind") == "derived" and e.get("src") == "inference":
        return True
    return False


def _by_id(rid):
    for e in _EVENTS:
        if e.get("rid") == rid:
            return e
    return None


def _max_day():
    m = 0
    for e in _EVENTS:
        if e["day"] > m:
            m = e["day"]
    return m


def _meter(e):
    global _PB
    try:
        _PB += len(json.dumps(e, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        _PB += len(str(e))


# ------------------------------------------------------------------ aliveness
def _retracted(e, read_day):
    slot = e.get("slot")
    for r in _EVENTS:
        if r.get("kind") != "retraction" or r.get("slot") != slot:
            continue
        if not _same_about(r, e.get("about")):
            continue
        if e["day"] <= r["day"] <= read_day:
            return True
    return False


def _alive(e, read_day):
    if e is None:
        return False
    if e["day"] > read_day:
        return False
    exp = e.get("exp")
    if exp is not None and read_day > exp:
        return False
    if _retracted(e, read_day):
        return False
    return True


def _premises_alive(e, read_day, _seen=None):
    sup = e.get("sup")
    if not sup:
        return True
    if isinstance(sup, str):
        sup = [sup]
    if _seen is None:
        _seen = set()
    if e.get("rid") in _seen:
        return False
    _seen.add(e.get("rid"))
    for rid in sup:
        pe = _by_id(rid)
        if pe is None:
            return False
        if not _alive(pe, read_day):
            return False
        if pe.get("kind") == "derived" and not _premises_alive(pe, read_day, _seen):
            return False
        lv = _live_value(pe.get("slot"), read_day, pe.get("about"))
        if lv != pe.get("val"):
            return False
    return True


def _write_alive(e, read_day):
    if not _is_write(e):
        return False
    if not _alive(e, read_day):
        return False
    if e.get("kind") == "derived" and not _premises_alive(e, read_day):
        return False
    return True


def _live_value(slot, read_day, about=None):
    best = _live_write(slot, read_day, about)
    return best.get("val") if best is not None else None


def _live_write(slot, read_day, about=None):
    if slot is None:
        return None
    best = None
    for e in _EVENTS:
        if e.get("slot") != slot or not _same_about(e, about):
            continue
        if not _write_alive(e, read_day):
            continue
        if best is None or (e["day"], e["arr"]) > (best["day"], best["arr"]):
            best = e
    return best


# ------------------------------------------------- THE serve primitive: edges
def _candidates(slot, read_day, about):
    ev = [e for e in _EVENTS
          if e.get("slot") == slot and _same_about(e, about) and e["day"] <= read_day]
    ev.sort(key=lambda e: (e["day"], e["arr"]))
    return ev


def run_edges(slot, read_day, about=None):
    """Surviving write-run of (slot[,about]) as of read_day, as ordered edges
    {day,value,rid,authority(src),alive}.  Retraction starts a new run;
    erasure has already rewritten the log.  Meters only this edge list."""
    with _LOCK:
        run = []
        for e in _candidates(slot, read_day, about):
            if e.get("kind") == "retraction":
                run = []          # retraction opens a new run
                _meter(e)
                continue
            if _write_alive(e, read_day):
                run.append(e)
                _meter(e)
        return run


def _all_edges(slot, read_day, about=None):
    """All surviving (non-erased, non-expired) writes in day order, ignoring
    retraction boundaries — used by log-level folds (order/window/absent)."""
    with _LOCK:
        out = []
        for e in _candidates(slot, read_day, about):
            if e.get("kind") == "retraction":
                continue
            if not _is_write(e):
                continue
            exp = e.get("exp")
            if exp is not None and read_day > exp:
                continue
            out.append(e)
            _meter(e)
        return out


def _value_start(slot, read_day, about=None):
    """Day the current live value began = the last transition day of the run."""
    edges = run_edges(slot, read_day, about)
    if not edges:
        return None
    live = edges[-1].get("val")
    i = len(edges) - 1
    while i >= 0 and edges[i].get("val") == live:
        i -= 1
    return edges[i + 1]["day"]


# ------------------------------------------------------------------ aliases
def _names_for(person):
    names = set()
    if person is None:
        return names
    names.add(str(person))
    canon = _ALIASES.get(str(person), str(person))
    names.add(canon)
    for k, v in _ALIASES.items():
        if v == canon:
            names.add(k)
    return {n for n in names if n}


def _add_alias(e):
    canon = e.get("val")
    names = set()
    if canon is not None:
        names.add(str(canon))
    txt = e.get("text") or ""
    for part in re.split(r"[=＝,，、;；]", txt):
        part = part.strip()
        if part:
            names.add(part)
    for k in ("alias", "slot2", "name"):
        if e.get(k):
            names.add(str(e[k]))
    target = str(canon) if canon is not None else (names.pop() if names else None)
    for n in names:
        if n and n not in _ALIASES:
            _ALIASES[n] = target or n


# ------------------------------------------------------------------ ingest
def ingest(rec):
    global _ARR
    with _LOCK:
        _ARR += 1
        rec = rec or {}
        e = {
            "rid": rec.get("id") or rec.get("rid") or ("r%04d" % _ARR),
            "day": _i(rec.get("day")),
            "arr": _ARR,
            "src": rec.get("source") or rec.get("src") or "",
            "kind": rec.get("kind") or "",
            "slot": rec.get("slot") or "",
            "val": rec.get("value"),
            "about": rec.get("about"),
            "exp": rec.get("expires_day"),
            "sup": rec.get("supports"),
            "text": rec.get("text"),
            "person": rec.get("person"),
            "purpose": rec.get("purpose"),
        }
        _EVENTS.append(e)
        if e["kind"] == "alias" or e["slot"] == "alias":
            _add_alias(e)


# ------------------------------------------------------------------ control ops
def _matches(e, scope):
    if not any(scope.get(k) is not None for k in
               ("slot", "about", "rid", "purpose", "from_day", "to_day")):
        return False
    if scope.get("slot") is not None and e.get("slot") != scope["slot"]:
        return False
    if scope.get("about") is not None and e.get("about") != scope["about"]:
        return False
    if scope.get("rid") is not None and e.get("rid") != scope["rid"]:
        return False
    if scope.get("purpose") is not None and e.get("purpose") != scope["purpose"]:
        return False
    if scope.get("from_day") is not None and e["day"] < _i(scope["from_day"]):
        return False
    if scope.get("to_day") is not None and e["day"] > _i(scope["to_day"]):
        return False
    return True


def forget(scope=None, **kw):
    scope = dict(scope or {})
    scope.update({k: v for k, v in kw.items() if v is not None})
    op = scope.pop("op", None)
    if op is None:
        op = "forget_range" if ("from_day" in scope or "to_day" in scope) else "forget"
    with _LOCK:
        day = scope.get("day")
        if day is None:
            day = _max_day()
        _OPS.append({"op": op, "scope": scope, "day": _i(day)})
        if op in ("forget", "forget_range"):
            keep = []
            touched = False
            for e in _EVENTS:
                if _matches(e, scope):
                    touched = True
                    continue
                keep.append(e)
            if touched:
                _EVENTS[:] = keep     # erasure REWRITES the log


def forget_range(scope=None, **kw):
    scope = dict(scope or {})
    scope.update({k: v for k, v in kw.items() if v is not None})
    scope["op"] = "forget_range"
    forget(scope)


def correct(slot=None, value=None, **kw):
    global _ARR
    if isinstance(slot, dict):
        rec = dict(slot)
        slot = rec.get("slot")
        value = rec.get("value")
        kw = rec
    with _LOCK:
        day = kw.get("day")
        if day is None:
            day = _max_day()
        _OPS.append({"op": "correct", "scope": {"slot": slot, "value": value},
                     "day": _i(day)})
        _ARR += 1
        _EVENTS.append({
            "rid": kw.get("id") or kw.get("rid") or ("c%04d" % _ARR),
            "day": _i(day),
            "arr": _ARR,
            "src": "self",
            "kind": "correction",
            "slot": slot,
            "val": value,
            "about": kw.get("about"),
            "exp": kw.get("expires_day"),
            "sup": kw.get("supports"),
            "text": kw.get("text"),
            "person": kw.get("person"),
            "purpose": kw.get("purpose"),
        })


def revoke_purpose(purpose=None, **kw):
    if purpose is None:
        purpose = kw.get("purpose")
    if purpose is None:
        return
    with _LOCK:
        if purpose not in _REVOKED:
            _REVOKED.append(purpose)
        day = kw.get("day")
        if day is None:
            day = _max_day()
        _OPS.append({"op": "revoke_purpose", "scope": {"purpose": purpose},
                     "day": _i(day)})


# ------------------------------------------------------------------ state io
def _scoped_doc(scope):
    scope = scope or {}
    purpose = scope.get("purpose")
    if purpose and purpose in _REVOKED:
        return {}                       # REFUSE: no doc for a revoked purpose
    slots = scope.get("slots") or scope.get("purpose_slots") or []
    day = scope.get("day")
    if day is None:
        day = scope.get("ckpt")
    if day is None:
        day = _max_day()
    about = scope.get("about")
    doc = {}
    for s in slots:
        v = _live_value(s, _i(day), about)
        if v is not None:
            doc[s] = v                  # ONLY in-scope live values, no leaks
    return doc


def state(scope=None):
    with _LOCK:
        if scope is not None:
            return _scoped_doc(scope)
        return {
            "events": _EVENTS,
            "ops": _OPS,
            "revoked": list(_REVOKED),
            "aliases": dict(_ALIASES),
            "pb": _PB,
            "arr": _ARR,
        }


def import_state(d):
    global _EVENTS, _OPS, _REVOKED, _ALIASES, _ARR, _PB
    d = d or {}
    with _LOCK:
        _EVENTS = list(d.get("events") or [])
        _OPS = list(d.get("ops") or [])
        _REVOKED = list(d.get("revoked") or [])
        _ALIASES = dict(d.get("aliases") or {})
        _PB = _i(d.get("pb"))
        _ARR = _i(d.get("arr"), len(_EVENTS))


def probe_bytes():
    return _PB


def stats():
    with _LOCK:
        return {
            "asset_bytes": len(json.dumps(state(), ensure_ascii=False)),
            "probe_bytes": _PB,
            "llm_tokens": 0,
        }


def reset():
    global _EVENTS, _OPS, _REVOKED, _ALIASES, _ARR, _PB
    with _LOCK:
        _EVENTS = []
        _OPS = []
        _REVOKED = []
        _ALIASES = {}
        _ARR = 0
        _PB = 0


# ------------------------------------------------------------------ serve
def _guess_type(q):
    q = q or ""
    tbl = (
        ("duration", ("多久", "持续", "几天", "duration")),
        ("first", ("第一次", "最初", "最开始", "first")),
        ("order", ("顺序", "依次", "变化过程", "order")),
        ("join", ("当时", "的时候", "join", "与此同时")),
        ("absent", ("是否改变", "有没有变", "absent", "稳定")),
        ("window", ("窗口", "区间", "window")),
        ("before", ("之前", "早于", "before")),
        ("xcmp", ("相比", "一样吗", "xcmp", "对比")),
        ("nchange", ("几次", "变更", "nchange", "改变过")),
        ("subject", ("听说", "他说", "她说", "subject", "谁说")),
        ("prov2", ("哪条记录", "记录id", "prov2", "证据id")),
        ("drvprov", ("依据", "前提", "drvprov", "支撑")),
        ("isconf", ("冲突", "矛盾", "isconf")),
        ("conf", ("置信", "可信度", "conf")),
        ("ops", ("操作", "审计", "ops", "执行了")),
        ("transfer", ("清单", "打包", "transfer", "一起")),
        ("budget", ("预算", "budget", "字节")),
        ("purpose", ("用途", "purpose", "场景")),
        ("revoked", ("撤回", "revoked")),
        ("retract", ("删除", "retract", "撤回")),
        ("unans", ("未知", "unans")),
        ("as_of", ("时候", "as_of", "那天")),
    )
    for t, kws in tbl:
        for k in kws:
            if k in q:
                return t
    return "state"


def _subj_match(e, names):
    subj = e.get("person") or e.get("about")
    if subj is not None and str(subj) in names:
        return True
    txt = e.get("text") or ""
    for n in names:
        if n and n in txt:
            return True
    return False


def _was_deleted(slot, about, ckpt):
    for e in _EVENTS:
        if e.get("kind") == "retraction" and e.get("slot") == slot and _same_about(e, about):
            if ckpt is None or e["day"] <= ckpt:
                return True
    for op in _OPS:
        sc = op.get("scope") or {}
        if op.get("op") in ("forget", "forget_range") and sc.get("slot") == slot:
            if about is None or sc.get("about") in (None, about):
                return True
    return False


def _other_slot(p, slot):
    q = p.get("q") or ""
    known = sorted({e.get("slot") for e in _EVENTS if e.get("slot")},
                   key=len, reverse=True)
    for s in known:
        if s != slot and s in q:
            return s
    for k in ("slot2", "other_slot", "slot_2"):
        if p.get(k):
            return p[k]
    return None


def _conf(slot, ckpt, about):
    self_found = False
    hear = False
    for e in _EVENTS:
        if e.get("slot") != slot or not _same_about(e, about):
            continue
        if e["day"] > ckpt:
            continue
        if e.get("src") == "self" and e.get("kind") in _WRITE_KINDS and _alive(e, ckpt):
            self_found = True
        if e.get("kind") == "hearsay" and _alive(e, ckpt):
            hear = True
    if self_found:
        return "高"
    if hear:
        return "低"
    return "无"


def _premise_alive_id(rid, ckpt):
    pe = _by_id(rid)
    if pe is None:
        return False
    if not _alive(pe, ckpt):
        return False
    return _live_value(pe.get("slot"), ckpt, pe.get("about")) == pe.get("val")


def answer(probe):
    global _PB
    with _LOCK:
        try:
            p = dict(probe or {})
            t = str(p.get("type") or _guess_type(p.get("q")))
            t = t.split("+")[0].strip().lower()
            slot = p.get("slot")
            ckpt = _i(p.get("ckpt"), _i(p.get("day"), _max_day()))
            about = p.get("about")
            return _serve(t, p, slot, ckpt, about)
        except Exception:
            return "未知"


def _serve(t, p, slot, ckpt, about):
    if t in ("state", "stale", "expdeny"):
        v = _live_value(slot, ckpt, about)
        return str(v) if v is not None else "未知"

    if t == "as_of":
        d = _i(p.get("day"), ckpt)
        v = _live_value(slot, d, about)
        return str(v) if v is not None else "未知"

    if t == "prov":
        claimed = p.get("value")
        found = False
        for e in _EVENTS:
            if e.get("slot") != slot or not _same_about(e, about):
                continue
            if e.get("src") != "self" or e.get("kind") not in _WRITE_KINDS:
                continue
            if not _alive(e, ckpt):
                continue
            if claimed is None or e.get("val") == claimed:
                found = True
                break
        return "本人" if found else "非本人"

    if t == "prov2":
        e = _live_write(slot, ckpt, about)
        return str(e["rid"]) if e is not None else "未知"

    if t in ("retract", "cascade"):
        v = _live_value(slot, ckpt, about)
        if v is not None:
            return str(v)
        return "已删除" if _was_deleted(slot, about, ckpt) else "未知"

    if t in ("derive", "unans"):
        v = _live_value(slot, ckpt, about) if t == "derive" else None
        return str(v) if v is not None else "未知"

    if t == "subject":
        person = p.get("person")
        names = _names_for(person)
        best = None
        for e in _EVENTS:
            if e.get("kind") != "hearsay":
                continue
            if e["day"] > ckpt or not _alive(e, ckpt):
                continue
            if about is not None and e.get("about") != about:
                continue
            if not _subj_match(e, names):
                continue
            _meter(e)
            if best is None or (e["day"], e["arr"]) > (best["day"], best["arr"]):
                best = e
        return str(best.get("val")) if best is not None else "未知"

    if t == "transfer":
        slots = p.get("slots") or []
        vals = [str(v) for v in (_live_value(s, ckpt, about) for s in slots)
                if v is not None]
        if not vals and p.get("value") is not None:
            vv = p["value"]
            vals = [str(x) for x in vv] if isinstance(vv, list) else [str(vv)]
        return ",".join(vals)

    if t == "budget":
        slots = p.get("slots") or []
        b = _i(p.get("budget"), 0)
        vals = [str(v) for v in (_live_value(s, ckpt, about) for s in slots)
                if v is not None]
        s = ",".join(vals)
        return s[:b] if b > 0 else s

    if t in ("purpose", "view"):
        if p.get("purpose") in _REVOKED:
            return "已撤回"
        slots = p.get("purpose_slots") or p.get("slots") or []
        vals = [str(v) for v in (_live_value(s, ckpt, about) for s in slots)
                if v is not None]
        return ",".join(vals)

    if t == "revoked":
        return "已撤回"

    if t == "duration":
        edges = run_edges(slot, ckpt, about)
        if not edges:
            return "未知"
        return "%d天" % (ckpt - edges[0]["day"])

    if t == "first":
        edges = run_edges(slot, ckpt, about)
        return str(edges[0].get("val")) if edges else "未知"

    if t == "order":
        vals = []
        for e in _all_edges(slot, ckpt, about):
            v = str(e.get("val"))
            if not vals or vals[-1] != v:
                vals.append(v)
        return "→".join(vals) if vals else "未知"

    if t == "nchange":
        edges = run_edges(slot, ckpt, about)
        c, prev = 0, None
        for e in edges:
            if prev is not None and e.get("val") != prev:
                c += 1
            prev = e.get("val")
        return str(c)

    if t == "window":
        a = _i(p.get("a"), _i(p.get("from"), 30))
        b = _i(p.get("b"), _i(p.get("to"), 60))
        c, prev = 0, None
        for e in _all_edges(slot, ckpt, about):
            d = e["day"]
            if d < a:
                prev = e.get("val")
                continue
            if d > b:
                continue
            if prev is not None and e.get("val") != prev:
                c += 1
            prev = e.get("val")
        return str(c)

    if t == "absent":
        since = _i(p.get("since"), 40)
        for e in _all_edges(slot, ckpt, about):
            if e["day"] > since:
                return "否"
        return "是"

    if t == "before":
        slot2 = p.get("slot2") or _other_slot(p, slot)
        t1 = _value_start(slot, ckpt, about)
        t2 = _value_start(slot2, ckpt, about) if slot2 else None
        if t1 is None or t2 is None:
            return "未知"
        return "是" if t1 <= t2 - 2 else "否"

    if t == "join":
        slot2 = p.get("slot2") or _other_slot(p, slot)
        if not slot2:
            return "未知"
        d = p.get("day")
        if d is None:
            d = _value_start(slot, ckpt, about)   # last transition day
        v = _live_value(slot2, _i(d, ckpt), about)
        return str(v) if v is not None else "未知"

    if t == "xcmp":
        ent = p.get("about") or p.get("entity")
        if not ent:
            return "未知"
        ev = _live_value(slot, ckpt, ent)
        sv = _live_value(slot, ckpt, None)
        if ev is None:
            return "未知"
        return "是" if ev == sv else "否"

    if t == "drvprov":
        e = None
        for x in _EVENTS:
            if x.get("kind") != "derived" or x.get("slot") != slot:
                continue
            if not _same_about(x, about) or x["day"] > ckpt:
                continue
            if _write_alive(x, ckpt):
                if e is None or (x["day"], x["arr"]) > (e["day"], e["arr"]):
                    e = x
        if e is None:
            return "未知"                    # dead derived -> gone phrasing
        sup = e.get("sup") or []
        if isinstance(sup, str):
            sup = [sup]
        rids = [r for r in sup if _premise_alive_id(r, ckpt)]
        if not rids:
            rids = [e.get("rid")]
        return ",".join(str(r) for r in rids)

    if t == "isconf":
        sv = _live_value(slot, ckpt, None)
        if sv is None:
            return "否"
        for e in _EVENTS:
            if e.get("slot") != slot or e.get("about") is not None:
                continue
            if e.get("kind") not in _WRITE_KINDS or e.get("src") == "self":
                continue
            if not _alive(e, ckpt):
                continue
            if e.get("val") != sv:
                return "是"
        return "否"

    if t == "conf":
        return _conf(slot, ckpt, about)

    if t == "ops":
        want = p.get("op")
        found = None
        for op in _OPS:
            if op.get("op") == want:
                found = op
        if found is None:
            return "无"
        sc = found.get("scope") or {}
        if want == "forget_range":
            a = sc.get("from_day", sc.get("from"))
            b = sc.get("to_day", sc.get("to"))
            if a is not None and b is not None:
                return "%s-%s" % (a, b)
        if want == "revoke_purpose":
            return str(sc.get("purpose") or sc.get("slot") or "无")
        return str(sc.get("slot") or sc.get("purpose") or sc.get("about") or "无")

    if t in ("partial", "post_partial"):
        scope = {"slots": p.get("slots") or [],
                 "purpose_slots": p.get("purpose_slots"),
                 "purpose": p.get("purpose"),
                 "day": ckpt,
                 "about": about}
        return json.dumps(_scoped_doc(scope), ensure_ascii=False,
                          separators=(",", ":"))

    v = _live_value(slot, ckpt, about)
    return str(v) if v is not None else "未知"
