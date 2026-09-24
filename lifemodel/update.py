"""M3 Update: how an Event changes the asset.

v1 semantics (with the TemporalGraph store):
    EVERY normalized event is appended as a temporal edge on its source
    vertex — including hearsay and assistant suggestions. Whether an
    event may influence a given answer is decided at READ time (serve
    queries only the "self" vertex for self-state), not at write time.

    This is the event-sourcing lesson from the M2 round: never throw
    records away at ingest. History is the asset; views are derivations.

    update-vs-revision (Katsuno–Mendelzon, from the M3 survey): a
    `correction`/`retraction` revises what we *recorded*; an `update`
    records that the *world* changed. Both are just edges here — the
    distinction only matters for derived entries, which don't exist yet.

Remaining M3 evolution target (next round): derived entries carrying
`supports=[edge]` so that forgetting/correcting one edge cascades to
every conclusion built on it (TMS-style dependency tracking).
"""
from __future__ import annotations


def apply(store, ev: dict) -> None:
    store.append(ev)
