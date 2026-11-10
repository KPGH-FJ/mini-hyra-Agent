# Typed-record layer: reviewed integration boundary

PR #104's original saved lab chain (5/5 oracle, 2/7 extraction, 4/7 canonical
frames, 7/7 spec verification) is historical evidence for those scripts and
samples, not a production guarantee. The repaired evaluator deliberately changes
selection and incomplete-sum semantics. No new paid/model experiments were run,
and the historical 7/7 is not asserted for this revised implementation.

## Supported opt-in path

`LLMIngestor(..., typed=True)` adds a canonical-frame pass. Every required field
must be present with an appropriate type before a frame is accepted. Missing or
malformed responses receive one focused retry; remaining failures stay untyped.
New ingestor instances generate independently namespaced record IDs. This avoids
restart collisions without changing externally provided IDs.

`aanswer(..., agg="spec")` tries deterministic aggregation before the profile
route for eligible first-person enumeration/duration questions. It uses only
authoritative self-attributed statements. Self-sourced hearsay, suggestions,
derived records and unknown kinds cannot enter the typed pool, regardless of
the frame polarity assigned by the typing model. Current-state phrasing, partially typed histories and
histories containing updates, corrections or retractions fall back to the normal
reader. This is a conservative boundary, **not** an implementation of typed
current-state/correction semantics. Unrecognized question phrasing and ambiguous
natural-language intent remain research limitations; this route is experimental
and off by default.

The evaluator preserves explicit selectors, applies common predicates to
`any_of` alternatives, matches counterparties exactly after normalization, filters
duplicate members before choosing evidence, and prevents transitive duplicate
groups with conflicting dates. Missing summands and conflicting duplicate-group
values return unknown rather than an exact-looking total. Distinct counts omit
null objects. Invalid generated DSL shapes fall back instead of raising.

Relative dates are not resolved semantically: explicit `mention_day` or `tolerant`
window modes apply their documented approximations to unresolved relative anchors;
`strict` excludes them. Those modes must not be described as exact event dating.

The verification prompt includes vocabulary and rejected candidates as well as
selected evidence, so the stateless verifier can inspect underselection. Model
outputs remain fallible and these guards do not establish a security sandbox.

## Offline verification

On the PR #104 head plus these repairs:

- `python -m unittest discover -s tests -v`: 24 regression tests passed.
- `python tests/test_lifemodel_contract.py lm`: 31/31 passed.
- `python tests/test_bench_sweep.py`: 582/582 across seeds 7, 301, 330.
- `python -m compileall -q lifemodel` and `git diff --check`: passed.

These are the **old oracle** denominators on #104, before integration with #105.
The integrated branch must rerun the full suite against the corrected oracle.
Every registry purge added by #105 must also purge `typed`; typed snapshot/export
and erasure tests must be rerun after resolving store conflicts. No remote push,
merge, model call or paid experiment was performed during this local review.
