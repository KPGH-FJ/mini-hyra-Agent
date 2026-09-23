"""M5 Control: user-facing mutation + export, with an operation journal.

v0 semantics:
    correct(slot, value) -> treated as an authoritative correction write
                            at the latest observed day (also enters prov —
                            the person asserted it, by definition).
    forget(scope)        -> removes state AND prov entries for the scope:
                            {"slot": s} or {"day_gte": a, "day_lte": b}
                            (slot or day range); derived data touching the
                            scope is removed — retraction of prov too.
    journal            -> append-only record of every control operation.

Cascade invalidation of derived answers isn't v0 — that's the M5+M3
evolution point.
"""
from __future__ import annotations


class Control:
    def __init__(self, store):
        self.store = store
        self.journal: list = []
        self._day = 0

    def observe_day(self, day: int) -> None:
        self._day = max(self._day, day)

    def correct(self, slot, value) -> None:
        self.store.put(slot, value, self._day, None)
        self.journal.append({"op": "correct", "slot": slot, "value": value})

    def forget(self, scope: dict) -> None:
        n = 0
        if "slot" in scope:
            s = scope["slot"]
            n += (s in self.store.state) + (s in self.store.prov)
            self.store.state.pop(s, None)
            self.store.prov.pop(s, None)
            self.store.ctx = [c for c in self.store.ctx if c["slot"] != s]
        else:
            lo, hi = scope.get("day_gte", 0), scope.get("day_lte", 10**9)
            for s in [s for s, e in self.store.state.items()
                      if lo <= e["day"] <= hi]:
                self.store.state.pop(s, None); n += 1
            self.store.ctx = [c for c in self.store.ctx
                              if not (lo <= c["day"] <= hi)]
        self.journal.append({"op": "forget", "scope": scope, "removed": n})

    def export(self, snapshot: dict) -> dict:
        self.journal.append({"op": "export"})
        return {"asset": snapshot, "journal": self.journal}
