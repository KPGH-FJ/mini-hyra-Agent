"""M3 Update: how an Event changes the asset.

v2 semantics (P3 r2 fold — TMS-style premise maintenance won the family
race over pure event-sourced replay at equal quality with ~320x cheaper
reads; see results/life_model_v3/FAMILY_RACE.md):

    EVERY normalized event is appended as a temporal edge on its source
    vertex — including hearsay and assistant suggestions. Whether an
    event may influence a given answer is decided at READ time (serve
    queries only the "self" vertex for self-state), not at write time.

    `kind="derived"` records additionally register premises resolved
    from their `supports` record ids, and EVERY mutation ends in a
    premise fixpoint inside the store (`_prune`): a derived entry dies
    the moment any premise slot is deleted or its live value diverges —
    transitively, since premises may themselves be derived. The
    mechanism lives in store.py because it is a state invariant that
    must hold after every write path (append, forget, restore) — same
    reason prov rebuild lives next to edge erasure.

    update-vs-revision (Katsuno–Mendelzon, from the M3 survey): a
    `correction`/`retraction` revises what we *recorded*; an `update`
    records that the *world* changed. Both are edges; the distinction
    matters only through the premise check — a correction that changes
    a premised value kills the dependent, an update that doesn't touch
    it leaves it standing.
"""
from __future__ import annotations


def apply(store, ev: dict) -> None:
    store.append(ev)
