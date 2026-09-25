"""Life Model asset — M5 control semantics.

Control machinery (delta over the fallback baseline):
  * consent-scoped purpose views: revoke_purpose(p) withdraws a use-case view
    (data stays in the asset, the view answers 已撤回);
  * range-scoped erasure forget({day_gte, day_lte}) erases the window's write
    edges and rebuilds the live value from surviving edges (rollback, not a
    tombstone); forget({slot}) / forget({about}) erase vertices wholesale;
  * an operation journal (forget / forget_range / correct / revoke_purpose)
    that is part of state() and survives export->import, so post_import `ops`
    probes can be answered;
  * correct(slot, value) is a read-time self-assertion: it supersedes the live
    value, keeps provenance meaningful, and starves derived premises whose
    premise value diverged;
  * derived facts are maintained by a premise fixpoint: a derived fact dies
    (and is purged from state AND history, transitively through chains) when a
    supporting record is retracted/forgotten or when the supporting slot's live
    value no longer matches the value it had when the derivation was asserted.

Frozen substrate (M1/M3/M4): day-authoritative write edges with arrival-order
tie-breaks (out-of-order ingest safe), bitemporal as_of history, expiry,
retraction tombstones, alias-canonicalised attributed hearsay, multi-entity
(about) vertices, purpose views, budgeted packing, prov/prov2 citation, unans
abstention, and honest byte metering (cost measured, never fabricated).
"""
import json
import threading

_LOCK = threading.RLock()
_STATE = None
SELF_KINDS = ("statement", "update", "correction")


def _new_state():
    return {
        "v": 3, "seq": 0, "max_day": 0,
        "alias": {},        # name -> canonical
        "slots": {},        # self-domain: slot -> {"w": [writes], "ret": [day, exp, rid]}
        "about": {},        # entity -> {"slots": {...}}
        "hearsay": [],      # [day, seq, subject, speaker, slot, value, exp, rid, text]
        "derived": {},      # rid -> {slot, v, day, seq, sup, exp, about}
        "recs": {},         # rid -> [day, seq, slot, value, kind, src, about, exp]
        "removed": [],      # rids erased by forget / derived-cascade
        "journal": [],      # [op, target, day]
        "revoked": [],      # withdrawn purposes
        "pbytes": 0,        # cumulative consulted bytes
    }


def _ensure():
    global _STATE
    if _STATE is None:
        _STATE = _new_state()
    return _STATE


def _canon(st, name):
    if name is None:
        return None
    cur, seen = name, set()
    while cur in st["alias"] and st["alias"][cur] != cur and cur not in seen:
        seen.add(cur)
        cur = st["alias"][cur]
    return cur


def _about_match(st, a1, a2):
    if a1 is None and a2 is None:
        return True
    if a1 is None or a2 is None:
        return False
    return _canon(st, a1) == _canon(st, a2)


def _val_key(v):
    if isinstance(v, (list, tuple)):
        return tuple(str(x) for x in v)
    return v


def _vstr(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v)


def _get_store(st, about, create=False):
    if about is None:
        return st["slots"]
    v = st["about"].get(about)
    if v is None:
        if not create:
            return {}
        v = {"slots": {}}
        st["about"][about] = v
    return v["slots"]


def _matching_stores(st, about):
    out = []
    if about is None:
        out.append(st["slots"])
    else:
        for k, v in st["about"].items():
            if _canon(st, k) == _canon(st, about):
                out.append(v["slots"])
    return out


def _all_stores(st):
    out = [st["slots"]]
    for v in st["about"].values():
        out.append(v["slots"])
    return out


def _writes(rec, ck):
    if rec is None:
        return []
    out = [w for w in rec["w"] if not (w[4] is not None and ck > w[4])]
    out.sort(key=lambda w: (w[0], w[1]))
    return out


def _ret_active(rec, ck):
    r = rec["ret"]
    if r is None:
        return False
    return not (r[1] is not None and ck > r[1])


