#!/usr/bin/env python3
"""Evaluator for symbolic_fit. Usage: python3 evaluate.py <solution_dir>
Reads <solution_dir>/solution.json -> {a,b,c,d}, computes -RMSE against the
hidden reference on a held-out grid, prints JSON {"score", "feedback"}."""
import json
import math
import sys

TRUE = {"a": 2.3, "b": 1.7, "c": -0.4, "d": 1.0}


def f(x, p):
    return p["a"] * math.sin(p["b"] * x) + p["c"] * x + p["d"]


def main() -> int:
    sol_dir = sys.argv[1]
    try:
        p = json.loads(open(f"{sol_dir}/solution.json").read())
        for k in TRUE:
            if not isinstance(p.get(k), (int, float)):
                raise ValueError(f"missing numeric param {k}")
    except Exception as e:
        print(json.dumps({"score": -1e9,
                          "feedback": f"invalid solution.json: {e}"}))
        return 0
    xs = [i * 0.37 - 10 for i in range(541)]  # held-out grid
    rmse = math.sqrt(sum((f(x, p) - f(x, TRUE)) ** 2 for x in xs) / len(xs))
    print(json.dumps({"score": -rmse,
                      "feedback": f"rmse={rmse:.6f} params={p}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
