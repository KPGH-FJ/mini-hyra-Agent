"""M5 Control: user-facing mutation + export, with an operation journal.

v1 semantics (TemporalGraph store):
    correct(slot, value) -> appended as an authoritative correction edge
                            at the latest observed day (also enters prov —
                            the person asserted it, by definition).
    forget(scope)        -> {"slot": s}: every edge of the slot erased
                            across ALL vertices — the TemporalGraph's
                            cascade-clean erase (history AND derived
                            state AND prov, one operation).
                            {"day_gte": a, "day_lte": b}: erase edges
                            whose from_day falls in the range.
    journal             -> append-only record of every control operation.

Cascade invalidation of derived entries still isn't v1 — that's the
M5+M3 evolution point (supports-tracking).
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
        self.store.append({"source": "self", "kind": "correction",
                           "slot": slot, "value": value,
                           "day": self._day, "expires": None})
        self.journal.append({"op": "correct", "slot": slot, "value": value})

    def forget(self, scope: dict) -> None:
        if "slot" in scope:
            n = self.store.forget_slot(scope["slot"])
        else:
            n = self.store.forget_range(scope.get("day_gte", 0),
                                        scope.get("day_lte", 10**9))
        self.journal.append({"op": "forget", "scope": scope, "removed": n})

    def revoke_purpose(self, purpose: str) -> None:
        """Withdraw consent for one use — the data stays, the view refuses."""
        self.store.revoked.add(purpose)
        self.journal.append({"op": "revoke_purpose", "purpose": purpose})

    def export(self, snapshot: dict) -> dict:
        self.journal.append({"op": "export"})
        return {"asset": snapshot, "journal": self.journal}
