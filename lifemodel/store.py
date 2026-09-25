"""M2 Store v1 — winning family: per-(source, slot) temporal history.

P3 r1 outcome (results/life_model_v2/FAMILY_RACE.md): every surveyed
index family that won — event-sourced aggregates, subject claims graph,
bitemporal slot-history — is this same idea: group the record stream by
(source, slot), keep validity metadata, answer by lookup never replay.
Quality saturates at 97/97 across all of them; the game is cost.

v0 was `SlotIndex` (flat LWW + ctx log): correct on state/prov but had no
history (as_of impossible) and dropped non-authoritative events (subject
impossible). v1 keeps EVERY event as a temporal edge:

    hist: "source|slot" -> [[value, from_day, kind, expires], ...]

Reads use the max-from rule — the latest edge with from_day <= query day
decides; a retraction edge means "gone from that day". Expiry is stored
on the edge and applied at read time. Derived views are projections of
the same edges: self-state is the "self" vertex, hearsay lives on each
other person's vertex — authority is a READ-side filter, which is why
subject hearsay can never pollute self state.

    prov: slot -> [values self ever asserted]   (prov probes)
    exp:  slot -> expires_day   slot-scoped lease: once any self write
          declares expires_day the WHOLE slot dies after that day —
          later writes without expiry do NOT renew the lease, and the
          check is applied at READ day, not at ingest.

forget(slot) erases every edge of the slot across ALL sources —
cascade-clean by construction, no separate history purge.

P3 r2 M3 fold (TMS): `kind="derived"` records additionally register in
`drv`: slot -> {"premises": {premise_slot: premised_value}, "value": v},
resolved from their `supports=[record ids]` via `rsv` (id -> (slot,
value)). A derived entry is live ONLY while every premise holds — every
mutation (append, forget_slot, forget_range) ends in a `_prune()`
fixpoint that kills drv entries whose premise slot's live value is
absent or diverged; premise slots may themselves be derived, so the
sweep is transitive. Reads fall back to drv after the self vertex, so
derived values answer as self-state while valid — the TMS lesson from
the M3 round: premises are load-bearing, not documentation.

All contents stay JSON-serializable: snapshot() emits them verbatim.
"""
from __future__ import annotations

SELF = "self"
WRITES = {"statement", "update", "correction"}
AUTH = WRITES | {"retraction"}


def _key(source, slot):
    return f"{source}|{slot}"


def _edge_at(edges, day):
    """Latest edge by from_day <= `day`; retraction tombstone => gone."""
    cur = None
    for e in edges:
        if e[1] <= day and (cur is None or e[1] >= cur[1]):
            cur = e
    if cur is None or cur[2] == "retraction":
        return None
    if cur[3] is not None and day > cur[3]:
        return None
    return cur[0]


