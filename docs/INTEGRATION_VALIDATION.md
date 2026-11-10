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

## Remote verification and remaining work

The offline CI definition covers Python 3.10, 3.12 and 3.13. Local checks do not
claim those remote jobs have passed; inspect the integration PR's exact head.
The Git Data publication may have a different commit SHA because commit metadata
is regenerated; its entire tree must match the reviewed local tree before merge.

All 102 original non-main branches are retained pending history/activity review.
No `ours` history merge or branch deletion was performed. The separate desktop
research workspace is outside this repository cleanup. Production security,
legacy worst-case replay cost and real-language quality remain unverified.
