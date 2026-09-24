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

forget(slot) erases every edge of the slot across ALL sources —
cascade-clean by construction, no separate history purge.

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

    # ---- writes ----
    def append(self, ev: dict) -> None:
        """Every normalized event becomes an edge on its source vertex."""
        if ev["slot"] is None:
            return
        self.hist.setdefault(_key(ev["source"], ev["slot"]), []).append(
            [ev["value"], ev["day"], ev["kind"], ev.get("expires")])
        if ev["source"] == SELF and ev["kind"] in WRITES:
            vals = self.prov.setdefault(ev["slot"], [])
            if ev["value"] not in vals:
                vals.append(ev["value"])

    def forget_slot(self, slot) -> int:
        """Erase the slot across every vertex (history AND derivations)."""
        keys = [k for k in self.hist if k.split("|", 1)[1] == slot]
        n = len(keys) + (slot in self.prov)
        for k in keys:
            del self.hist[k]
        self.prov.pop(slot, None)
        return n

    def forget_range(self, lo, hi) -> int:
        """Erase edges whose from_day falls in [lo, hi]."""
        n = 0
        touched = set()
        for k in list(self.hist):
            kept = [e for e in self.hist[k] if not (lo <= e[1] <= hi)]
            n += len(self.hist[k]) - len(kept)
            if len(kept) != len(self.hist[k]):
                touched.add(k.split("|", 1)[1])
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
        return n

    # ---- reads (serve.py meters what it touches) ----
    def edges_of(self, source, slot):
        return self.hist.get(_key(source, slot), [])

    def live_at(self, source, slot, day=10**9):
        edges = self.edges_of(source, slot)
        if source == SELF:
            edges = [e for e in edges if e[2] in AUTH]
        return _edge_at(edges, day)

    def live(self, slot, day=10**9):
        return self.live_at(SELF, slot, day)

    def live_bundle(self, day=10**9, slots=None):
        if slots is not None:
            out = []
            for sl in slots:
                v = self.live_at(SELF, sl, day)
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
        return out

    def asserted(self, slot, value):
        return value in self.prov.get(slot, [])

    def snapshot(self):
        return {"hist": self.hist, "prov": self.prov}

    def restore(self, d):
        """Reload a snapshot() dict — export/import continuity hook."""
        self.hist = {k: [list(e) for e in v] for k, v in d["hist"].items()}
        self.prov = {k: list(v) for k, v in d["prov"].items()}