def _live_write(st, slot, ck, about):
    if slot is None:
        return None
    best = None
    for store in _matching_stores(st, about):
        rec = store.get(slot)
        if rec is None:
            continue
        ws = _writes(rec, ck)
        if not ws:
            continue
        w = ws[-1]
        if rec["ret"] is not None and _ret_active(rec, ck) and w[0] < rec["ret"][0]:
            continue  # retracted and not revived by a later write
        if best is None or (w[0], w[1]) > (best[0], best[1]):
            best = w
    return best


def _write_at(st, slot, day, ck, about):
    if slot is None:
        return None
    best = None
    for store in _matching_stores(st, about):
        rec = store.get(slot)
        if rec is None:
            continue
        ws = [w for w in _writes(rec, ck) if w[0] <= day]
        if not ws:
            continue
        w = ws[-1]
        if (rec["ret"] is not None and _ret_active(rec, ck) and day >= rec["ret"][0]
                and w[0] < rec["ret"][0]):
            continue
        if best is None or (w[0], w[1]) > (best[0], best[1]):
            best = w
    return best


def _hearsay_rid_live(st, rid, ck):
    for h in st["hearsay"]:
        if h[7] == rid:
            return not (h[6] is not None and ck > h[6])
    return False


def _supports_ok(st, d, ck, removed):
    for rid in d.get("sup", []):
        if rid in removed:
            return False
        r = st["recs"].get(rid)
        if r is None:
            continue  # support not delivered yet (out-of-order) -> keep alive
        day, seq, slot, val, kind, src, about, exp = r
        if exp is not None and ck > exp:
            return False
        if kind in SELF_KINDS and src == "self":
            lw = _live_write(st, slot, ck, about)
            if lw is None or _val_key(lw[2]) != _val_key(val):
                return False  # premise value diverged (correction / update)
        elif kind == "derived":
            if rid not in st["derived"]:
                return False  # supporting derivation is dead
        elif kind == "hearsay":
            if not _hearsay_rid_live(st, rid, ck):
                return False
    return True


def _maintain(st, ck):
    """Premise fixpoint: purge derived facts whose premises no longer hold.
    Purging is transitive (chains) because a purged fact disappears from
    st['derived'] and st['recs'], so its dependants lose their support."""
    removed = set(st.get("removed", []))
    changed = True
    while changed:
        changed = False
        for rid in list(st["derived"].keys()):
            d = st["derived"][rid]
            dead = (d.get("exp") is not None and ck > d["exp"]) or \
                   not _supports_ok(st, d, ck, removed)
            if dead:
                st["derived"].pop(rid, None)
                st["recs"].pop(rid, None)
                removed.add(rid)
                changed = True
    st["removed"] = sorted(removed)


def _derived_best(st, slot, ck, about, max_day=None):
    best = None
    for rid, d in st["derived"].items():
        if d.get("slot") != slot:
            continue
        if max_day is not None and d["day"] > max_day:
            continue
        if d.get("exp") is not None and ck > d["exp"]:
            continue
        da = d.get("about")
        if about is None:
            if da is not None:
                continue
        elif da is None or _canon(st, da) != _canon(st, about):
            continue
        if best is None or (d["day"], d["seq"]) > (best[0], best[1]):
            best = (d["day"], d["seq"], d.get("v"), rid)
    return best


def _live_value(st, slot, ck, about):
    w = _live_write(st, slot, ck, about)
    if w is not None:
        return _vstr(w[2])
    d = _derived_best(st, slot, ck, about)
    if d is not None:
        return _vstr(d[2])
    return None


def _name_in_text(st, text):
    if not text:
        return None
    names = [n for n in list(st["alias"].keys()) + list(st["about"].keys()) if n]
    names.sort(key=len, reverse=True)
    for n in names:
        if n in text:
            return n
    return None


