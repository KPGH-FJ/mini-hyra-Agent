"""M3 Update: how an Event changes the asset.

v0 semantics (direct overwrite — TMS-style dependency propagation is the
first evolution candidate for this module):

    authoritative write (statement/update/correction) -> supersede slot
    authoritative retraction                          -> delete slot
    non-authoritative event                           -> ctx note only

Expiry is lazy: an `expires` marker is stored, applied at read time by
store.live()/live_bundle() — nothing is deleted when the day passes.
"""
from __future__ import annotations


def apply(store, ev: dict) -> None:
    if not ev["authoritative"]:
        store.note_ctx(ev)
        return
    if ev["kind"] == "retraction":
        store.remove(ev["slot"])
        return
    if ev["kind"] in ("statement", "update", "correction"):
        store.put(ev["slot"], ev["value"], ev["day"], ev["expires"])
