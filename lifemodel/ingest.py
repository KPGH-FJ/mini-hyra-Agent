"""M1 Ingest: raw record -> normalized Event.

v0 policy (intentionally minimal — the evolution point):
    authoritative  = source == "self" and kind in
                     {statement, update, correction, retraction}
    hearsay/suggestion/other/assistant/device/doc records are kept as
    non-authoritative context (metadata only — they inform provenance
    negatives but never write state).
"""
from __future__ import annotations

SOURCES = {"self", "other", "assistant", "device", "doc", "inference"}
KINDS = {"statement", "update", "correction", "retraction",
         "suggestion", "hearsay", "derived"}
WRITES = {"statement", "update", "correction"}


def normalize(rec: dict) -> dict:
    """Return an Event dict. Unknown/missing fields become explicit None so
    downstream modules never guess."""
    src = str(rec.get("source", ""))
    kind = str(rec.get("kind", ""))
    ev = {
        "id": rec.get("id"),
        "day": int(rec.get("day", 0)),
        "source": src,
        "kind": kind,
        "slot": rec.get("slot"),
        "value": rec.get("value"),
        "expires": rec.get("expires_day"),
        "supports": rec.get("supports"),
        "authoritative": src == "self" and kind in (WRITES | {"retraction"}),
        "text": rec.get("text", ""),
    }
    return ev