def _hearsay_match(st, probe, ck):
    slot = probe.get("slot")
    person = probe.get("person")
    about = probe.get("about")
    best = None
    for h in st["hearsay"]:
        day, seq, subj, spk, hslot, val, exp, rid, text = h
        if subj is None:
            subj = _name_in_text(st, text)
        if exp is not None and ck > exp:
            continue
        if about is not None:
            if _canon(st, spk) != _canon(st, person):
                continue
            if _canon(st, subj) != _canon(st, about):
                continue
        elif _canon(st, subj) != _canon(st, person):
            continue
        if slot is not None and hslot is not None and hslot != slot:
            continue
        if best is None or (day, seq) > (best[0], best[1]):
            best = (day, seq, val)
    return best


def _self_said(st, slot, val, ck, about):
    kv = _val_key(val)
    for rid, r in st["recs"].items():
        day, seq, rslot, rval, kind, src, rabout, exp = r
        if kind not in SELF_KINDS or src != "self" or rslot != slot:
            continue
        if exp is not None and ck > exp:
            continue
        if not _about_match(st, rabout, about):
            continue
        if _val_key(rval) == kv:
            return True
    return False


def _self_said_any(st, slot, ck, about):
    for rid, r in st["recs"].items():
        day, seq, rslot, rval, kind, src, rabout, exp = r
        if kind not in SELF_KINDS or src != "self" or rslot != slot:
            continue
        if exp is not None and ck > exp:
            continue
        if _about_match(st, rabout, about):
            return True
    return False


def _hearsay_about(st, slot, about, ck):
    if about is None:
        return False
    for h in st["hearsay"]:
        if h[4] != slot or _canon(st, h[2]) != _canon(st, about):
            continue
        if h[6] is not None and ck > h[6]:
            continue
        return True
    return False


def _other_said_about(st, slot, about, ck):
    if about is None:
        return False
    for rid, r in st["recs"].items():
        day, seq, rslot, rval, kind, src, rabout, exp = r
        if kind not in SELF_KINDS or src == "self" or rslot != slot:
            continue
        if exp is not None and ck > exp:
            continue
        if rabout is None or _canon(st, rabout) != _canon(st, about):
            continue
        return True
    return False


def _count_changes(st, slot, ck, about):
    ws = []
    for store in _matching_stores(st, about):
        for w in _writes(store.get(slot), ck):
            ws.append(w)
    ws.sort(key=lambda w: (w[0], w[1]))
    n, prev, have = 0, None, False
    for w in ws:
        if not have or _val_key(w[2]) != prev:
            n += 1
            prev = _val_key(w[2])
            have = True
    return n


def _split_vals(v):
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    s = str(v)
    for ch in ("，", "、", "；", ";", ","):
        s = s.replace(ch, "\x00")
    return [p.strip() for p in s.split("\x00") if p.strip()]


def _latest_real_rid(st, slot, ck, about):
    best = None
    for store in _matching_stores(st, about):
        for w in _writes(store.get(slot), ck):
            if str(w[3]).startswith("correct-"):
                continue
            if best is None or (w[0], w[1]) > (best[0], best[1]):
                best = w
    return best[3] if best else None


def _slot_snapshot(st, slot, about):
    out = []
    for store in _matching_stores(st, about):
        r = store.get(slot)
        if r is not None:
            out.append(r)
    return out


def _b(st, *objs):
    """Honest metering: bytes actually consulted to answer."""
    try:
        st["pbytes"] += len(json.dumps(list(objs), ensure_ascii=False, default=str))
    except Exception:
        st["pbytes"] += sum(len(str(o)) for o in objs)


