"""Bench regression sweep — drives the reference implementations through
full generated lifecycles and asserts the frontier asset stays clean.

Run:  python tests/test_bench_sweep.py [seed ...]  (default: 7 301 330)
      python tests/test_bench_sweep.py --range 340 350

The contract suite pins semantics on hand-built lifecycles; this sweep
catches divergence between the generator's truth model and an
implementation across the whole 90-day lifecycle — the failures that
only appear at scale (derived revival inside SKIP windows, post-export
erasure, scoped-export leaks, entity-alias ordering).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tasks" / "life_model" / "bench"))
sys.path.insert(0, str(ROOT / "tasks" / "life_model"))

_argv, sys.argv = sys.argv, [sys.argv[0]]  # evaluate.py reads argv[2]
import evaluate as ev  # noqa: E402
sys.argv = _argv
from generator import generate  # noqa: E402

LIFEMODEL_V1 = ROOT / "tasks" / "life_model" / "lifemodel_v1"


def sweep(seeds, density=1, impl=None):
    """Fresh asset per seed — never reuse one instance across drives."""
    tot = ok = 0
    fails = []
    for seed in seeds:
        records, probes, truth, meta = generate(seed, density=density)
        asset = impl() if impl else ev.load_asset(LIFEMODEL_V1)
        rows, cost, how = ev.drive(asset, [dict(r) for r in records],
                                   probes, meta)
        for r in rows:
            tot += 1
            if r["score"] >= 1:
                ok += 1
            else:
                fails.append((seed, r["probe"]["type"],
                              str(r.get("answer"))[:40]))
    return ok, tot, fails


def main():
    args = sys.argv[1:]
    if args[:1] == ["--range"]:
        seeds = list(range(int(args[1]), int(args[2])))
    else:
        seeds = [int(s) for s in args] or [7, 301, 330]
    ok, tot, fails = sweep(seeds)
    print(f"{ok}/{tot} clean across seeds {seeds}")
    for f in fails[:20]:
        print("  fail:", f)
    sys.exit(0 if ok == tot else 1)


if __name__ == "__main__":
    main()
