# -*- coding: utf-8 -*-
"""Life Model asset: M5 control semantics on top of a temporal edge store."""
import json
import re

WRITE_KINDS = ("statement", "update", "correction", "derived", "correct")


def _new():
    return {"recs": [], "journal": [], "revoked": [], "forgotten_slots": [],
            "forgotten_about": [], "probe_bytes": 0, "seq": 0}


_S = _new()
_AM = None
_AK = None


def _norm(v):
    if v is None:
        return ""
    return re.sub(r"\s+", "", str(v)).lower()


def _sup(r):
    s = r.get("supports")
    if not s:
        return []
    if isinstance(s, str):
        return [s]
    try:
        return [str(x) for x in s]
    except Exception:
        return []


def _alias_map():
    global _AM, _AK
    key = (len(_S["recs"]), _S["seq"])
    if _AM is not None and _AK == key:
        return _AM
    m = {}
    for r in _S["recs"]:
        if r.get("kind") == "alias" or r.get("slot") == "alias":
            canon = str(r.get("value"))
            txt = " ".join(str(r.get(k) or "") for k in ("text", "value", "slot", "id"))
            if r.get("alias"):
                txt += " " + str(r["alias"])
            for n in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·]+", txt):
                if n and n != canon:
                    m.setdefault(n, canon)
            m.setdefault(canon, canon)
    _AM, _AK = m, key
    return m


def _canon(x):
    if x is None:
        return None
    return _alias_map().get(str(x), str(x))


def _names():
    m = _alias_map()
    s = set(m.keys())
    s.update(m.values())
    return s


def _write_ok(r):
    k = r.get("kind")
    src = r.get("source")
    if k == "derived":
        return src == "inference"
    if k not in ("statement", "update", "correction", "correct"):
        return False
    if r.get("about") is None:
        return src == "self"
    return True


# ------------------------------------------------------------------ ingest
def ingest(rec):
    rec = rec or {}
    r = {}
    for k in ("id", "day", "source", "kind", "slot", "value", "text",
              "expires_day", "about", "supports"):
        r[k] = rec.get(k)
    try:
        r["day"] = int(r["day"])
    except Exception:
        r["day"] = 0
    if r.get("expires_day") is not None:
        try:
            r["expires_day"] = int(r["expires_day"])
        except Exception:
            r["expires_day"] = None
    _S["seq"] += 1
    r["arr"] = _S["seq"]
    _S["recs"].append(r)


def _remove_edges(pred):
    """Erase matching write edges, cascading to derived facts losing supports."""
    removed = set()
    first = True
    while True:
        again = False
        keep = []
        for r in _S["recs"]:
            dead = (first and pred(r)) or (
                r.get("kind") == "derived" and
                any(s in removed for s in _sup(r)))
            if dead:
                removed.add(r["id"])
                again = True
                continue
            keep.append(r)
        _S["recs"] = keep
        first = False
        if not again:
            break


def forget(scope):
    scope = scope or {}
    _S["seq"] += 1
    if scope.get("slot") is not None:
        slot = scope["slot"]
        if slot not in _S["forgotten_slots"]:
            _S["forgotten_slots"].append(slot)
        _remove_edges(lambda r: r.get("slot") == slot)
        _S["journal"].append({"op": "forget", "target": slot, "at": _S["seq"]})
    elif scope.get("about") is not None:
        a = _canon(scope["about"])
        if a not in _S["forgotten_about"]:
            _S["forgotten_about"].append(a)
        _remove_edges(lambda r: _canon(r.get("about")) == a)
        _S["journal"].append({"op": "forget", "target": a, "at": _S["seq"]})
    elif scope.get("day_gte") is not None or scope.get("day_lte") is not None:
        lo = scope.get("day_gte", -10 ** 9)
        hi = scope.get("day_lte", 10 ** 9)
        _remove_edges(lambda r: r.get("kind") in WRITE_KINDS and
                      lo <= r.get("day", 0) <= hi)
        _S["journal"].append({"op": "forget_range", "target": "%s~%s" % (lo, hi),
                              "at": _S["seq"]})


def correct(slot, value):
    _S["seq"] += 1
    day = max([r.get("day", 0) for r in _S["recs"]] or [0]) + 1
    _S["recs"].append({"id": "correct_%d" % _S["seq"], "day": day,
                       "source": "self", "kind": "correct", "slot": slot,
                       "value": value, "text": "", "about": None,
                       "supports": None, "arr": _S["seq"]})
    _S["journal"].append({"op": "correct", "target": slot, "at": _S["seq"]})


def revoke_purpose(purpose):
    _S["seq"] += 1
    if purpose not in _S["revoked"]:
        _S["revoked"].append(purpose)
    _S["journal"].append({"op": "revoke_purpose", "target": purpose,
                          "at": _S["seq"]})