def _dispatch(st, probe, t, ck):
    slot = probe.get("slot")
    about = probe.get("about")

    if t in ("state", "stale", "post_import"):
        v = _live_value(st, slot, ck, about)
        _b(st, _slot_snapshot(st, slot, about), st["derived"])
        return v if v is not None else "未知"

    if t == "retract":
        rec = None
        for store in _matching_stores(st, about):
            if store.get(slot) is not None:
                rec = store[slot]
                break
        _b(st, rec)
        ws = _writes(rec, ck)
        if rec is not None and rec["ret"] is not None and _ret_active(rec, ck) and ws \
                and ws[-1][0] < rec["ret"][0]:
            return "已删除"
        v = _live_value(st, slot, ck, about)
        if v is not None:
            return v
        return "已删除" if (rec is not None and _ret_active(rec, ck)) else "未知"

    if t == "prov":
        r = _self_said(st, slot, probe.get("value"), ck, about)
        _b(st, st["recs"])
        return "本人" if r else "非本人"

    if t == "prov2":
        w = _live_write(st, slot, ck, about)
        _b(st, _slot_snapshot(st, slot, about))
        if w is None:
            return "无"
        rid = str(w[3])
        if rid.startswith("correct-"):
            real = _latest_real_rid(st, slot, ck, about)
            return rid + "," + str(real) if real else rid
        return rid

    if t == "as_of":
        day = probe.get("day")
        try:
            day = int(day) if day is not None else ck
        except Exception:
            day = ck
        w = _write_at(st, slot, day, ck, about)
        _b(st, _slot_snapshot(st, slot, about))
        if w is not None:
            return _vstr(w[2])
        d = _derived_best(st, slot, ck, about, max_day=day)
        if d is not None:
            return _vstr(d[2])
        return "未知"

    if t == "subject":
        best = _hearsay_match(st, probe, ck)
        _b(st, st["hearsay"], st["alias"])
        if best is not None:
            return _vstr(best[2])
        if about is not None:  # v8: what `person` stated about `about`
            person = probe.get("person")
            best2 = None
            for rid, r in st["recs"].items():
                day, seq, rslot, rval, kind, src, rabout, exp = r
                if kind not in SELF_KINDS or rslot != slot:
                    continue
                if exp is not None and ck > exp:
                    continue
                if not _about_match(st, rabout, about):
                    continue
                if _canon(st, src) != _canon(st, person):
                    continue
                if best2 is None or (day, seq) > (best2[0], best2[1]):
                    best2 = (day, seq, rval)
            if best2 is not None:
                return _vstr(best2[2])
        return "未知"

    if t in ("cascade", "derive"):
        v = _live_value(st, slot, ck, about)
        _b(st, _slot_snapshot(st, slot, about), st["derived"])
        return v if v is not None else "未知"

    if t == "unans":
        said = _self_said_any(st, slot, ck, about)
        if said:
            v = _live_value(st, slot, ck, about)
            _b(st, st["recs"])
            return v if v is not None else "未知"
        _b(st, st["recs"])
        return "未知"

    if t in ("purpose", "revoked"):
        pur = probe.get("purpose")
        if pur in st["revoked"]:
            _b(st, st["revoked"])
            return "已撤回"
        slots = probe.get("purpose_slots") or probe.get("slots") or []
        vals = []
        for s in slots:
            v = _live_value(st, s, ck, None)
            if v is not None:
                vals.append(v)
        _b(st, st["revoked"], slots)
        return ",".join(vals) if vals else "未知"

    if t == "budget":
        budget = probe.get("budget")
        try:
            budget = int(budget) if budget is not None else 10 ** 9
        except Exception:
            budget = 10 ** 9
        slots = probe.get("slots") or []
        vals = []
        for s in slots:
            v = _live_value(st, s, ck, None)
            if v is not None:
                vals.append(v)
        s = ",".join(vals)
        if len(s) > budget:
            cut = s[:budget]
            i = cut.rfind(",")
            if i > 0:
                cut = cut[:i]
            s = cut
        _b(st, slots)
        return s if s else "未知"

    if t == "ops":
        op = probe.get("op")
        targets = [e[1] for e in st["journal"] if e[0] == op]
        _b(st, st["journal"])
        if not targets:
            return "无"
        seen = []
        for tgt in reversed(targets):
            if tgt not in seen:
                seen.append(tgt)
        return ",".join(str(x) for x in seen)

    if t == "nchange":
        n = _count_changes(st, slot, ck, about)
        _b(st, _slot_snapshot(st, slot, about))
        return str(n)

    if t == "conf":
        _b(st, st["recs"], st["hearsay"])
        if _self_said_any(st, slot, ck, about):
            return "高"
        if _hearsay_about(st, slot, about, ck) or _other_said_about(st, slot, about, ck):
            return "低"
        return "无"

    if t == "transfer":
        slots = probe.get("slots") or ([slot] if slot is not None else [])
        raws, parts = [], []
        for s in slots:
            v = _live_value(st, s, ck, about)
            if v is None:
                continue
            raws.append(v)
            parts.extend(_split_vals(v))
        _b(st, slots)
        raw_s = ",".join(raws)
        if not raw_s:
            return "未知"
        part_s = ",".join(parts)
        if part_s and part_s != raw_s:
            return raw_s + "," + part_s
        return raw_s

    return "未知"


