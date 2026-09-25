# P3 r4/r5 — cumulative frontier family race (LifeStream v6c)

Question: after M1 (ingest: alias + out-of-order) and M5 (control:
revoke / range-forget / ops-audit) pressures joined the bench, which
implementation families still answer the whole lifecycle?

## Frontier (seed 7, 135 probes)

| impl | score | quality | what it survives |
|---|---|---|---|
| lifemodel v1 | 134.97 | 135/135 | everything |
| tms baseline | 135.0 | 135/135 | everything (pricier reads) |
| esr baseline | 135.0 | 135/135 | everything (replays the log per probe) |
| raw | 99.5 | — | loses ~35 to OOO + rollback + audit |
| ledger (LWW) | 84.5 | — | same losses, worse: arrival-order truth |
| rag | 53.0 | — | keyword retrieval, no semantics |
| flat | 44.0 | — | whole-dump serve, no views/metering |

## What each pressure knocks out

| pressure (version) | probes | deficient family | honest loss |
|---|---|---|---|
| derived + premise invalidation (v3) | derive/cascade | flat stores without supports | ~4 |
| export/import round-trip (v3) | post_import flag | no state()/import_state | all flagged probes |
| serve pressure (v4) | unans/purpose/budget/prov2 | whole-dump serve, no abstention | up to ~75 (flat) |
| ambient density ×4 (v4) | — | replay-per-probe readers | cost only |
| alias + out-of-order (v5) | subject/state/prov2 | arrival-order impls (ledger/raw) | ~5–15 |
| purpose revocation (v6) | revoked | no consent registry | ~1 + leaks |
| range-forget rollback (v6b) | state+stale ×2ckpt, prov2 | cur-only materializers without history rebuild | ~5 |
| ops audit (v6c) | ops ×2 | no op journal | ~2 |

## Semantics pinned this wave

- `day` is authoritative, never arrival order — within a checkpoint
  window records may be displaced; `_wday`/`rvid` track max write day.
- alias records map name forms onto canonical persons at read time;
  hearsay under either form lands on the same subject vertex.
- `revoke_purpose(p)`: the DATA stays, the USE is refused — revoked set
  must round-trip export/import.
- `forget({day_gte, day_lte})`: erasing write edges rolls the slot back
  to its previous live value (NOT tombstone-hide). Implementations must
  rebuild materialized latest-write markers (_wday, rvid, prov, exp)
  from surviving edges — edges therefore carry their record id (5th
  element).
- the ops journal is part of the asset: it lives in state()/snapshot
  and survives export/import; audit probes read nothing else.

## Bench truth bugs caught by seed sweeps

- prov noise filter ignored the evaluator's correct() control write —
  a hearsay value matching the corrected value was probed expect=非本人
  while the truth was 本人 (seed 3). Excluded post-CORRECT_DAY.
- latest_rid iterated arrival order — under v5's OOO it could name a
  stale record. Now max-day + alive().

## Open frontier

- M1 ingest round (lab run_v5) in flight — first evolved-solution
  sample on the cumulative bench.
- v7 candidates: NL query surface via lifemodel/query.py (untested),
  partial export (export only a purpose's view), conflict probes
  (same-day contradictory sources), audit depth (ops with day/scope).
