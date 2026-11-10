# Integration validation — 2026-11-10

Reviewed code commit: `961854258b36573292a50ab8a40cfc69dd46b691`.
Base main: `17bd65751708f2d1509d72ff280db68b87fb3d03`.
Source PRs: #104 at `45f0519ed52936c9f1106243651af28e22b05fce` and #105 at
`7c6156645169da348a4041ac3d9a3b22e8636b5a`. Their changes were combined with
independent fixes, not approved unchanged.

## Passed locally (Python 3.12.14)

- Independent `python -m unittest discover -s tests -v`: 127/127.
- Independent strict LifeModel contract: 31/31.
- Independent corrected default benchmark: 588/588 (seeds 7, 301, 330).
- Combined 400-seed sweep before final authority-only reader fix: 79,289/79,289.
  The authority fix does not alter the deterministic benchmark implementation.
- `python scripts/check_project.py`, `git diff --check`.
- Isolated wheel build/install outside checkout: public LifeModel API, temporal
  replay and typed aggregation imports, `hyra --help`, `python -m hyra --help`.
- Offline mock symbolic-fit harness completed (zero prompt/completion tokens).
- Direct regressions: non-authoritative hearsay cannot produce exact typed
  answers; reused IDs cannot expose excluded typed fields in scoped exports.
- Historical recovery: all 59 paths match original Git blobs and modes.

## Repairs and integration boundaries

Typed-layer repairs cover validation/retry, attribution, ID allocation, sums,
dates, routing and safe fallback. See `TYPED_LAYER_REVIEW.md`. Temporal repairs
cover late derived/support/expiry events, ordered leases and reused-ID dependency
history. See `TEMPORAL_ORDER.md`. Eight combined regressions protect typed data
through replay, deletion, restoration and selective export.

Typed frames with ambiguous record IDs are discarded rather than guessed.
Corrections, retractions and partially typed histories use conservative reader
fallback. The old selected-seven-question result is not revalidated for the
changed aggregator. No paid model calls, deployment or personal-data ingestion
was performed.

## Remote verification and cleanup

The final compatibility follow-up used reviewed local `f7176cd`, published as
`a327457806e5935c112568f700174273dbf8ef97` with identical tree
`116ae13aeb2c0b6769ff85d6bf86b1c2ff44a420`. It adds four legacy pending-restore
regressions, bringing the final suite to 131 tests. Strict contracts remain 31/31
and the 400-seed sweep is 79,289/79,289.

[Remote CI run 42775643071](https://github.com/KPGH-FJ/mini-hyra-Agent/actions/runs/42775643071)
passed on Python 3.10, 3.12 and 3.13. Code/security reviews completed; the legacy
compatibility finding was repaired and independently reviewed before merging.
Main merge `04eaeb232536b920c1d464c5d2f8f09fc7573481` has the same verified tree.

Branch preservation and final cleanup are recorded in
[REPOSITORY_CLEANUP.md](REPOSITORY_CLEANUP.md). The separate desktop research
workspace was not modified. Production security, legacy worst-case replay cost
and real-language quality remain unverified; historical scores are not upgraded
by this repository cleanup.