# ---------------------------------------------------------------- public API

def ingest(rec):
    with _LOCK:
        st = _ensure()
        rec = rec or {}
        rid = rec.get("id")
        day = rec.get("day") or 0
        try:
            day = int(day)
        except Exception:
            day = 0
        st["seq"] = int(st.get("seq", 0)) + 1
        seq = st["seq"]
        if day > int(st["max_day"]):
            st["max_day"] = day
        src = rec.get("source")
        kind = rec.get("kind")
        slot = rec.get("slot")
        val = rec.get("value")
        exp = rec.get("expires_day")
        if exp is not None:
            try:
                exp = int(exp)
            except Exception:
                exp = None
        about = rec.get("about")
        if rid is not None:
            st["recs"][rid] = [day, seq, slot, val, kind, src, about, exp]

        if kind == "alias":
            name = rec.get("name") or rec.get("subject") or rec.get("person") or rec.get("about")
            if name and val is not None:
                st["alias"][name] = val
                st["alias"].setdefault(val, val)
            return

        if kind in SELF_KINDS and src == "self":
            store = _get_store(st, about, create=True)
            r = store.get(slot)
            if r is None:
                r = {"w": [], "ret": None}
                store[slot] = r
            r["w"].append([day, seq, val, rid, exp, kind])
            return

        if kind == "retraction":
            store = _get_store(st, about, create=True)
            r = store.get(slot)
            if r is None:
                r = {"w": [], "ret": None}
                store[slot] = r
            r["ret"] = [day, exp, rid]
            return

        if kind == "hearsay":
            subj = rec.get("subject") or rec.get("person") or rec.get("about")
            hslot = slot
            if subj is None:  # defensive: subject encoded in the slot
                subj = slot
                hslot = None
            st["hearsay"].append([day, seq, subj, src, hslot, val, exp, rid,
                                  rec.get("text")])
            return

        if kind == "derived":
            sup = rec.get("supports")
            if sup is None:
                sup = rec.get("support")
            if sup is None:
                sup = []
            if isinstance(sup, str):
                sup = [sup]
            if rid is not None:
                st["derived"][rid] = {"slot": slot, "v": val, "day": day, "seq": seq,
                                      "sup": list(sup), "exp": exp, "about": about}
            return
        # suggestion / other kinds: recorded in recs only (never state)


def answer(probe):
    with _LOCK:
        st = _ensure()
        probe = probe or {}
        t = str(probe.get("type") or probe.get("q") or "").strip().lower()
        ck = probe.get("ckpt")
        try:
            ck = int(ck) if ck is not None else int(st["max_day"])
        except Exception:
            ck = int(st["max_day"])
        _maintain(st, ck)
        try:
            r = _dispatch(st, probe, t, ck)
        except Exception:
            r = "未知"
        return "未知" if r is None else r


