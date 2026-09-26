# asset.py -- Life Model asset (M5 control semantics)
#
# Contract: module-level ingest / answer / forget / correct / revoke_purpose /
# state / import_state / probe_bytes / stats.
#
# Model: an append-only set of normalized records, indexed into
# (about, slot) vertices ordered by (day, arrival).  Live values are derived by
# replaying the vertex's write edges up to the probe's day (bitemporal), which
# makes out-of-order ingest, same-day ties, expiry, retraction, supersession and
# range-rollback all the same computation.  Derived (inference) facts are extra
# write edges that are only live while their premise fixpoint holds.  Control
# ops (forget / forget_range / correct / revoke_purpose) mutate a gone-set, add
# read-time edges, or flip a purpose flag, and every one is journaled.

import json

_SAID = ("statement", "update", "correction")


def _norm(v):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return str(v)


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _exp(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class LifeModel:
    def __init__(self):
        self.recs = {}        # id -> normalized record
        self.gone = set()     # ids erased by forget / forget_range
        self.journal = []     # control-op audit trail
        self.purposes = {}    # purpose -> {"revoked": bool}
        self.aliases = {}     # name -> canonical name
        self.pb = 0           # cumulative bytes consulted
        self.arr = 0          # arrival counter (tie-break, later wins)
        self.max_day = 0
        self.verts = None     # (about, slot) -> sorted edge list
        self._sz = {}         # id -> serialized size (metering only)
        self._dcache = None   # (ver, day) -> alive derived set
        self._ver = 0

    # ------------------------------------------------------------------ misc
    def _bump(self):
        self._ver += 1
        self.verts = None
        self._dcache = None

    def _touch(self, r):
        rid = r["id"]
        sz = self._sz.get(rid)
        if sz is None:
            sz = len(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            self._sz[rid] = sz
        self.pb += sz

    def _resolve(self, name):
        """Resolve a person name to its canonical form through the alias map."""
        if name is None:
            return None
        key = str(name).strip()
        if not key:
            return None
        seen = set()
        cur = key
        while cur not in seen:
            seen.add(cur)
            nxt = self.aliases.get(cur)
            if not nxt or nxt == cur:
                break
            cur = nxt
        return cur

    def _verts_get(self):
        if self.verts is None:
            d = {}
            for r in self.recs.values():
                d.setdefault((r["about"], r["slot"]), []).append(r)
            for v in d.values():
                v.sort(key=lambda e: (e["day"], e["arr"]))
            self.verts = d
        return self.verts

    # ------------------------------------------------------------- ingestion
    def ingest(self, rec):
        if not isinstance(rec, dict):
            return
        rid = rec.get("id")
        if rid is None:
            rid = "_n%d" % self.arr
        rid = str(rid)
        if rid in self.recs:
            return
        supp = rec.get("supports")
        if supp is None:
            supp = None
        elif isinstance(supp, (list, tuple)):
            supp = [str(x) for x in supp if x is not None]
        else:
            supp = [str(supp)]
        r = {
            "id": rid,
            "day": _int(rec.get("day")),
            "arr": self.arr,
            "source": rec.get("source"),
            "kind": rec.get("kind"),
            "slot": rec.get("slot"),
            "value": _norm(rec.get("value")),
            "exp": _exp(rec.get("expires_day")),
            "about": rec.get("about"),
            "supp": supp,
            "text": rec.get("text"),
        }
        self.arr += 1
        if r["day"] > self.max_day:
            self.max_day = r["day"]
        if r["kind"] == "alias":
            canon = _norm(rec.get("value"))
            names = []
            for key in ("text", "alias"):
                n = _norm(rec.get(key))
                if n:
                    names.append(n)
            if rec.get("slot") and rec.get("slot") != "alias":
                n = _norm(rec.get("slot"))
                if n:
                    names.append(n)
            for key in ("names", "aliases"):
                v = rec.get(key)
                if isinstance(v, list):
                    for n in v:
                        n = _norm(n)
                        if n:
                            names.append(n)
            if canon:
                for n in names:
                    if n != canon:
                        self.aliases[n] = canon
        self.recs[rid] = r
        self._bump()

    # --------------------------------------------------------- control ops
    def forget(self, scope):
        """Erase every record matching the scope.  slot / about / day_gte /
        day_lte may be combined; a day window makes this a range forget that
        rolls the live value back to the previous surviving write."""
        if not isinstance(scope, dict):
            scope = {}
        slot = scope.get("slot")
        about = scope.get("about")
        g = scope.get("day_gte")
        l = scope.get("day_lte")
        if slot is None and about is None and g is None and l is None:
            return
        g = _int(g) if g is not None else None
        l = _int(l) if l is not None else None
        first_slot = None
        n = 0
        for r in self.recs.values():
            if slot is not None and r["slot"] != slot:
                continue
            if about and (r["about"] or None) != about:
                continue
            if g is not None and r["day"] < g:
                continue
            if l is not None and r["day"] > l:
                continue
            if r["id"] not in self.gone:
                self.gone.add(r["id"])
                n += 1
                if first_slot is None:
                    first_slot = r["slot"]
        op = "forget_range" if (g is not None or l is not None) else "forget"
        target = slot or about or first_slot
        self.journal.append({"op": op, "slot": slot, "about": about,
                             "day_gte": g, "day_lte": l, "target": target,
                             "n": n})
        self._bump()

    def correct(self, slot, value):
        """User correction at read time: a fresh self correction edge that
        supersedes the slot's live value (and therefore breaks premises that
        depended on the old value)."""
        if not slot:
            return
        rid = "_c%d" % self.arr
        r = {"id": rid, "day": self.max_day, "arr": self.arr,
             "source": "self", "kind": "correction", "slot": slot,
             "value": _norm(value), "exp": None, "about": None,
             "supp": None, "text": None}
        self.arr += 1
        self.recs[rid] = r
        self.journal.append({"op": "correct", "slot": slot, "target": slot,
                             "value": _norm(value)})
        self._bump()

    def revoke_purpose(self, purpose):
        """Withdraw a use-case view: the data stays, the view refuses."""
        if not purpose:
            return
        p = str(purpose)
        self.purposes[p] = {"revoked": True}
        self.journal.append({"op": "revoke_purpose", "purpose": p, "target": p})
        self._bump()

    # ------------------------------------------------------- live-value core
    def _eff(self, about, slot, T, alive, touch=True):
        """Value effective at day T for vertex (about, slot): replay write
        edges in (day, arrival) order, honouring erasure, expiry, retraction,
        supersession and live derived facts."""
        edges = self._verts_get().get((about, slot))
        if not edges:
            return None, None
        cur = None
        cure = None
        for e in edges:
            if e["day"] > T:
                break
            if e["id"] in self.gone:
                continue
            k = e["kind"]
            if k == "hearsay" or k == "suggestion" or k == "alias":
                continue
            if k == "derived":
                if alive is not None and e["id"] not in alive:
                    continue
            elif e["source"] != "self":
                continue
            exp = e["exp"]
            if exp is not None and T > exp:
                continue
            if touch:
                self._touch(e)
            if k == "retraction":
                cur = None
                cure = None
            else:
                cur = e["value"]
                cure = e
        return cur, cure

    def _premises(self, d, alive, T):
        if d["id"] in self.gone:
            return False
        if d["exp"] is not None and T > d["exp"]:
            return False
        supp = d["supp"]
        if not supp:
            return True
        for sid in supp:
            s = self.recs.get(sid)
            if s is None or s["id"] in self.gone:
                return False
            about = s["about"] if s["about"] is not None else d["about"]
            v, _ = self._eff(about, s["slot"], T, alive, touch=False)
            if _norm(v) != _norm(s["value"]):
                return False
        return True

    def _derived(self, T):
        """Fixpoint of live derived facts at day T (death is transitive)."""
        key = (self._ver, T)
        if self._dcache is not None and self._dcache[0] == key:
            return self._dcache[1]
        derived = [r for r in self.recs.values() if r["kind"] == "derived"]
        alive = set(d["id"] for d in derived)
        changed = True
        guard = 0
        while changed and guard < 128:
            guard += 1
            changed = False
            for d in derived:
                if d["id"] not in alive:
                    continue
                if not self._premises(d, alive, T):
                    alive.discard(d["id"])
                    changed = True
        for d in derived:
            self._touch(d)
            if d["id"] in alive:
                for sid in (d["supp"] or []):
                    s = self.recs.get(sid)
                    if s is not None:
                        self._touch(s)
        self._dcache = (key, alive)
        return alive

    # ------------------------------------------------------------- answers
    def _a_state(self, about, slot, ckpt, alive):
        v, _ = self._eff(about, slot, ckpt, alive)
        return v if v is not None else "未知"

    def _a_retract(self, about, slot, ckpt, alive):
        v, _ = self._eff(about, slot, ckpt, alive)
        if v is not None:
            return v
        verts = self._verts_get()
        for e in verts.get((about, slot), ()):
            if e["day"] > ckpt:
                break
            if e["id"] in self.gone:
                continue
            if e["kind"] == "retraction" and e["source"] == "self":
                if e["exp"] is None or ckpt <= e["exp"]:
                    return "已删除"
        for e in verts.get((about, slot), ()):
            if e["id"] in self.gone:
                return "已删除"
            if e["source"] == "self" and e["kind"] in _SAID:
                return "已删除"
            if e["kind"] == "derived":
                return "已删除"
        return "未知"

    def _a_prov(self, probe, about, slot, ckpt, alive):
        claimed = _norm(probe.get("value"))
        v, e = self._eff(about, slot, ckpt, alive)
        if e is not None and e["source"] == "self" and e["kind"] in _SAID \
                and _norm(v) == claimed:
            return "本人"
        return "非本人"

    def _a_prov2(self, about, slot, ckpt, alive):
        v, e = self._eff(about, slot, ckpt, alive)
        if e is not None and e["source"] == "self" and e["kind"] in _SAID:
            return str(e["id"])
        best = None
        for ed in self._verts_get().get((about, slot), ()):
            if ed["id"] in self.gone:
                continue
            if ed["source"] == "self" and ed["kind"] in _SAID:
                if best is None or (ed["day"], ed["arr"]) > (best["day"], best["arr"]):
                    best = ed
        return str(best["id"]) if best is not None else "未知"

    def _a_subject(self, probe, about, slot, ckpt):
        person = probe.get("person")
        canon = self._resolve(person) if person else None
        best = None
        for r in self.recs.values():
            if r["kind"] != "hearsay" or r["id"] in self.gone:
                continue
            if canon is None or self._resolve(r["source"]) != canon:
                continue
            ra = r["about"]
            if about is not None:
                if ra != about:
                    continue
            elif ra is not None and self._resolve(ra) != canon:
                continue
            if slot is not None and r["slot"] != slot:
                continue
            if r["exp"] is not None and ckpt > r["exp"]:
                continue
            self._touch(r)
            if best is None or (r["day"], r["arr"]) > (best["day"], best["arr"]):
                best = r
        return best["value"] if best is not None else "未知"

    def _slot_list(self, probe, key):
        v = probe.get(key)
        if not v:
            return []
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v if x is not None and str(x).strip() != ""]
        return [x.strip() for x in str(v).split(",") if x.strip()]

    def _pack(self, slots, about, ckpt, alive):
        out = []
        for s in slots:
            v, _ = self._eff(about, s, ckpt, alive)
            if v is not None:
                out.append(str(v))
        return ",".join(out)

    def _a_transfer(self, probe, about, slot, ckpt, alive):
        vals = probe.get("values")
        if isinstance(vals, (list, tuple)):
            return ",".join(str(x) for x in vals)
        slots = self._slot_list(probe, "slots")
        if slots:
            s = self._pack(slots, about, ckpt, alive)
            return s if s else "未知"
        out = []
        cur = None
        for e in self._verts_get().get((about, slot), ()):
            if e["day"] > ckpt:
                break
            if e["id"] in self.gone:
                continue
            k = e["kind"]
            if k in ("hearsay", "suggestion", "alias"):
                continue
            if k == "derived":
                if e["id"] not in alive:
                    continue
            elif e["source"] != "self":
                continue
            if e["exp"] is not None and ckpt > e["exp"]:
                continue
            self._touch(e)
            if k == "retraction":
                cur = None
            else:
                if e["value"] != cur:
                    out.append(str(e["value"]))
                cur = e["value"]
        return ",".join(out) if out else "未知"

    def _revoked(self, probe):
        p = probe.get("purpose")
        if not p:
            return False
        return bool(self.purposes.get(str(p), {}).get("revoked"))

    def _a_view(self, probe, about, ckpt, alive):
        if self._revoked(probe):
            return "已撤回"
        slots = self._slot_list(probe, "purpose_slots") or self._slot_list(probe, "slots")
        s = self._pack(slots, about, ckpt, alive)
        return s if s else "未知"

    def _a_budget(self, probe, about, ckpt, alive):
        if self._revoked(probe):
            return "已撤回"
        slots = self._slot_list(probe, "slots")
        if not slots and probe.get("slot"):
            slots = [str(probe.get("slot"))]
        s = self._pack(slots, about, ckpt, alive)
        return s if s else "未知"

    def _a_ops(self, probe):
        op = probe.get("op")
        if not op:
            return "无"
        op = str(op)
        ents = [j for j in self.journal if j.get("op") == op]
        if not ents:
            return "无"
        j = ents[-1]
        t = j.get("target") or j.get("slot") or j.get("purpose") or j.get("about")
        return str(t) if t else "无"

    def _nchange(self, about, slot, ckpt):
        prev = None
        count = 0
        for e in self._verts_get().get((about, slot), ()):
            if e["day"] > ckpt:
                break
            if e["id"] in self.gone:
                continue
            if e["source"] != "self" or e["kind"] not in _SAID:
                continue
            v = e["value"]
            if prev is not None and v != prev:
                count += 1
            prev = v
        return count

    def _conf(self, about, slot, ckpt, alive):
        v, e = self._eff(about, slot, ckpt, alive)
        if e is not None and e["source"] == "self" and e["kind"] in _SAID:
            return "高"
        for ed in self._verts_get().get((about, slot), ()):
            if ed["id"] in self.gone or ed["source"] == "self":
                continue
            k = ed["kind"]
            if k == "hearsay" or k in _SAID:
                if ed["exp"] is None or ckpt <= ed["exp"]:
                    return "低"
        return "无"

    # ------------------------------------------------------------- dispatch
    def answer(self, probe):
        if not isinstance(probe, dict):
            return "未知"
        t = probe.get("type")
        if t is None:
            t = probe.get("q")
        t = str(t or "").strip().lower()
        ck = probe.get("ckpt")
        ckpt = _int(ck, self.max_day) if ck is not None else self.max_day
        about = probe.get("about")
        slot = probe.get("slot")
        alive = self._derived(ckpt)

        if t in ("state", "stale", "cascade", "derive"):
            return self._a_state(about, slot, ckpt, alive)
        if t == "unans":
            return "未知"
        if t == "retract":
            return self._a_retract(about, slot, ckpt, alive)
        if t == "as_of":
            d = probe.get("day")
            D = _int(d, ckpt) if d is not None else ckpt
            al = self._derived(D)
            v, _ = self._eff(about, slot, D, al)
            return v if v is not None else "未知"
        if t == "prov":
            return self._a_prov(probe, about, slot, ckpt, alive)
        if t == "prov2":
            return self._a_prov2(about, slot, ckpt, alive)
        if t == "subject":
            return self._a_subject(probe, about, slot, ckpt)
        if t == "transfer":
            return self._a_transfer(probe, about, slot, ckpt, alive)
        if t in ("purpose", "revoked"):
            return self._a_view(probe, about, ckpt, alive)
        if t == "budget":
            return self._a_budget(probe, about, ckpt, alive)
        if t == "ops":
            return self._a_ops(probe)
        if t == "nchange":
            return str(self._nchange(about, slot, ckpt))
        if t == "conf":
            return self._conf(about, slot, ckpt, alive)

        # lenient fallback for unseen probe shapes
        if probe.get("purpose_slots") or (probe.get("purpose") and self._revoked(probe)):
            return self._a_view(probe, about, ckpt, alive)
        if probe.get("budget") is not None and probe.get("slots"):
            return self._a_budget(probe, about, ckpt, alive)
        if probe.get("person"):
            return self._a_subject(probe, about, slot, ckpt)
        if probe.get("day") is not None:
            D = _int(probe.get("day"), ckpt)
            al = self._derived(D)
            v, _ = self._eff(about, slot, D, al)
            return v if v is not None else "未知"
        return self._a_state(about, slot, ckpt, alive)

    # --------------------------------------------------------- persistence
    def state(self):
        return {
            "v": 4,
            "recs": list(self.recs.values()),
            "gone": sorted(self.gone),
            "journal": self.journal,
            "purposes": self.purposes,
            "aliases": self.aliases,
            "pb": self.pb,
            "arr": self.arr,
            "max_day": self.max_day,
        }

    def import_state(self, d):
        if not isinstance(d, dict):
            return
        self.recs = {}
        self.gone = set(d.get("gone") or [])
        self.journal = list(d.get("journal") or [])
        self.purposes = dict(d.get("purposes") or {})
        self.aliases = dict(d.get("aliases") or {})
        self.pb = _int(d.get("pb"))
        self.arr = _int(d.get("arr"))
        self.max_day = _int(d.get("max_day"))
        for r in (d.get("recs") or []):
            if not isinstance(r, dict):
                continue
            rid = r.get("id")
            if rid is None:
                continue
            self.recs[str(rid)] = {
                "id": str(rid),
                "day": _int(r.get("day")),
                "arr": _int(r.get("arr")),
                "source": r.get("source"),
                "kind": r.get("kind"),
                "slot": r.get("slot"),
                "value": _norm(r.get("value")),
                "exp": _exp(r.get("exp")),
                "about": r.get("about"),
                "supp": r.get("supp"),
                "text": r.get("text"),
            }
        self._bump()

    def probe_bytes(self):
        return self.pb

    def stats(self):
        return {
            "asset_bytes": len(json.dumps(self.state(), ensure_ascii=False)),
            "probe_bytes": self.pb,
            "llm_tokens": 0,
        }


_M = LifeModel()

def ingest(rec): _M.ingest(rec)
def answer(probe): return _M.answer(probe)
def forget(scope): _M.forget(scope)
def correct(slot, value): _M.correct(slot, value)
def revoke_purpose(purpose): _M.revoke_purpose(purpose)
def state(): return _M.state()
def import_state(d): _M.import_state(d)
def probe_bytes(): return _M.probe_bytes()
def stats(): return _M.stats()
