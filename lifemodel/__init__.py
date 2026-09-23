"""lifemodel — LifeModel system v0 skeleton.

Five modules behind one facade (see docs/LIFEMODEL_ARCHITECTURE.md):

    M1 ingest.py   — record -> normalized Event (source/kind/reliability)
    M2 store.py    — authoritative per-slot index + provenance (s0011 champion)
    M3 update.py   — apply(event) semantics: supersede/retract/expire
    M4 serve.py    — probe answering with honest byte metering
    M5 control.py  — correct/forget/export + operation journal
"""
from .model import LifeModel

__all__ = ["LifeModel"]
__version__ = "0.1.0"
