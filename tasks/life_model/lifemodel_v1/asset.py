"""Eval adapter: drives the real lifemodel package through the bench.

Not an evolved solution — the reference implementation of the system
under research, scored by the same evaluator-driven protocol so module
upgrades show up as score deltas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lifemodel import LifeModel  # noqa: E402

_m = LifeModel()


def ingest(rec):
    _m.ingest(rec)


def answer(probe):
    return _m.answer(probe)


def forget(scope):
    _m.forget(scope)


def correct(slot, value):
    _m.correct(slot, value)


def revoke_purpose(purpose):
    _m.revoke_purpose(purpose)


def state(scope=None):
    return _m.state(scope)


def import_state(d):
    _m.import_state(d)


def probe_bytes():
    return _m.probe_bytes()