def forget(scope):
    with _LOCK:
        st = _ensure()
        scope = scope or {}
        day = int(st["max_day"])
        removed = []

        if "day_gte" in scope or "day_lte" in scope:  # range erasure + rollback
            try:
                g = int(scope.get("day_gte")) if scope.get("day_gte") is not None else 0
            except Exception:
                g = 0
            try:
                l = int(scope.get("day_lte")) if scope.get("day_lte") is not None else 10 ** 9
            except Exception:
                l = 10 ** 9
            target = scope.get("slot") or ("day%d-%d" % (g, l))
            for store in _all_stores(st):
                for s, r in list(store.items()):
                    keep = []
                    for w in r["w"]:
                        (removed.append(w[3]) if g <= w[0] <= l else keep.append(w))
                    r["w"] = keep
                    if r["ret"] is not None and g <= r["ret"][0] <= l:
                        removed.append(r["ret"][2])
                        r["ret"] = None
            for rid, d in list(st["derived"].items()):
                if g <= d["day"] <= l:
                    st["derived"].pop(rid, None)
                    st["recs"].pop(rid, None)
                    removed.append(rid)
            st["hearsay"] = [h for h in st["hearsay"]
                             if not (g <= h[0] <= l or removed.append(h[7]) is None)]
            st["journal"].append(["forget_range", target, day])

        elif scope.get("about") is not None and scope.get("slot") is None:
            about = scope["about"]
            for k in list(st["about"].keys()):
                if _canon(st, k) == _canon(st, about):
                    v = st["about"].pop(k)
                    for s, r in v["slots"].items():
                        removed.extend(w[3] for w in r["w"])
                        if r["ret"] is not None:
                            removed.append(r["ret"][2])
            kept = []
            for h in st["hearsay"]:
                if _canon(st, h[2]) == _canon(st, about):
                    removed.append(h[7])
                else:
                    kept.append(h)
            st["hearsay"] = kept
            for rid, d in list(st["derived"].items()):
                if d.get("about") is not None and _canon(st, d["about"]) == _canon(st, about):
                    st["derived"].pop(rid, None)
                    st["recs"].pop(rid, None)
                    removed.append(rid)
            st["journal"].append(["forget", "about:" + str(about), day])

        else:  # slot erasure (optionally within an about scope)
            slot = scope.get("slot")
            about = scope.get("about")
            for store in _matching_stores(st, about):
                r = store.get(slot)
                if r is None:
                    continue
                removed.extend(w[3] for w in r["w"])
                if r["ret"] is not None:
                    removed.append(r["ret"][2])
                r["w"] = []
                r["ret"] = None
            st["journal"].append(["forget",
                                  slot if about is None else ("%s:%s" % (about, slot)), day])

        st["removed"] = sorted(set(list(st.get("removed", [])) + removed))
        for rid in st["removed"]:  # erased records are gone from provenance too
            st["recs"].pop(rid, None)
        _maintain(st, day)  # cascade: derived facts losing their support die


def correct(slot, value):
    with _LOCK:
        st = _ensure()
        day = int(st["max_day"])
        st["seq"] = int(st.get("seq", 0)) + 1
        seq = st["seq"]
        rid = "correct-%d" % seq
        store = st["slots"]  # user correction is a self-domain assertion
        r = store.get(slot)
        if r is None:
            r = {"w": [], "ret": None}
            store[slot] = r
        r["w"].append([day, seq, value, rid, None, "correction"])
        r["ret"] = None  # correction revives a retracted slot
        st["recs"][rid] = [day, seq, slot, value, "correction", "self", None, None]
        st["journal"].append(["correct", slot, day])


def revoke_purpose(purpose):
    with _LOCK:
        st = _ensure()
        purpose = purpose if purpose is not None else ""
        if purpose not in st["revoked"]:
            st["revoked"].append(purpose)
        st["journal"].append(["revoke_purpose", purpose, int(st["max_day"])])


def state():
    with _LOCK:
        return _ensure()


def import_state(d):
    global _STATE
    with _LOCK:
        base = _new_state()
        d = d or {}
        for k, v in base.items():
            if k in d and d[k] is not None:
                base[k] = d[k]
        _STATE = base


def probe_bytes():
    with _LOCK:
        return int(_ensure().get("pbytes", 0))


def stats():
    with _LOCK:
        st = _ensure()
        try:
            ab = len(json.dumps(st, ensure_ascii=False, default=str))
        except Exception:
            ab = 0
        return {"asset_bytes": ab, "probe_bytes": int(st.get("pbytes", 0)),
                "llm_tokens": 0}
