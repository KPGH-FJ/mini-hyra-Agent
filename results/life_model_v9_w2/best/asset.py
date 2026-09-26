#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Life Model asset: ingest -> serve/control -> export/import.

DELTA vs base: the serve layer is the product. One event-sourced journal
remains the truth, while answer() routes every probe type through explicit
serve decisions: live/run history, alias-merged attribution, premise
fixpoints, byte-budget packing, purpose refusal, scoped exports, and an
audit journal that survives state()->import_state(). Cost is metered, never
fabricated.
"""

import json
import threading

_LOCK = threading.RLock()

_ASSERT_KINDS = {"statement", "update", "correction"}
_GONE = "未知"
_DELETED = "已删除/未知"
_REVOKED = "已撤回"
_SOURCES = {"self", "other", "assistant", "device", "doc", "inference", "system"}


def _norm(v):
    if v is None:
        return None
    if isinstance(v, (dict, list, tuple, set)):
        try:
            return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return str(v)
    s = str(v).strip()
    return s if s != "" else None


def _lkey(v):
    s = _norm(v)
    return None if s is None else s.lower()


def _same(a, b):
    return _norm(a) == _norm(b)


def _to_day(v, default=0):
    if v is None:
        return default
    try:
        return int(float(str(v).strip()))
    except Exception:
        pass
    digits = "".join(ch for ch in str(v) if ch.isdigit() or (ch == "-" and digits == ""))
    try:
        return int(digits) if digits not in ("", "-") else default
    except Exception:
        return default


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        out = []
        for x in v:
            n = _norm(x)
            if n is not None:
                out.append(n)
        return out
    s = _norm(v)
    if s is None:
        return []
    if "," in s:
        return [x.strip() for x in s.split(",") if x.strip()]
    return [s]


def _jsonable(obj):
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return {"_str": str(obj)}


class Asset:
    def __init__(self):
        self.events = []
        self.aliases = {}
        self.journal = []
        self.purposes = {}
        self.current_day = 0
        self.first_day = 0
        self._pb = 0
        self._llm = 0
        self._op_seq = 0
        self._consulted = []

    # ---------------- ingest ----------------

    def ingest(self, rec):
        with _LOCK:
            if not isinstance(rec, dict):
                return
            e = {}
            for k in ("id", "day", "source", "kind", "slot", "value", "text",
                      "expires_day", "about", "person", "subject", "supports",
                      "premises", "purpose", "purpose_slots", "op", "arrival"):
                if k in rec and rec[k] is not None:
                    e[k] = rec[k]
            e["day"] = _to_day(e.get("day"), 0)
            e["arrival"] = len(self.events)
            if e.get("id") is None:
                e["id"] = "e%03d" % e["arrival"]
            if e.get("supports") is None and e.get("premises") is not None:
                e["supports"] = e["premises"]
            if e.get("supports") is not None:
                e["supports"] = _as_list(e["supports"])
            if "expires_day" in e and e["expires_day"] is not None:
                e["expires_day"] = _to_day(e["expires_day"], None)
            self.events.append(e)

            self.current_day = max(self.current_day, e["day"])
            self.first_day = min(self.first_day, e["day"]) if self.events else e["day"]

            if _lkey(e.get("kind")) == "alias" and _lkey(e.get("source")) == "system":
                a = _norm(e.get("slot"))
                c = _norm(e.get("value"))
                if a and c:
                    self.aliases[a] = c

            pur = _norm(e.get("purpose"))
            if pur and e.get("purpose_slots") is not None:
                slots = _as_list(e.get("purpose_slots"))
                cur = self.purposes.setdefault(pur, {"slots": slots, "revoked": False})
                if slots:
                    cur["slots"] = slots

    # ---------------- control ops ----------------

    def _journal(self, op, **kw):
        self._op_seq += 1
        entry = {"op": _lkey(op), "seq": self._op_seq, "day": kw.pop("day", self.current_day)}
        entry.update(kw)
        entry["scope"] = _jsonable(kw.get("scope", {}))
        self.journal.append(entry)
        return entry

    def forget(self, scope=None):
        with _LOCK:
            scope = scope or {}
            if not isinstance(scope, dict):
                scope = {"slot": _norm(scope)}
            if (scope.get("from") is not None or scope.get("start") is not None) and scope.get("to") is not None:
                a = _to_day(scope.get("from", scope.get("start")))
                b = _to_day(scope.get("to"))
                self._forget_range(a, b, scope)
                return
            slots = [x for x in _as_list(scope.get("slots") if scope.get("slots") is not None else scope.get("slot")) if x]
            about = _norm(scope.get("about"))
            self._journal("forget", slot=slots[0] if len(slots) == 1 else None,
                          slots=slots, about=about, scope=scope, day=_to_day(scope.get("day"), self.current_day))
            if about:
                self._erase(lambda e: _same(self._about(e), about))
            elif slots:
                self._erase(lambda e: self._slot(e) in slots)

    def _forget_range(self, a, b, scope=None):
        a, b = _to_day(a), _to_day(b)
        if a > b:
            a, b = b, a
        self._journal("forget_range", frm=a, to=b, range="%d-%d" % (a, b),
                      scope=scope or {"from": a, "to": b}, day=b)
        self._erase(lambda e: a <= _to_day(e.get("day"), 0) <= b)

    def forget_range(self, start, end):
        with _LOCK:
            self._forget_range(start, end)

    def correct(self, slot, value):
        with _LOCK:
            slot = _norm(slot)
            if slot is None:
                return
            day = self.current_day
            e = {"id": "correct-%d" % (self._op_seq + 1), "day": day, "arrival": len(self.events),
                 "source": "self", "kind": "correction", "slot": slot, "value": value}
            self.events.append(e)
            self._journal("correct", slot=slot, value=value, day=day)
            self.current_day = max(self.current_day, day)

    def revoke_purpose(self, purpose):
        with _LOCK:
            pur = _norm(purpose)
            if pur is None:
                return
            cur = self.purposes.setdefault(pur, {"slots": [], "revoked": False})
            cur["revoked"] = True
            self._journal("revoke_purpose", purpose=pur, scope={"purpose": pur}, day=self.current_day)

    # ---------------- erasure / rebuild ----------------

    def _find_event(self, eid):
        n = _norm(eid)
        if n is None:
            return None
        for e in self.events:
            if _same(e.get("id"), n):
                return e
        return None

    def _erase(self, pred):
        changed = True
        while changed:
            changed = False
            ids = {_norm(e.get("id")) for e in self.events}
            new_events = []
            for e in self.events:
                if pred(e):
                    changed = True
                    continue
                if _lkey(e.get("kind")) == "derived" and self._support_killed(e, ids, pred):
                    changed = True
                    continue
                new_events.append(e)
            self.events[:] = new_events

    def _support_killed(self, e, ids, pred):
        for sid in _as_list(e.get("supports")):
            s = self._find_event(sid)
            if s is None or s is e:
                return True
            if _norm(s.get("id")) not in ids:
                return True
            if pred(s):
                return True
            if _lkey(s.get("kind")) == "derived" and self._support_killed(s, ids, pred):
                return True
        return False

    # ---------------- accessors ----------------

    def _slot(self, e):
        return _norm(e.get("slot"))

    def _value(self, e):
        return _norm(e.get("value"))

    def _about(self, e):
        return _norm(e.get("about"))

    def _person(self, e):
        p = _norm(e.get("person"))
        if p is None:
            p = _norm(e.get("subject"))
        if p is None:
            src = _lkey(e.get("source"))
            if src not in _SOURCES and src not in (None, "self"):
                p = _norm(e.get("source"))
        return p

    def _kind(self, e):
        return _lkey(e.get("kind"))

    def _source(self, e):
        return _lkey(e.get("source"))

    def _expired(self, e, day):
        return e.get("expires_day") is not None and _to_day(day, 0) > _to_day(e.get("expires_day"), 0)

    def _sorted(self, events=None):
        evs = list(self.events if events is None else events)
        return sorted(evs, key=lambda e: (_to_day(e.get("day"), 0), _to_day(e.get("arrival"), 0)))

    def _by_id(self, events=None):
        return {_norm(e.get("id")): e for e in (events if events is not None else self.events) if _norm(e.get("id")) is not None}

    def _canonical(self, name):
        n = _norm(name)
        if n is None:
            return None
        seen = set()
        cur = n
        for _ in range(12):
            if cur in seen:
                break
            seen.add(cur)
            nxt = self.aliases.get(cur)
            if nxt is None:
                break
            cur = nxt
        return cur

    def _note(self, obj):
        if obj is not None:
            self._consulted.append(obj)

    def _meter(self, obj):
        try:
            b = len(json.dumps(obj, ensure_ascii=False, default=str))
        except Exception:
            b = len(str(obj))
        self._pb += max(2, b)

    # ---------------- live state / premises ----------------

    def _live_map(self, day, about=None, self_only=True):
        day = _to_day(day, self.current_day)
        evs = self._sorted()
        live = {}
        retracted = set()
        for e in evs:
            if _to_day(e.get("day"), 0) > day:
                continue
            if about is None:
                if self._about(e) is not None:
                    continue
            elif not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            k = self._slot(e)
            if k is None:
                continue
            if self._kind(e) == "retraction":
                live.pop(k, None)
                retracted.add(k)
                continue
            if self._kind(e) not in _ASSERT_KINDS:
                continue
            if self_only and self._source(e) != "self":
                continue
            if self._expired(e, day):
                continue
            live[k] = {"value": self._value(e), "id": _norm(e.get("id")),
                       "day": _to_day(e.get("day"), 0), "kind": self._kind(e),
                       "expires": e.get("expires_day")}

        ctx = {"day": day, "evs": evs, "by_id": self._by_id(evs), "live": live,
               "retracted": retracted, "memo": {}, "visiting": set(), "self_only": self_only}
        for e in evs:
            if self._kind(e) != "derived" or self._expired(e, day):
                continue
            if about is None:
                if self._about(e) is not None:
                    continue
            elif not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            k = self._slot(e)
            if k is None or _to_day(e.get("day"), 0) > day:
                continue
            if self._derived_alive(e, ctx):
                live[k] = {"value": self._value(e), "id": _norm(e.get("id")),
                           "day": _to_day(e.get("day"), 0), "kind": "derived",
                           "expires": e.get("expires_day")}
        return live

    def _diverged(self, support, derived, evs, day, self_only):
        sk = self._slot(support)
        sv = self._value(support)
        if sk is None or sv is None:
            return True
        for x in evs:
            if _to_day(x.get("day"), 0) <= _to_day(derived.get("day"), 0):
                continue
            if _to_day(x.get("day"), 0) > _to_day(day, 0):
                continue
            if self._slot(x) != sk or self._kind(x) not in _ASSERT_KINDS:
                continue
            if self_only and self._source(x) != "self":
                continue
            if not _same(self._value(x), sv):
                return True
        return False

    def _derived_alive(self, e, ctx):
        key = (_norm(e.get("id")), _to_day(ctx["day"], 0), bool(ctx["self_only"]))
        if key in ctx["memo"]:
            return ctx["memo"][key]
        if key in ctx["visiting"]:
            return False
        ctx["visiting"].add(key)
        result = self._derived_alive_impl(e, ctx)
        ctx["visiting"].discard(key)
        ctx["memo"][key] = result
        return result

    def _derived_alive_impl(self, e, ctx):
        day = ctx["day"]
        if self._expired(e, day):
            return False
        sups = _as_list(e.get("supports"))
        if not sups:
            return False
        for sid in sups:
            s = ctx["by_id"].get(_norm(sid))
            if s is None or s is e:
                return False
            if (_to_day(s.get("day"), 0), _to_day(s.get("arrival"), 0)) > (_to_day(e.get("day"), 0), _to_day(e.get("arrival"), 0)):
                return False
            if self._kind(s) == "retraction":
                return False
            sk = self._slot(s)
            if sk is None:
                return False
            if sk in ctx["retracted"]:
                return False
            if self._kind(s) in _ASSERT_KINDS:
                if ctx["self_only"] and self._source(s) != "self":
                    return False
                if self._expired(s, day):
                    return False
                if sk not in ctx["live"] or not _same(ctx["live"][sk]["value"], self._value(s)):
                    return False
                if self._diverged(s, e, ctx["evs"], day, ctx["self_only"]):
                    return False
            elif self._kind(s) == "derived":
                if self._expired(s, day):
                    return False
                if not self._derived_alive(s, ctx):
                    return False
                val = ctx["live"][sk]["value"] if sk in ctx["live"] else self._value(s)
                if not _same(val, self._value(s)):
                    return False
                if self._diverged(s, e, ctx["evs"], day, ctx["self_only"]):
                    return False
            else:
                if sk not in ctx["live"] or not _same(ctx["live"][sk]["value"], self._value(s)):
                    return False
        return True

    def _current(self, slot, day=None, about=None, self_only=None):
        if slot is None:
            return None
        day = self.current_day if day is None else day
        if about is None:
            m = self._live_map(day, None, self_only=True if self_only is None else self_only)
        else:
            m = self._live_map(day, about, self_only=False if self_only is None else self_only)
        cur = m.get(_norm(slot))
        if cur:
            self._note(cur.get("id"))
        return cur

    # ---------------- history runs ----------------

    def _run_values(self, slot, day=None, about=None, self_only=True):
        slot = _norm(slot)
        day = self.current_day if day is None else _to_day(day)
        evs = self._sorted()
        last_retract = -1
        for i, e in enumerate(evs):
            if _to_day(e.get("day"), 0) > day:
                continue
            if about is None:
                if self._about(e) is not None:
                    continue
            elif not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            if self._slot(e) != slot or self._kind(e) != "retraction":
                continue
            last_retract = i
        bucket = {}
        for e in evs[last_retract + 1:]:
            if _to_day(e.get("day"), 0) > day or self._slot(e) != slot:
                continue
            if about is None:
                if self._about(e) is not None:
                    continue
            elif not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            if self._expired(e, day):
                continue
            if self._kind(e) in _ASSERT_KINDS:
                if self_only and self._source(e) != "self":
                    continue
            elif self._kind(e) != "derived":
                continue
            bucket[_to_day(e.get("day"), 0)] = e
        out = []
        for d in sorted(bucket):
            e = bucket[d]
            self._note(e.get("id"))
            out.append({"value": self._value(e), "day": d, "id": _norm(e.get("id")), "kind": self._kind(e)})
        return out

    # ---------------- attribution ----------------

    def _subject_value(self, person, slot=None, about=None, day=None):
        p = self._canonical(person)
        if p is None:
            return None
        day = self.current_day if day is None else _to_day(day)
        best = None
        for e in self._sorted():
            if _to_day(e.get("day"), 0) > day or self._kind(e) != "hearsay":
                continue
            if not _same(self._canonical(self._person(e)), p):
                continue
            if about is not None and not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            if slot is not None and self._slot(e) != _norm(slot):
                continue
            if self._expired(e, day):
                continue
            if best is None or (_to_day(e.get("day"), 0), _to_day(e.get("arrival"), 0)) > (_to_day(best.get("day"), 0), _to_day(best.get("arrival"), 0)):
                best = e
        if best is None:
            return None
        self._note(best.get("id"))
        return self._value(best)

    # ---------------- evidence/confidence ----------------

    def _has_self_assertion(self, slot, about=None, value=None):
        slot = _norm(slot)
        for e in self._sorted():
            if self._kind(e) not in _ASSERT_KINDS or self._slot(e) != slot:
                continue
            if self._source(e) != "self":
                continue
            if about is None:
                if self._about(e) is not None:
                    continue
            elif not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            if value is not None and not _same(self._value(e), value):
                continue
            self._note(e.get("id"))
            return True
        return False

    def _has_any_claim(self, slot, about=None):
        slot = _norm(slot)
        for e in self._sorted():
            if self._slot(e) != slot:
                continue
            if about is None:
                if self._about(e) is not None:
                    continue
            elif not _same(self._canonical(self._about(e)), self._canonical(about)):
                continue
            if self._kind(e) in _ASSERT_KINDS or self._kind(e) == "hearsay":
                self._note(e.get("id"))
                return True
        return False

    # ---------------- serve helpers ----------------

    def _purpose_revoked(self, purpose):
        p = _norm(purpose)
        return p is not None and bool(self.purposes.get(p, {}).get("revoked", False))

    def _purpose_slots(self, purpose):
        p = _norm(purpose)
        return list(self.purposes.get(p, {}).get("slots", []) or [])

    def _bundle(self, slots, day, values=None):
        day = self.current_day if day is None else day
        m = self._live_map(day, None, True)
        out = []
        for s in slots:
            cur = m.get(_norm(s))
            if cur and cur.get("value") is not None:
                out.append(cur["value"])
                self._note(cur.get("id"))
        if not out and values:
            allvals = {v["value"] for v in m.values() if v.get("value") is not None}
            out = [v for v in values if v in allvals]
        return ",".join(out) if out else _GONE

    def _journal_answer(self, op):
        op = _lkey(op)
        if op is None:
            return "无"
        entries = [j for j in self.journal if _lkey(j.get("op")) == op]
        if not entries:
            self._note("journal:%s:none" % op)
            return "无"
        j = entries[-1]
        self._note("journal:%s" % j.get("seq"))
        if op == "forget_range":
            return "%s-%s" % (_to_day(j.get("frm"), 0), _to_day(j.get("to"), 0))
        if j.get("slot"):
            return _norm(j.get("slot"))
        slots = _as_list(j.get("slots"))
        if slots:
            return ",".join(slots)
        if j.get("about"):
            return "about:%s" % _norm(j.get("about"))
        if j.get("purpose"):
            return _norm(j.get("purpose"))
        if j.get("range"):
            return _norm(j.get("range"))
        return "无"

    def _scoped_doc(self, scope=None):
        scope = {} if scope is None else scope
        if not isinstance(scope, dict):
            if isinstance(scope, (list, tuple, set)):
                scope = {"slots": list(scope)}
            else:
                scope = {"slot": _norm(scope)}
        purpose = _norm(scope.get("purpose"))
        if purpose is not None and self._purpose_revoked(purpose):
            return {}
        slots = _as_list(scope.get("slots"))
        if not slots and scope.get("slot") is not None:
            slots = [_norm(scope.get("slot"))]
        if not slots and purpose is not None:
            slots = self._purpose_slots(purpose)
        about = _norm(scope.get("about"))
        day = scope.get("day", scope.get("ckpt", self.current_day))
        if about is not None:
            m = self._live_map(day, about, self_only=False)
        else:
            m = self._live_map(day, None, self_only=True)
        doc = {}
        for s in slots:
            cur = m.get(_norm(s))
            if cur and cur.get("value") is not None:
                doc[s] = cur["value"]
                self._note(cur.get("id"))
        return doc

    # ---------------- main serve router ----------------

    def answer(self, probe):
        with _LOCK:
            self._consulted = []
            try:
                out = self._answer(probe or {})
            except Exception:
                out = _GONE
            try:
                self._meter(self._consulted if self._consulted else ["none"])
            except Exception:
                self._pb += 2
            return out

    def _answer(self, p):
        typ = _lkey(p.get("type")) or self._infer_type(p.get("q") or p.get("question") or "")
        ckpt = _to_day(p.get("ckpt", p.get("day")), self.current_day)
        if typ in ("partial", "post_partial"):
            scope = dict(p.get("scope") or {})
            for k in ("slots", "slot", "purpose", "about", "day", "ckpt"):
                if k in p and k not in scope:
                    scope[k] = p[k]
            return json.dumps(self._scoped_doc(scope), ensure_ascii=False)

        if typ == "revoked":
            return _REVOKED if self._purpose_revoked(p.get("purpose")) else "无"

        if typ == "purpose":
            pur = _norm(p.get("purpose"))
            if pur is not None and self._purpose_revoked(pur):
                return _REVOKED
            slots = _as_list(p.get("purpose_slots")) or self._purpose_slots(pur)
            return self._bundle(slots, ckpt)

        if typ in ("budget", "transfer"):
            slots = _as_list(p.get("slots"))
            vals = _as_list(p.get("value")) if typ == "transfer" else None
            return self._bundle(slots, ckpt, vals)

        if typ == "ops":
            return self._journal_answer(p.get("op"))

        if typ == "duration":
            return str(self._duration_answer(p, ckpt))

        if typ == "nchange":
            return str(self._nchange_answer(p, ckpt))

        if typ == "first":
            run = self._run_values(p.get("slot"), ckpt)
            return run[0]["value"] if run else _GONE

        if typ == "order":
            run = self._run_values(p.get("slot"), ckpt)
            vals = []
            for x in run:
                if not vals or vals[-1] != x["value"]:
                    vals.append(x["value"])
            return "→".join(vals) if vals else _GONE

        if typ == "join":
            return self._join_answer(p, ckpt)

        if typ == "absent":
            return self._absent_answer(p, ckpt)

        if typ == "window":
            return self._window_answer(p, ckpt)

        if typ == "xcmp":
            return self._xcmp_answer(p, ckpt)

        if typ == "isconf":
            return self._isconf_answer(p, ckpt)

        if typ == "conf":
            return self._conf_answer(p, ckpt)

        if typ == "prov2":
            cur = self._current(p.get("slot"), ckpt, p.get("about"))
            return cur.get("id") if cur else "无"

        if typ == "drvprov":
            return self._drvprov_answer(p, ckpt)

        if typ == "prov":
            return "本人" if self._has_self_assertion(p.get("slot"), p.get("about"), p.get("value")) else "非本人"

        if typ == "subject":
            v = self._subject_value(p.get("person"), p.get("slot"), p.get("about"), ckpt)
            return v if v is not None else _GONE

        if typ == "as_of":
            day = _to_day(p.get("day"), ckpt)
            cur = self._current(p.get("slot"), day, p.get("about"))
            return cur.get("value") if cur else _GONE

        if typ == "retract":
            return self._retract_answer(p, ckpt)

        if typ == "unans":
            return _GONE

        if typ == "expdeny":
            cur = self._current(p.get("slot"), ckpt, p.get("about"))
            return cur.get("value") if cur else _GONE

        if typ in ("state", "stale", "cascade", "derive", "post_import"):
            return self._state_answer(p, ckpt)

        return _GONE

    def _state_answer(self, p, day):
        about = p.get("about")
        if about is None:
            cur = self._current(p.get("slot"), day, None, True)
        else:
            cur = self._current(p.get("slot"), day, about, False)
        return cur.get("value") if cur else _GONE

    def _retract_answer(self, p, day):
        slot = _norm(p.get("slot"))
        cur = self._current(slot, day, p.get("about"))
        if cur:
            return cur.get("value")
        deleted = any(self._slot(e) == slot and self._kind(e) == "retraction" for e in self.events)
        if not deleted and any(_lkey(j.get("op")) == "forget" and slot in _as_list(j.get("slots")) for j in self.journal):
            deleted = True
        return _DELETED if deleted else _GONE

    def _duration_answer(self, p, ckpt):
        slot = _norm(p.get("slot"))
        if slot:
            run = self._run_values(slot, ckpt)
            start = run[0]["day"] if run else self.first_day
        else:
            start = self.first_day
        return max(0, _to_day(ckpt, self.current_day) - _to_day(start, 0))

    def _nchange_answer(self, p, ckpt):
        run = self._run_values(p.get("slot"), ckpt)
        n = 0
        prev = None
        for x in run:
            if prev is not None and x["value"] != prev:
                n += 1
            prev = x["value"]
        return n

    def _join_answer(self, p, ckpt):
        slot = _norm(p.get("slot"))
        other = p.get("slot2") or p.get("other_slot") or p.get("other")
        if other is None:
            slots = _as_list(p.get("slots"))
            if len(slots) >= 2:
                other = slots[1]
        cur = self._current(slot, ckpt)
        if not cur:
            return _GONE
        other_cur = self._current(other, cur["day"])
        return other_cur.get("value") if other_cur else _GONE

    def _absent_answer(self, p, ckpt):
        slot = _norm(p.get("slot"))
        if slot:
            run = self._run_values(slot, ckpt)
            bad = any(x["day"] > 40 for x in run)
        else:
            bad = any(_to_day(e.get("day"), 0) > 40 for e in self.events if self._kind(e) in _ASSERT_KINDS)
        return "否" if bad else "是"

    def _window_answer(self, p, ckpt):
        run = self._run_values(p.get("slot"), ckpt)
        lo, hi = 30, 60
        if p.get("from") is not None:
            lo = _to_day(p.get("from"), lo)
        if p.get("to") is not None:
            hi = _to_day(p.get("to"), hi)
        if p.get("start") is not None:
            lo = _to_day(p.get("start"), lo)
        if p.get("end") is not None:
            hi = _to_day(p.get("end"), hi)
        prev = None
        out = []
        for x in run:
            if x["day"] < lo:
                prev = x["value"]
            elif lo <= x["day"] <= hi:
                if prev is None or x["value"] != prev:
                    out.append(x["value"])
                prev = x["value"]
        if not out:
            if prev is not None:
                out.append(prev)
            elif run:
                out.append(run[0]["value"])
        return "→".join(out) if out else _GONE

    def _xcmp_answer(self, p, ckpt):
        slot = _norm(p.get("slot"))
        about = _norm(p.get("about"))
        if slot is None or about is None:
            return _GONE
        mine = self._current(slot, ckpt, None, True)
        theirs = self._current(slot, ckpt, about, False)
        if not mine or not theirs:
            return _GONE
        return "是" if _same(mine.get("value"), theirs.get("value")) else "否"

    def _isconf_answer(self, p, ckpt):
        slot = _norm(p.get("slot"))
        mine = self._current(slot, ckpt, None, True)
        if not slot:
            return "否"
        for e in self._sorted():
            if _to_day(e.get("day"), 0) > ckpt or self._slot(e) != slot or self._about(e) is not None:
                continue
            if self._kind(e) not in _ASSERT_KINDS and self._kind(e) != "hearsay":
                continue
            if self._source(e) == "self" or self._kind(e) == "suggestion":
                continue
            if mine and _same(self._value(e), mine.get("value")):
                continue
            self._note(e.get("id"))
            return "是"
        return "否"

    def _conf_answer(self, p, ckpt):
        slot = _norm(p.get("slot"))
        about = _norm(p.get("about"))
        mine = self._current(slot, ckpt, about, True if about is None else False)
        if mine:
            return "高"
        if self._has_any_claim(slot, about):
            return "低"
        return "无"

    def _drvprov_answer(self, p, ckpt):
        cur = self._current(p.get("slot"), ckpt, p.get("about"))
        if not cur:
            return "无"
        if cur.get("kind") != "derived":
            return cur.get("id") or "无"
        e = self._find_event(cur.get("id"))
        if e is None:
            return cur.get("id") or "无"
        m = self._live_map(ckpt, self._about(e), self_only=False)
        ids = []
        for sid in _as_list(e.get("supports")):
            s = self._find_event(sid)
            if s is None:
                continue
            k = self._slot(s)
            if k and k in m and _same(m[k].get("value"), self._value(s)):
                ids.append(_norm(s.get("id")))
        return ",".join(ids) if ids else "无"

    def _infer_type(self, q):
        s = _lkey(q)
        if not s:
            return None
        table = [
            ("as_of", ("as_of", "当时", "那天")),
            ("subject", ("subject", "听说", " attributed")),
            ("prov", ("prov", "本人")),
            ("prov2", ("prov2", "record id", "记录")),
            ("budget", ("budget", "预算")),
            ("transfer", ("transfer", "打包")),
            ("purpose", ("purpose", "视图")),
            ("revoked", ("revoked", "撤回")),
            ("ops", ("ops", "操作")),
            ("duration", ("duration", "时长")),
            ("nchange", ("nchange", "变更次数")),
            ("first", ("first", "首个")),
            ("order", ("order", "顺序")),
            ("join", ("join", "交叉")),
            ("absent", ("absent", "稳定")),
            ("window", ("window", "窗口")),
            ("xcmp", ("xcmp", "实体比较")),
            ("isconf", ("isconf", "冲突")),
            ("conf", ("conf", "置信")),
            ("partial", ("partial", "导出")),
            ("retract", ("retract", "删除")),
            ("cascade", ("cascade", "级联")),
            ("derive", ("derive", "派生")),
            ("unans", ("unans", "无法回答")),
        ]
        for t, keys in table:
            if any(k in s for k in keys):
                return t
        return None

    # ---------------- export/import ----------------

    def state(self, scope=None):
        with _LOCK:
            if scope is not None:
                return self._scoped_doc(scope)
            return {
                "version": 4,
                "events": _jsonable(self.events),
                "aliases": _jsonable(self.aliases),
                "journal": _jsonable(self.journal),
                "purposes": _jsonable(self.purposes),
                "current_day": self.current_day,
                "first_day": self.first_day,
                "probe_bytes": self._pb,
                "llm_tokens": self._llm,
            }

    def import_state(self, d):
        with _LOCK:
            if not isinstance(d, dict):
                return
            if isinstance(d.get("state"), dict):
                d = d["state"]
            evs = d.get("events", d.get("records"))
            if evs is None and isinstance(d.get("slots"), dict):
                evs = []
                for i, (k, v) in enumerate(d["slots"].items()):
                    evs.append({"id": "import-%d" % i, "day": 0, "arrival": i, "source": "self",
                                "kind": "statement", "slot": k, "value": v})
            if evs is not None:
                self.events = []
                for i, e in enumerate(evs):
                    if not isinstance(e, dict):
                        continue
                    x = dict(e)
                    x["day"] = _to_day(x.get("day"), 0)
                    x["arrival"] = _to_day(x.get("arrival"), i)
                    if x.get("supports") is None and x.get("premises") is not None:
                        x["supports"] = x["premises"]
                    if x.get("supports") is not None:
                        x["supports"] = _as_list(x["supports"])
                    self.events.append(x)
            self.aliases = dict(d.get("aliases", d.get("alias_map", {})) or {})
            self.journal = _jsonable(d.get("journal", [])) or []
            pur = d.get("purposes", {})
            if isinstance(pur, dict):
                self.purposes = {}
                for k, v in pur.items():
                    if isinstance(v, dict):
                        self.purposes[_norm(k)] = {"slots": _as_list(v.get("slots", [])), "revoked": bool(v.get("revoked", False))}
                    else:
                        self.purposes[_norm(k)] = {"slots": _as_list(v), "revoked": False}
            self.current_day = _to_day(d.get("current_day"), 0)
            self.first_day = _to_day(d.get("first_day"), 0)
            self._pb = _to_day(d.get("probe_bytes"), self._pb)
            self._llm = _to_day(d.get("llm_tokens"), 0)
            self._op_seq = max(self._op_seq, len(self.journal))
            for e in self.events:
                if _lkey(e.get("kind")) == "alias" and _lkey(e.get("source")) == "system":
                    a, c = _norm(e.get("slot")), _norm(e.get("value"))
                    if a and c:
                        self.aliases[a] = c
            self._consulted = []

    def probe_bytes(self):
        with _LOCK:
            return self._pb

    def stats(self):
        with _LOCK:
            try:
                asset_bytes = len(json.dumps(self.state(), ensure_ascii=False, default=str))
            except Exception:
                asset_bytes = len(str(self.state()))
            return {
                "asset_bytes": asset_bytes,
                "probe_bytes": self._pb,
                "llm_tokens": self._llm,
                "events": len(self.events),
                "journal_ops": len(self.journal),
                "revoked_purposes": [p for p, v in self.purposes.items() if v.get("revoked")],
            }


_A = Asset()

def ingest(rec):
    _A.ingest(rec)

def answer(probe):
    return _A.answer(probe)

def forget(scope=None):
    _A.forget(scope)

def forget_range(start, end):
    _A.forget_range(start, end)

def correct(slot, value):
    _A.correct(slot, value)

def revoke_purpose(purpose):
    _A.revoke_purpose(purpose)

def state(scope=None):
    return _A.state(scope)

def import_state(d):
    _A.import_state(d)

def probe_bytes():
    return _A.probe_bytes()

def stats():
    return _A.stats()
