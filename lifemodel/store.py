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

import copy

from .replay import TemporalReplayUnavailable, replay

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
        self._pending_drv: list = []  # derived records awaiting premise
        # resolution — a premise record that arrives later in feed order
        # but earlier in DAY defers registration (truth replays day-
        # sorted), it doesn't kill the derived at birth
        self._drv_log: list = []   # every derived event ever appended
        # ({slot,value,supports,day,seq}) — the log the drv registry is
        # derived from; an erasure rewrites the underlying log, so drv
        # state must be REBUILT, not merely re-pruned: a derived pruned
        # by a killer that was itself erased comes back alive
        self._drv_seq: int = 0  # arrival-order high-water mark; never reuse
        # a surviving event's seq after erasure creates gaps in the log
        self.exp: dict = {}   # slot -> expires_day (slot-scoped lease)
        self.rvid: dict = {}  # slot -> latest self-write record id (prov2)
        self.aliases: dict = {}  # alias -> canonical person (M1)
        self.revoked: set = set()  # purposes whose use is withdrawn (M5)
        self.journal: list = []    # control-op log, survives export (M5)
        self._wday: dict = {}   # slot -> day of latest self write (OOO)
        self._rday: dict = {}   # record id -> authored day (premise
        # day-order checks for deferred derived resolution)
        self._now: int = 0    # latest observed event day (read-day clock)
        self._next_arrival_seq: int = 0
        self._legacy_order: bool = False

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
        """Stage exceptional historical writes before publishing any change."""
        if (ev["slot"] is not None and ev["source"] == SELF
                and not ev.get("about") and ev["kind"] in AUTH
                and ev["day"] < self._now):
            affected = self._affected_derived(
                {ev["slot"]}, {ev["id"]} if ev.get("id") else ())
            if affected:
                staged = copy.deepcopy(self)
                staged._append(ev)
                staged._replay_drv(affected)
                self.__dict__.update(staged.__dict__)
                return
        self._append(ev)

    def _append(self, ev: dict) -> None:
        """Every normalized event becomes an edge on its source vertex."""
        if ev["slot"] is None:
            return
        self._now = max(self._now, ev["day"])
        if ev["kind"] == "alias":
            self.aliases[ev["slot"]] = ev["value"]
            return
        if ev.get("id"):
            self.rsv[ev["id"]] = (ev["slot"], ev["value"])
            self._rday[ev["id"]] = ev["day"]
        who = (f'{ev["source"]}|{ev["about"]}' if ev.get("about")
               else ev["source"])   # claimer|about|slot vertex
        arrival = self._next_arrival_seq
        self._next_arrival_seq += 1
        self.hist.setdefault(_key(who, ev["slot"]), []).append(
            [ev["value"], ev["day"], ev["kind"], ev.get("expires"),
             ev.get("id"), arrival])
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
            dev = {"slot": ev["slot"], "value": ev["value"],
                   "supports": list(ev.get("supports") or []),
                   "day": ev["day"], "id": ev.get("id"),
                   "src": ev.get("source", "inference"),
                   "vertex": _key(who, ev["slot"]),
                   "arrival_seq": arrival,
                   "seq": self._drv_seq}
            self._drv_seq += 1
            self._drv_log.append(dev)
            # Use the same per-record day gate for an already-resolved
            # premise as for a premise that arrives later.
            if self._reg_drv(dev) == "pending":
                self._pending_drv.append(dev)
        self._prune()

    def _premises(self, ev):
        """supports=[record ids] -> {premise_slot: premised_value}.
        Returns None while any support rid is unresolved OR resolves to
        a record authored after the derived's own day — truth replays
        events day-sorted, so a premise that postdates the derived
        means it was dead at birth in day order too (never registers)."""
        out = {}
        for rid in ev.get("supports") or []:
            if rid not in self.rsv:
                return None
            s, v = self.rsv[rid]
            out[s] = v
        return out

    def _premise_days(self, ev):
        """premise record days (parallel to _premises) for the
        day-order gate; None if any support is still unresolved."""
        out = {}
        for rid in ev.get("supports") or []:
            if rid not in self.rsv:
                return None
            s, _v = self.rsv[rid]
            out[s] = self._rday.get(rid, 0)
        return out

    def _live_val(self, slot):
        """Self-authoritative value, else the live derived value."""
        v = self.live_at(SELF, slot, self._now)
        if v is not None:
            return v
        d = self.drv.get(slot)
        return d["value"] if d else None

    def _reg_drv(self, dev):
        """Register one derived event if resolvable + day-gated;
        returns 'live' | 'pending' | 'dead'."""
        pre = {}
        for rid in dev["supports"]:
            if rid not in self.rsv or rid not in self._rday:
                return "pending"
            if self._rday[rid] > dev["day"]:
                return "dead"
            s, v = self.rsv[rid]
            pre[s] = v
        self.drv[dev["slot"]] = {"premises": pre, "value": dev["value"]}
        return "live"

    def _affected_derived(self, slots, record_ids=(), derived_slots=()):
        changed, outputs = set(slots), set(derived_slots)
        changed.update(outputs)
        removed = set(record_ids)
        # Cached premises are useful dependency evidence in old snapshots
        # even when their replay log is incomplete. Missing history is a
        # reason to reject an affected replay, never to skip invalidation.
        if changed or removed:
            logged = {d['slot'] for d in self._drv_log}
            outputs.update(k.rsplit('|', 1)[-1] for k, edges in self.hist.items()
                           if any(e[2] == 'derived' for e in edges)
                           and k.rsplit('|', 1)[-1] not in logged)
            changed.update(outputs)
        while True:
            before = len(outputs)
            for dev in self._drv_log:
                if (dev["slot"] in changed or removed.intersection(dev['supports']) or any(
                        rid in self.rsv and self.rsv[rid][0] in changed
                        for rid in dev["supports"])):
                    outputs.add(dev["slot"])
                    changed.add(dev["slot"])
            for slot, entry in self.drv.items():
                if slot in changed or changed.intersection(entry['premises']):
                    outputs.add(slot)
                    changed.add(slot)
            if len(outputs) == before:
                return outputs

    def _replay_drv(self, affected):
        if not affected:
            return
        drv, pending = replay(self.hist, self._drv_log, self._now, affected)
        self.drv = {s: d for s, d in self.drv.items() if s not in affected}
        self.drv.update(drv)
        self._pending_drv = [d for d in self._pending_drv
                             if d["slot"] not in affected] + pending
        self._prune()

    def _rebuild_drv(self):
        if getattr(self, '_defer_rebuild', False):
            return
        self._replay_drv(getattr(self, "_erase_affected",
                                 {d["slot"] for d in self._drv_log}))

    def _refresh_record_ids(self, record_ids):
        """Erasure rewrites duplicate-ID last-arrival caches as well."""
        for rid in record_ids:
            entries = [(k, e) for k, edges in self.hist.items()
                       for e in edges if e[4] == rid]
            if not entries:
                self.rsv.pop(rid, None)
                self._rday.pop(rid, None)
                continue
            known = [(k, e) for k, e in entries if len(e) > 5]
            if known:
                vertex, edge = max(known, key=lambda pair: pair[1][5])
            elif len({k for k, _e in entries}) == 1:
                vertex, edge = entries[-1]
            elif all((k.rsplit('|', 1)[-1], e[:2]) ==
                     (entries[0][0].rsplit('|', 1)[-1], entries[0][1][:2])
                     for k, e in entries):
                vertex, edge = entries[0]
            else:
                raise TemporalReplayUnavailable('legacy duplicate record ID order is ambiguous')
            self.rsv[rid] = (vertex.rsplit('|', 1)[-1], edge[0])
            self._rday[rid] = edge[1]

    def _erase_atomically(self, method, selected, *args):
        staged = copy.deepcopy(self)
        slots = {k.rsplit('|', 1)[-1] for k, e in selected
                 if k.count('|') == 1 and k.split('|')[0] == SELF and e[2] in AUTH}
        # A non-authoritative event may still be the clock tick that
        # killed a leased premise before its later renewal. Removing that
        # tick can change derived history without changing any owner edge.
        removed_days = {e[1] for _k, e in selected}
        slots.update(k.rsplit('|', 1)[-1] for k, edges in self.hist.items()
                     if k.count('|') == 1 and k.split('|')[0] == SELF
                     and any(e[2] in WRITES and e[3] is not None
                             and any(e[1] <= day and e[3] < day for day in removed_days)
                             for e in edges))
        ids = {e[4] for _k, e in selected if e[4]}
        derived = {k.rsplit('|', 1)[-1] for k, e in selected if e[2] == 'derived'}
        staged._erase_affected = self._affected_derived(slots, ids, derived)
        staged._defer_rebuild = True
        result = getattr(staged, method)(*args)
        del staged._defer_rebuild
        staged._refresh_record_ids(ids | (set(self.rsv) - set(staged.rsv)))
        staged._rebuild_drv()
        del staged._erase_affected
        self.__dict__.update(staged.__dict__)
        return result

    def _prune(self):
        """Fixpoint sweep: resolve pending derived, then kill drv
        entries with a dead/diverged premise."""
        kept = []
        for dev in self._pending_drv:
            st = self._reg_drv(dev)
            if st == "pending":
                kept.append(dev)        # premise record not arrived yet
            # 'dead' drops for good; 'live' registered via _reg_drv
        self._pending_drv = kept
        moved = True
        while moved:
            moved = False
            for s in list(self.drv):
                if any(self._live_val(ps) != pv
                       for ps, pv in self.drv[s]["premises"].items()):
                    del self.drv[s]
                    moved = True

    def _erase_record_refs(self, removed_ids, removed_vertices=()) -> None:
        """Physically erase dependents of permanently erased records.

        This is narrower than deleting a whole derived slot: an
        independent user write or derivation on that slot must survive.
        Range erasure does not use this helper: deleting a killer there
        is allowed to revive an earlier surviving derived event.
        """
        removed = set(removed_ids)
        vertices = set(removed_vertices)
        # Old no-id logs cannot prove their entity from current edges:
        # their original edge may already have been erased. Refuse an
        # affected legacy deletion before changing any state.
        for dev in self._drv_log:
            if not dev.get("id") and "vertex" not in dev and any(
                    k.split("|", 1)[0] == dev["src"]
                    and k.rsplit("|", 1)[-1] == dev["slot"] for k in vertices):
                raise ValueError("ambiguous derived event: legacy record "
                                 "has no id or vertex")
        erased = []
        remaining = self._drv_log
        while True:
            kept, changed = [], False
            for dev in remaining:
                if (dev.get("id") in removed or dev.get("vertex") in vertices
                        or any(rid in removed for rid in dev["supports"])):
                    erased.append(dev)
                    if dev.get("id"):
                        removed.add(dev["id"])
                    changed = True
                else:
                    kept.append(dev)
            remaining = kept
            if not changed:
                break
        edge_plan = []
        for dev in erased:
            # The log predates entity metadata. An existing record id
            # still identifies its exact edge across two/three-part
            # vertices; do not assume every derived edge is src|slot.
            if not dev.get("id") and "vertex" not in dev:
                raise ValueError("ambiguous derived event: legacy record "
                                 "has no id or vertex")
            keys = [k for k, edges in self.hist.items()
                    if k.split("|", 1)[0] == dev["src"]
                    and k.rsplit("|", 1)[-1] == dev["slot"]
                    and ("vertex" not in dev or k == dev["vertex"])
                    and any(e[2] == "derived"
                            and ("arrival_seq" not in dev or
                                 len(e) > 5 and e[5] == dev["arrival_seq"])
                            and ((dev.get("id") and e[4] == dev["id"])
                                 or (not dev.get("id") and not e[4]
                                     and e[1] == dev["day"]
                                     and e[0] == dev["value"]))
                            for e in edges)]
            if len(keys) > 1:
                # Legacy logs have no about field. Do not guess which
                # entity owns an id-less event and erase an independent
                # same-slot fact. Preflight the whole closure before any
                # mutation so the caller can report a failed deletion.
                raise ValueError("ambiguous derived event: cannot safely erase "
                                 "records across multiple vertices")
            edge_plan.append((dev, keys))
        self._drv_log = remaining
        for dev, keys in edge_plan:
            for key in keys:
                edges = self.hist.get(key, [])
                # One log event corresponds to one edge. Do not erase
                # independent explicit writes on the same output slot.
                for i, edge in enumerate(edges):
                    if (edge[2] == "derived"
                            and ("arrival_seq" not in dev or
                                 len(edge) > 5 and edge[5] == dev["arrival_seq"])
                            and ((dev.get("id") and edge[4] == dev["id"])
                                 or (not dev.get("id") and not edge[4]
                                     and edge[1] == dev["day"]
                                     and edge[0] == dev["value"]))):
                        del edges[i]
                        break
                if key in self.hist and not edges:
                    del self.hist[key]
        for rid in removed:
            self.rsv.pop(rid, None)
            self._rday.pop(rid, None)

    def forget_slot(self, slot) -> int:
        selected = [(k, e) for k, edges in self.hist.items()
                    if k.rsplit('|', 1)[-1] == slot for e in edges]
        return self._erase_atomically("_forget_slot", selected, slot)

    def _forget_slot(self, slot) -> int:
        """Erase the slot across every vertex (history AND derivations)."""
        keys = [k for k in self.hist if k.rsplit("|", 1)[-1] == slot]
        n = len(keys) + (slot in self.prov)
        removed_ids = {rid for rid, (s, _v) in self.rsv.items() if s == slot}
        for k in keys:
            removed_ids.update(e[4] for e in self.hist[k] if e[4])
        self._erase_record_refs(removed_ids, keys)
        for k in keys:
            self.hist.pop(k, None)
        self.prov.pop(slot, None)
        self.drv.pop(slot, None)
        self.exp.pop(slot, None)
        for reg in (self.rvid, self._wday):
            for key in list(reg):
                if key.rsplit("|", 1)[-1] == slot:
                    del reg[key]
        self._drv_log = [d for d in self._drv_log if d["slot"] != slot]
        # Keep auditable operation metadata without retaining a value
        # the owner explicitly asked to erase.
        for entry in self.journal:
            if entry.get("slot") == slot:
                entry.pop("value", None)
        self._rebuild_drv()   # dependents of the forgotten slot die too
        return n

    def forget_about(self, about) -> int:
        selected = [(k, e) for k, edges in self.hist.items()
                    if k.count("|") == 2 and k.split("|")[1] in self.forms_of(about)
                    for e in edges]
        return self._erase_atomically("_forget_about", selected, about)

    def _forget_about(self, about) -> int:
        """Forget a person: erase every vertex about them (all claimers,
        all name forms of the entity)."""
        keys = [k for k in self.hist
                if k.count("|") == 2
                and k.split("|")[1] in self.forms_of(about)]
        removed_ids = {e[4] for k in keys for e in self.hist[k] if e[4]}
        self._erase_record_refs(removed_ids, keys)
        for k in keys:
            self.hist.pop(k, None)
            akey = k.split("|", 1)[1]
            self._wday.pop(akey, None)
            self.rvid.pop(akey, None)
        self._rebuild_drv()
        return len(keys)

    def forget_range(self, lo, hi) -> int:
        selected = [(k, e) for k, edges in self.hist.items()
                    for e in edges if lo <= e[1] <= hi]
        return self._erase_atomically("_forget_range", selected, lo, hi)

    def _forget_range(self, lo, hi) -> int:
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
        self._drv_log = [d for d in self._drv_log
                         if not (lo <= d["day"] <= hi)]
        self._rebuild_drv()   # rewritten log revives what the erased
        # killer had pruned, and buries what lost its own edge
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
             "rday": self._rday,
             "pending_drv": self._pending_drv,
             "drv_log": self._drv_log,
             "revoked": sorted(self.revoked),
             "temporal_order_version": 1,
             "legacy_order": self._legacy_order,
             "next_arrival_seq": self._next_arrival_seq}
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
            # Do not turn a conditional claim into an unconditional one
            # by stripping just its premises. Omit the entire active
            # derivation when its justification cannot leave this scope.
            d["drv"] = {k: v for k, v in d["drv"].items()
                        if all(s in keep for s in v["premises"])}
            # owner-level registries must not leak out-of-scope data:
            # journal entries carry corrected values, aliases map
            # person identities — the scoped doc gets neither verbatim
            d["journal"] = [j for j in self.journal
                            if j.get("slot") in keep]
            d["aliases"] = {}
            # the derived-event log and the pending queue carry
            # out-of-scope derived VALUES verbatim — scope them too,
            # and only keep day-marks for the rids that survive
            d["drv_log"] = [e for e in d["drv_log"]
                            if e["slot"] in keep
                            and e.get("vertex", "").count("|") <= 1]
            d["pending_drv"] = [e for e in d["pending_drv"]
                                if e["slot"] in keep
                                and e.get("vertex", "").count("|") <= 1]
            d["rday"] = {k: v for k, v in d["rday"].items()
                         if k in live_ids}
            # Absolute sequence gaps/high-water reveal excluded activity.
            # Rank-rebase only exported events, always on independent copies.
            ranks = {seq: i for i, seq in enumerate(sorted(
                e[5] for edges in d["hist"].values() for e in edges
                if len(e) > 5))}
            d["hist"] = {k: [e[:5] + [ranks[e[5]]] if len(e) > 5
                              else list(e) for e in edges]
                         for k, edges in d["hist"].items()}
            for reg in ("drv_log", "pending_drv"):
                d[reg] = [dict(e, arrival_seq=ranks[e["arrival_seq"]])
                          if "arrival_seq" in e else copy.deepcopy(e)
                          for e in d[reg]]
            derived_ranks = {seq: i for i, seq in enumerate(sorted(
                e['seq'] for e in d['drv_log']))}
            for reg in ('drv_log', 'pending_drv'):
                d[reg] = [dict(e, seq=derived_ranks[e['seq']]) for e in d[reg]]
            d["next_arrival_seq"] = len(ranks)
            d["legacy_order"] = any(len(e) < 6 for edges in d["hist"].values()
                                    for e in edges)
            # IDs may be reused across slots. Filtering the global cache
            # by ID alone can copy an excluded record's value/date.
            projected = TemporalGraph()
            projected.hist = d['hist']
            projected._refresh_record_ids(live_ids)
            d['rsv'], d['rday'] = projected.rsv, projected._rday
        return d

    def restore(self, d):
        staged = TemporalGraph()
        staged._restore(copy.deepcopy(d))
        self.__dict__.update(staged.__dict__)

    def _restore(self, d):
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
        self._rday = dict(d.get("rday", {}))
        self._pending_drv = [dict(e) for e in d.get("pending_drv", [])]
        self._drv_log = [dict(e) for e in d.get("drv_log", [])]
        self._drv_seq = max((e["seq"] for e in self._drv_log), default=-1) + 1
        self._restore_order(d)
        self._prune()

    def _restore_order(self, d):
        version = d.get("temporal_order_version")
        marked = "temporal_order_version" in d
        if marked and (type(version) is not int or version != 1):
            raise ValueError("unsupported temporal order version")
        if marked and any(key not in d for key in (
                'legacy_order', 'next_arrival_seq', 'rday', 'drv_log', 'pending_drv')):
            raise ValueError("ordered snapshot lacks required temporal metadata")
        legacy = d.get("legacy_order") if marked else True
        if type(legacy) is not bool:
            raise ValueError("legacy_order must be a boolean")
        orders = {}
        missing = False
        for vertex, edges in self.hist.items():
            previous = -1
            for edge in edges:
                if len(edge) == 4 and not marked:
                    edge.append(None)
                if len(edge) not in (5, 6):
                    raise ValueError("invalid history edge shape")
                if len(edge) == 5:
                    if marked and not legacy:
                        raise ValueError("complete order requires every edge sequence")
                    missing = True
                    if previous >= 0:
                        raise ValueError("legacy edge follows a newly ordered edge")
                    continue
                seq = edge[5]
                if (not marked or type(seq) is not int or seq < 0
                        or seq in orders or seq <= previous):
                    raise ValueError("invalid or duplicate arrival sequence")
                orders[seq] = (vertex, edge)
                previous = seq
        by_id = {}
        for vertex, edges in self.hist.items():
            for edge in edges:
                if edge[4]:
                    by_id.setdefault(edge[4], []).append((vertex, edge))
        if marked and 'rday' not in d:
            raise ValueError("ordered snapshot lacks record dates")
        for rid, entries in by_id.items():
            ordered = [(v, e) for v, e in entries if len(e) > 5]
            latest = max(ordered, key=lambda item: item[1][5]) if ordered else None
            if latest is None and len({v for v, _e in entries}) == 1:
                latest = entries[-1]  # one vertex retains its arrival order
            expected_day = latest[1][1] if latest is not None else None
            if rid not in self._rday:
                if marked:
                    raise ValueError("ordered snapshot lacks a retained record date")
                if expected_day is not None:
                    self._rday[rid] = expected_day
            elif (type(self._rday[rid]) is not int or
                  expected_day is not None and self._rday[rid] != expected_day):
                raise ValueError("record date contradicts retained history")
            if marked and latest is not None:
                vertex, edge = latest
                if self.rsv.get(rid) != (vertex.rsplit('|', 1)[-1], edge[0]):
                    raise ValueError("record value contradicts retained history")
        births = set()
        for dev in self._drv_log:
            if marked and (not isinstance(dev.get('supports'), list)
                           or type(dev.get('seq')) is not int or dev['seq'] < 0
                           or type(dev.get('day')) is not int):
                raise ValueError("invalid derived birth metadata")
            seq = dev.get("arrival_seq")
            if seq is None and legacy:
                if any(e[2] == 'derived' and e[1] == dev['day']
                       and e[4] == dev.get('id') and len(e) > 5
                       for e in self.hist.get(dev.get('vertex',
                           f"{dev['src']}|{dev['slot']}"), [])):
                    raise ValueError("ordered derived edge lacks ordered birth metadata")
                missing = True
                continue
            if type(seq) is not int or seq not in orders or seq in births:
                raise ValueError("derived birth lacks a valid arrival sequence")
            births.add(seq)
            vertex, edge = orders[seq]
            if (vertex != dev.get("vertex") or edge[2] != "derived"
                    or vertex.rsplit('|', 1)[-1] != dev['slot']
                    or vertex.split('|', 1)[0] != dev['src']
                    or edge[1] != dev["day"] or edge[0] != dev["value"]
                    or edge[4] != dev.get("id")):
                raise ValueError("derived birth does not match its history edge")
        if any(edge[2] == 'derived' and seq not in births
               for seq, (_vertex, edge) in orders.items()):
            raise ValueError("ordered derived edge is absent from derived log")
        for pending in self._pending_drv:
            if pending not in self._drv_log:
                raise ValueError("pending birth is absent from derived log")
        next_seq = d.get("next_arrival_seq", 0) if marked else 0
        if (type(next_seq) is not int or next_seq < 0
                or orders and next_seq <= max(orders)):
            raise ValueError("invalid arrival sequence high-water mark")
        self._next_arrival_seq = next_seq
        self._legacy_order = missing
