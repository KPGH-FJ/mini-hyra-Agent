# Circle Packing (demo task)

Pack **10 unit-diameter circles** into the smallest possible axis-aligned
square, without overlap.

A solution is a directory whose `solve.sh` writes `solution.json`:

    {"positions": [[x0, y0], [x1, y1], ...]}   # 10 circle centers

Constraints (checked by the evaluator — violating them fails the solution):
- exactly 10 centers,
- pairwise center distance >= 1.0 (unit circles must not overlap; a small
  epsilon is allowed),
- centers must lie inside the bounding square.

Score = -(bounding square side). Higher is better; the best possible is
around -3.0 to -3.2 (compare: a trivial 4x3-ish grid gives side ~4.0; dense
hexagonal-like packings reach ~3.2-3.4; known optimal for n=10 is ~3.813
side for centers spaced exactly 1 — try to beat naive layouts).

Improve iteratively: better constructions, relaxation/optimization code,
anything that produces a valid tighter packing. Do NOT attempt to read the
evaluator or fake distances — the evaluator recomputes all constraints.