class TemporalGraph:
    def __init__(self):
        self.hist: dict = {}
        self.prov: dict = {}
        self.rsv: dict = {}   # record id -> (slot, value)
        self.drv: dict = {}   # derived slot -> {"premises": {}, "value"}
        self.exp: dict = {}   # slot -> expires_day (slot-scoped lease)
        self.rvid: dict = {}  # slot -> latest self-write record id (prov2)
        self.aliases: dict = {}  # alias -> canonical person (M1)
        self.revoked: set = set()  # purposes whose use is withdrawn (M5)
        self.journal: list = []    # control-op log, survives export (M5)
        self._wday: dict = {}   # slot -> day of latest self write (OOO)
        self._now: int = 0    # latest observed event day (read-day clock)

    def forms_of(self, person):
        """person + known aliases (alias records resolve names at read)."""
        out = {person}
        for a, c in self.aliases.items():
            if c == person:
                out.add(a)
            elif a == person:
                out.add(c)
        return out

    # ---- writes ----
    def append(self, ev: dict) -> None:
        """Every normalized event becomes an edge on its source vertex."""
        if ev["slot"] is None:
            return
        self._now = max(self._now, ev["day"])
        if ev["kind"] == "alias":
            self.aliases[ev["slot"]] = ev["value"]
            return
        if ev.get("id"):
            self.rsv[ev["id"]] = (ev["slot"], ev["value"])
        who = (f'{ev["source"]}|{ev["about"]}' if ev.get("about")
               else ev["source"])   # claimer|about|slot vertex
        self.hist.setdefault(_key(who, ev["slot"]), []).append(
            [ev["value"], ev["day"], ev["kind"], ev.get("expires"),
             ev.get("id")])
        if ev["source"] == SELF and ev["kind"] in WRITES:
            # rvid (prov2 citation) tracks self writes on any vertex —
            # keyed by slot for self claims, about|slot for entity claims
            rkey = (ev["slot"] if not ev.get("about")
                    else f'{ev["about"]}|{ev["slot"]}')
            # day is authoritative, not arrival order
            if (ev.get("id") and
                    ev["day"] >= self._wday.get(rkey, -1)):
                self._wday[rkey] = ev["day"]
                self.rvid[rkey] = ev["id"]
            if not ev.get("about"):
                vals = self.prov.setdefault(ev["slot"], [])
                if ev["value"] not in vals:
                    vals.append(ev["value"])
                if ev.get("expires"):
                    self.exp[ev["slot"]] = ev["expires"]
        if ev["kind"] == "derived":
            pre = self._premises(ev)
            if pre is not None:   # dangling supports: dead at birth
                self.drv[ev["slot"]] = {"premises": pre,
                                        "value": ev["value"]}
        self._prune()

    def _premises(self, ev):
        """supports=[record ids] -> {premise_slot: premised_value}."""
        out = {}
        for rid in ev.get("supports") or []:
            if rid not in self.rsv:
                return None
            s, v = self.rsv[rid]
            out[s] = v
        return out

    def _live_val(self, slot):
        """Self-authoritative value, else the live derived value."""
        v = self.live_at(SELF, slot, self._now)
        if v is not None:
            return v
        d = self.drv.get(slot)
        return d["value"] if d else None

    def _prune(self):
        """Fixpoint sweep: kill drv entries with a dead/diverged premise."""
        moved = True
        while moved:
            moved = False
            for s in list(self.drv):
                if any(self._live_val(ps) != pv
                       for ps, pv in self.drv[s]["premises"].items()):
                    del self.drv[s]
                    moved = True

    def forget_slot(self, slot) -> int:
        """Erase the slot across every vertex (history AND derivations)."""
        keys = [k for k in self.hist if k.split("|", 1)[1] == slot]
        n = len(keys) + (slot in self.prov)
        for k in keys:
            del self.hist[k]
        self.prov.pop(slot, None)
        self.drv.pop(slot, None)
        self.exp.pop(slot, None)
        self.rvid.pop(slot, None)
        self._wday.pop(slot, None)
        self._prune()   # dependents of the forgotten slot die too
        return n

    def forget_about(self, about) -> int:
        """Forget a person: erase every vertex about them (all claimers,
        all name forms of the entity)."""
        keys = [k for k in self.hist
                if k.count("|") == 2
                and k.split("|")[1] in self.forms_of(about)]
        for k in keys:
            del self.hist[k]
            akey = k.split("|", 1)[1]
            self._wday.pop(akey, None)
            self.rvid.pop(akey, None)
        return len(keys)

    def forget_range(self, lo, hi) -> int:
        """Erase edges whose from_day falls in [lo, hi]."""
        n = 0
        touched = set()
        atouched = set()   # about|slot keys whose self-writes were erased
        for k in list(self.hist):
            kept = [e for e in self.hist[k] if not (lo <= e[1] <= hi)]
            n += len(self.hist[k]) - len(kept)
            if len(kept) != len(self.hist[k]):
                if k.count("|") == 1:
                    # self-domain registries only — about-other vertexes
                    # (claimer|about|slot) have no slot registries
                    touched.add(k.split("|", 1)[1])
                elif (k.count("|") == 2
                        and k.split("|", 1)[0] == SELF):
                    atouched.add(k.split("|", 1)[1])
                for e in self.hist[k]:
                    if lo <= e[1] <= hi and e[4]:
                        self.rsv.pop(e[4], None)
            if kept:
                self.hist[k] = kept
            else:
                del self.hist[k]
        for slot in touched:
            dedup = []
            for e in self.hist.get(_key(SELF, slot), []):
                if e[2] in WRITES and e[0] not in dedup:
                    dedup.append(e[0])
            if dedup:
                self.prov[slot] = dedup
            else:
                self.prov.pop(slot, None)
            # roll materialized latest-write markers back to the
            # surviving max-day write — and rebuild the slot's lease:
            # an expiry carried by an erased edge must not linger
            # and kill the surviving earlier edge
            self._wday.pop(slot, None)
            self.rvid.pop(slot, None)
            self.exp.pop(slot, None)
            for e in sorted(self.hist.get(_key(SELF, slot), []),
                            key=lambda x: x[1]):
                if e[2] in WRITES:
                    self._wday[slot] = e[1]
                    if e[4]:
                        self.rvid[slot] = e[4]
                    if e[3] is not None:
                        self.exp[slot] = e[3]
        for akey in atouched:
            self._wday.pop(akey, None)
            self.rvid.pop(akey, None)
            for e in sorted(self.hist.get(_key(SELF, akey), []),
                            key=lambda x: x[1]):
                if e[2] in WRITES:
                    self._wday[akey] = e[1]
                    if e[4]:
                        self.rvid[akey] = e[4]
        for s in list(self.drv):
            if not self.edges_of("inference", s):
                del self.drv[s]
        self._prune()
        return n

    # ---- reads (serve.py meters what it touches) ----
    def edges_of(self, source, slot):
        return self.hist.get(_key(source, slot), [])

    def edges_about(self, claimer, about, slot):
        """edges across the about-entity's name forms (alias records
        canonicalize about-names at read, same as person forms);
        about=None is the self entity."""
        if about is None:
            return list(self.edges_of(claimer, slot))
        out = []
        for af in self.forms_of(about):
            out += self.edges_of(f"{claimer}|{af}", slot)
        return out

    def live_at_about(self, claimer, about, slot, day=10**9):
        if about is None:
            return self.live_at(claimer, slot, day)
        edges = self.edges_about(claimer, about, slot)
        if claimer == SELF:
            edges = [e for e in edges if e[2] in AUTH]
        return _edge_at(edges, day)

    def rvid_of(self, about, slot):
        """latest self-write record id for the vertex — about=None is
        the self entity; entity claims keyed by every name form."""
        if about is None:
            return self.rvid.get(slot)
        for af in self.forms_of(about):
            hit = self.rvid.get(f"{af}|{slot}")
            if hit is not None:
                return hit
        return None

    def live_at(self, source, slot, day=10**9):
        edges = self.edges_of(source, slot)
        if source.split("|")[0] == SELF:
            edges = [e for e in edges if e[2] in AUTH]
            if (source == SELF and self.exp.get(slot) is not None
                    and day > self.exp[slot]):
                return None   # slot lease lapsed at read day
        return _edge_at(edges, day)

    def live(self, slot, day=10**9):
        v = self.live_at(SELF, slot, day)
        if v is not None:
            return v
        d = self.drv.get(slot)
        return d["value"] if d else None

    def live_bundle(self, day=10**9, slots=None):
        if slots is not None:
            out = []
            for sl in slots:
                v = self.live(sl, day)
                if v is not None:
                    out.append(v)
            return out
        out = []
        for key, edges in self.hist.items():
            src = key.split("|", 1)[0]
            if src != SELF:
                continue
            v = _edge_at([e for e in edges if e[2] in AUTH], day)
            if v is not None and v not in out:
                out.append(v)
        for d in self.drv.values():
            if d["value"] not in out:
                out.append(d["value"])
        return out

    def asserted(self, slot, value):
        return value in self.prov.get(slot, [])

    def snapshot(self, scope=None):
        """scope={"slots": [...]} produces a purpose-scoped export —
        only the requested slots' edges/state travel (selective
        portability); journal/aliases/revoked are owner metadata and
        always ride along."""
        if (scope or {}).get("purpose") in self.revoked:
            # a purpose-scoped export is a USE — withdrawal refuses it,
            # or the data leaves through the side door the view closed
            return {}
        d = {"hist": self.hist, "prov": self.prov,
             "journal": self.journal,
             "rsv": self.rsv, "drv": self.drv, "exp": self.exp,
             "rvid": self.rvid, "aliases": self.aliases,
             "wday": self._wday, "now": self._now,
             "revoked": sorted(self.revoked)}
        slots = (scope or {}).get("slots")
        if slots:
            keep = set(slots)
            d["hist"] = {k: v for k, v in self.hist.items()
                         if k.count("|") == 1
                         and k.rsplit("|", 1)[-1] in keep}
            live_ids = {e[4] for v in d["hist"].values() for e in v
                        if len(e) > 4 and e[4]}
            d["rsv"] = {k: v for k, v in self.rsv.items()
                        if k in live_ids}
            for reg in ("prov", "drv", "exp", "rvid", "wday"):
                d[reg] = {k: v for k, v in d[reg].items() if k in keep}
            # owner-level registries must not leak out-of-scope data:
            # journal entries carry corrected values, aliases map
            # person identities — the scoped doc gets neither verbatim
            d["journal"] = [j for j in self.journal
                            if j.get("slot") in keep]
            d["aliases"] = {}
        return d

    def restore(self, d):
        """Reload a snapshot() dict — export/import continuity hook."""
        self.hist = {k: [list(e) for e in v] for k, v in d["hist"].items()}
        self.prov = {k: list(v) for k, v in d["prov"].items()}
        self.rsv = {k: tuple(v) for k, v in d["rsv"].items()}
        self.drv = {k: {"premises": dict(v["premises"]),
                        "value": v["value"]}
                    for k, v in d["drv"].items()}
        self.exp = dict(d["exp"])
        self.rvid = dict(d["rvid"])
        self.aliases = dict(d.get("aliases", {}))
        self.revoked = set(d.get("revoked", []))
        self.journal = [dict(e) for e in d.get("journal", [])]
        self._wday = dict(d.get("wday", {}))
        self._now = int(d.get("now", 0))
        self._prune()
