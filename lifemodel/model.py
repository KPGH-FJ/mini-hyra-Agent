"""LifeModel facade — the single entry point per docs/LIFEMODEL_ARCHITECTURE.md.

Each module is a plain object wired in __init__; evolution swaps one module
at a time by reimplementing that module's contract, never the facade.
"""
from __future__ import annotations

import json

from . import ingest as m_ingest
from . import serve as m_serve
from . import update as m_update
from .control import Control
from .store import TemporalGraph


class LifeModel:
    def __init__(self):
        self.store = TemporalGraph()      # M2
        self.control = Control(self.store)  # M5

    # ---- evaluator/record pipeline (M1 -> M3) ----
    def ingest(self, rec: dict) -> None:
        ev = m_ingest.normalize(rec)
        self.control.observe_day(ev["day"])
        m_update.apply(self.store, ev)

    # ---- usage (M4) ----
    def answer(self, probe: dict) -> str:
        return m_serve.answer(self.store, probe)

    # ---- user control (M5) ----
    def correct(self, slot, value) -> None:
        self.control.correct(slot, value)

    def forget(self, scope: dict) -> None:
        self.control.forget(scope)

    def export(self) -> dict:
        return self.control.export(self.store.snapshot())

    # ---- honest cost surface (measured, not declared) ----
    def state(self) -> dict:
        return self.store.snapshot()

    def import_state(self, d: dict) -> None:
        self.store.restore(d)

    def probe_bytes(self) -> int:
        return m_serve.probe_bytes()

    def asset_bytes(self) -> int:
        return len(json.dumps(self.state(), ensure_ascii=False))
