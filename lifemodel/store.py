"""M2 Store: authoritative per-slot index (run-1 champion, s0011 family).

    state: slot -> {"value", "day", "expires"}   last authoritative write wins
    prov:  slot -> [values the person ever asserted, first-assert order]
           (needed for prov probes: "did the person say slot=value" — a
           superseded value was still once said)
    ctx:   compact metadata log of NON-authoritative records
           (day, source, kind, slot only — no text; keeps cost honest)

All contents must stay JSON-serializable: `state()` snapshots it verbatim.
"""
from __future__ import annotations


class SlotIndex:
    def __init__(self):
        self.state: dict = {}
        self.prov: dict = {}
        self.ctx: list = []

    # ---- writes (called only by update.py with authoritative events) ----
    def put(self, slot, value, day, expires):
        self.state[slot] = {"value": value, "day": day, "expires": expires}
        vals = self.prov.setdefault(slot, [])
        if value is not None and value not in vals:
            vals.append(value)

    def remove(self, slot):
        self.state.pop(slot, None)

    def note_ctx(self, ev):
        self.ctx.append({k: ev[k] for k in ("day", "source", "kind", "slot")})

    # ---- reads (used by serve.py; metering measures what it touches) ----
    def live(self, slot, day=10**9):
        e = self.state.get(slot)
        if not e or (e["expires"] and day > e["expires"]):
            return None
        return e["value"]

    def asserted(self, slot, value):
        return value in self.prov.get(slot, [])

    def live_bundle(self, day=10**9, slots=None):
        xs = slots if slots is not None else list(self.state)
        return [self.state[s]["value"] for s in xs
                if s in self.state
                and not (self.state[s]["expires"] and day > self.state[s]["expires"])]

    def snapshot(self):
        return {"state": self.state, "prov": self.prov, "ctx": self.ctx}