# --------------------------------------------------- liveness / live value
def _alive_all(qday, max_day=None, consulted=None):
    recs = _S["recs"]
    if consulted is not None:
        for r in recs:
            consulted.add(r["id"])
    byid = {r["id"]: r for r in recs}
    retr = {}
    for r in recs:
        if r.get("kind") == "retraction":
            retr.setdefault((_canon(r.get("about")), r.get("slot")),
                            []).append((r.get("day", 0), r.get("arr", 0)))
    fs = set(_S["forgotten_slots"])
    fa = set(_S["forgotten_about"])

    def base(r):
        if r.get("slot") in fs:
            return False
        if _canon(r.get("about")) in fa:
            return False
        ex = r.get("expires_day")
        if ex is not None and qday is not None and qday > ex:
            return False
        if max_day is not None and r.get("day", 0) > max_day:
            return False
        for k in retr.get((_canon(r.get("about")), r.get("slot")), []):
            if k > (r.get("day", 0), r.get("arr", 0)):
                return False
        return True

    alive = {r["id"]: base(r) and _write_ok(r) for r in recs}
    livecache = {}

    def liveval(about, slot):
        key = (about, slot)
        if key in livecache:
            return livecache[key]
        best = None
        for r in recs:
            if not alive.get(r["id"]):
                continue
            if _canon(r.get("about")) != about or r.get("slot") != slot:
                continue
            k = (r.get("day", 0), r.get("arr", 0))
            if best is None or k > best[0]:
                best = (k, r)
        v = best[1]["value"] if best else None
        livecache[key] = v
        return v

    for _ in range(20):
        changed = False
        livecache.clear()
        for r in recs:
            if not alive.get(r["id"]):
                continue
            if r.get("kind") != "derived":
                continue
            ok = True
            for sid in _sup(r):
                sr = byid.get(sid)
                if sr is None or not alive.get(sr["id"]):
                    ok = False
                    break
                if sr.get("kind") in WRITE_KINDS and sr.get("slot"):
                    lv = liveval(_canon(sr.get("about")) or _canon(r.get("about")),
                                 sr["slot"])
                    if _norm(lv) != _norm(sr.get("value")):
                        ok = False
                        break
            if not ok:
                alive[r["id"]] = False
                changed = True
        if not changed:
            break
    return alive


def _live(slot, day, about=None, consulted=None, max_day=None):
    if slot is None:
        return None
    alive = _alive_all(day, max_day=max_day, consulted=consulted)
    about = _canon(about)
    best = None
    for r in _S["recs"]:
        if not alive.get(r["id"]):
            continue
        if r.get("slot") != slot or _canon(r.get("about")) != about:
            continue
        k = (r.get("day", 0), r.get("arr", 0))
        if best is None or k > best[0]:
            best = (k, r)
    return best[1] if best else None


def _history(slot, about=None, qday=None, consulted=None):
    alive = _alive_all(qday, consulted=consulted)
    about = _canon(about)
    seq = [(r.get("day", 0), r.get("arr", 0), r)
           for r in _S["recs"]
           if alive.get(r["id"]) and r.get("slot") == slot and
           _canon(r.get("about")) == about]
    seq.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in seq]


# ------------------------------------------------------------- subject help
def _hearsay_subject(r, names):
    if r.get("about"):
        return str(r["about"])
    s = str(r.get("slot") or "")
    t = str(r.get("text") or "")
    for n in sorted(names, key=len, reverse=True):
        if n and (n in s or n in t):
            return n
    for sep in (".", "。", "的", "：", ":", " ", "——"):
        if sep in s:
            head = s.split(sep)[0]
            if head:
                return head
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9·]{2,})", t)
    return m.group(1) if m else None


def _topic_match(r, slot):
    if not slot:
        return True
    return (str(slot) in str(r.get("slot") or "")) or (str(slot) in str(r.get("text") or ""))


# ------------------------------------------------------------------ answer
def answer(probe):
    probe = probe or {}
    consulted = set()
    try:
        res = _answer(probe, consulted)
    except Exception:
        res = "未知"
    try:
        _S["probe_bytes"] += sum(
            len(json.dumps(r, ensure_ascii=False))
            for r in _S["recs"] if r["id"] in consulted)
    except Exception:
        pass
    return res if isinstance(res, str) else "未知"


