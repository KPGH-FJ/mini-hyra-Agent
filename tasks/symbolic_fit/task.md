# Symbolic Fit (demo task)

Fit the parameters of a parametric model to hidden data.

The model form is fixed:

    f(x) = a * sin(b * x) + c * x + d

A solution is a directory whose `solve.sh` writes `solution.json` containing a
JSON object with numeric keys `a`, `b`, `c`, `d`, e.g. via a `model.py` that
holds a `PARAMS` dict and prints it.

The evaluator scores the solution by RMSE against hidden reference data on a
held-out grid; `score = -RMSE` (higher is better; perfect fit = 0).

Improve iteratively: perturb, restructure, or refit parameters. Do NOT try to
read the evaluator's data file — solutions that touch `evaluate.py` or the
data are invalid.
