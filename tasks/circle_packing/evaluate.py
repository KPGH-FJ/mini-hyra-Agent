#!/usr/bin/env python3
"""Evaluator for circle_packing.
Usage: python3 evaluate.py <solution_dir>
Reads solution.json {"positions": [[x,y]...]} (10 centers), verifies
non-overlap (pairwise >= 1 - eps) and bounds, score = -bounding side.
Anti-hacking: constraints are recomputed; declared metadata ignored."""
import json
import math
import sys

N = 10
EPS = 1e-6


def main() -> int:
    try:
        d = json.loads(open(f"{sys.argv[1]}/solution.json").read())
        pts = [(float(x), float(y)) for x, y in d["positions"]]
    except Exception as e:
        print(json.dumps({"score": -1e9,
                          "feedback": f"invalid solution.json: {e}"}))
        return 0
    if len(pts) != N:
        print(json.dumps({"score": -1e9,
                          "feedback": f"need {N} centers, got {len(pts)}"}))
        return 0
    mind = min(math.dist(pts[i], pts[j])
               for i in range(N) for j in range(i + 1, N))
    if mind < 1.0 - EPS:
        print(json.dumps({"score": -1e9,
                          "feedback": f"overlap: min distance {mind:.6f}"}))
        return 0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    side = max(max(xs) - min(xs), max(ys) - min(ys)) + 1.0  # +diameter
    print(json.dumps({"score": -side,
                      "feedback": f"side={side:.6f} mind={mind:.4f}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