def _answer(probe, consulted):
    t = str(probe.get("type") or probe.get("q") or "")
    day = probe.get("ckpt")
    if day is None:
        day = probe.get("day")
    try:
        day = int(day)
    except Exception:
        day = 90
    slot = probe.get("slot")
    about = _canon(probe.get("about"))

    if t in ("state", "stale", ""):
        r = _live(slot, day, about, consulted)
        return str(r["value"]) if r is not None else "未知"

    if t in ("as_of", "asof", "at"):
        d = probe.get("day")
        try:
            d = int(d)
        except Exception:
            d = day
        r = _live(slot, d, about, consulted, max_day=d)
        return str(r["value"]) if r is not None else "未知"

    if t in ("retract", "deleted"):
        deleted = (slot in _S["forgotten_slots"]) or any(
            r.get("kind") == "retraction" and r.get("slot") == slot and
            _canon(r.get("about")) == about for r in _S["recs"])
        return "已删除" if deleted else "未知"

    if t in ("cascade", "derive", "unans", "unknown"):
        return "未知"

    if t == "prov":
        val = probe.get("value")
        for r in _S["recs"]:
            if (r.get("slot") == slot and r.get("source") == "self" and
                    r.get("about") is None and
                    r.get("kind") in ("statement", "update", "correction", "correct")):
                if _norm(r.get("value")) == _norm(val):
                    return "本人"
        return "非本人"

    if t == "prov2":
        r = _live(slot, day, about, consulted)
        return str(r["id"]) if r is not None else "未知"

    if t in ("transfer", "budget", "pack"):
        slots = probe.get("slots") or probe.get("purpose_slots") or []
        vals = []
        for s in slots:
            r = _live(s, day, about, consulted)
            if r is not None:
                vals.append(str(r["value"]))
        return ",".join(vals) if vals else "未知"

    if t in ("purpose", "revoked", "view"):
        pur = probe.get("purpose")
        if pur is not None and pur in _S["revoked"]:
            return "已撤回"
        slots = probe.get("purpose_slots") or probe.get("slots") or []
        vals = []
        for s in slots:
            r = _live(s, day, about, consulted)
            if r is not None:
                vals.append(str(r["value"]))
        return ",".join(vals) if vals else "未知"

    if t == "subject":
        pc = _canon(probe.get("person"))
        names = _names()
        pslot = probe.get("slot")
        cands = []
        for r in _S["recs"]:
            if probe.get("about") is not None:
                if _canon(r.get("about")) != _canon(probe.get("about")):
                    continue
                if _canon(r.get("source")) != pc:
                    continue
                if r.get("kind") not in ("hearsay", "statement", "update",
                                         "correction", "suggestion"):
                    continue
            else:
                if r.get("kind") != "hearsay":
                    continue
                if _canon(_hearsay_subject(r, names)) != pc:
                    continue
                ex = r.get("expires_day")
                if ex is not None and day > ex:
                    continue
            cands.append(r)
        if pslot:
            filtered = [r for r in cands if _topic_match(r, pslot)]
            if filtered:
                cands = filtered
        if not cands:
            return "未知"
        r = max(cands, key=lambda r: (r.get("day", 0), r.get("arr", 0)))
        for rid in [x["id"] for x in cands]:
            consulted.add(rid)
        return str(r.get("value"))

    if t == "nchange":
        seq = _history(slot, about, qday=day, consulted=consulted)
        n = 0
        prev = None
        for r in seq:
            if _norm(r.get("value")) != _norm(prev):
                n += 1
            prev = r.get("value")
        # first assertion creates state, later divergences are transitions
        return str(max(0, n - 1))

    if t == "conf":
        selfsaid = False
        heard = False
        for r in _S["recs"]:
            if _canon(r.get("about")) != about:
                continue
            if slot and r.get("slot") != slot:
                continue
            if r.get("source") == "self" and r.get("kind") in (
                    "statement", "update", "correction", "correct"):
                selfsaid = True
            if r.get("kind") == "hearsay":
                heard = True
            consulted.add(r["id"])
        return "高" if selfsaid else ("低" if heard else "无")

    if t == "ops":
        op = probe.get("op")
        targets = [j["target"] for j in _S["journal"] if j.get("op") == op]
        return ",".join(dict.fromkeys(targets)) if targets else "无"

    if t == "journal":
        return json.dumps(_S["journal"], ensure_ascii=False)

    r = _live(slot, day, about, consulted)
    return str(r["value"]) if r is not None else "未知"


# ------------------------------------------------------------- state / io
def state():
    return {"recs": _S["recs"], "journal": _S["journal"],
            "revoked": list(_S["revoked"]),
            "forgotten_slots": list(_S["forgotten_slots"]),
            "forgotten_about": list(_S["forgotten_about"]),
            "probe_bytes": _S["probe_bytes"], "seq": _S["seq"]}


def import_state(d):
    global _AM, _AK
    d = d or {}
    _S["recs"] = [dict(r) for r in d.get("recs", [])]
    _S["journal"] = list(d.get("journal", []))
    _S["revoked"] = list(d.get("revoked", []))
    _S["forgotten_slots"] = list(d.get("forgotten_slots", []))
    _S["forgotten_about"] = list(d.get("forgotten_about", []))
    try:
        _S["probe_bytes"] = int(d.get("probe_bytes", 0))
    except Exception:
        _S["probe_bytes"] = 0
    try:
        _S["seq"] = int(d.get("seq", 0))
    except Exception:
        _S["seq"] = 0
    for r in _S["recs"]:
        r.setdefault("arr", 0)
        if not isinstance(r.get("arr"), int):
            r["arr"] = 0
    _AM, _AK = None, None


def probe_bytes():
    return int(_S["probe_bytes"])


def stats():
    return {"asset_bytes": len(json.dumps(state(), ensure_ascii=False)),
            "probe_bytes": int(_S["probe_bytes"]),
            "llm_tokens": 0}
