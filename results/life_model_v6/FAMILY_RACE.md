# P3 r4/r5 — cumulative frontier family race (LifeStream v6c)

Question: after M1 (ingest: alias + out-of-order) and M5 (control:
revoke / range-forget / ops-audit) pressures joined the bench, which
implementation families still answer the whole lifecycle?

## Frontier (seed 7, 136 probes)

| impl | score | quality | probe cost | what it survives |
|---|---|---|---|---|
| lifemodel v1 | 135.97 | 136/136 | 6 KB | everything — 100% quality on every probed seed (3/7/11/42) |
| tms baseline | 135.97 | 136/136 | 3 KB | everything |
| esr baseline | 135.42 | 136/136 | 2.7 MB | everything, pays replay-per-probe (~0.55 pt) |
| raw | 98.58 | 99.5 | 4.4 MB | loses ~36 to OOO + rollback + audit + serve |
| ledger (LWW) | 84.49 | 84.5 | 59 KB | same losses, worse: arrival-order truth |
| rag | 52.81 | 53.0 | 675 KB | keyword retrieval, no semantics |
| flat | 43.99 | 44.0 | 26 KB | whole-dump serve, no views/metering |

raw/ledger loss anatomy (seed 7): both lose the entire serve surface
(purpose 0/8, budget 0/2, prov2 0/4, ops 0/3, revoked 0/1, transfer
0/1 ≈ 18 pts) plus ~12 to OOO/rollback state-stale misses; ledger
additionally loses every subject probe (0/11 — no hearsay vertices)
and 7.5/8 as_of. raw even leaks a retracted value (retract −0.5).

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
| ops audit (v6c) | ops ×3 (forget/correct/revoke_purpose) | no op journal | ~3 |

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

## Scale-stress experiment (density axis, v6c semantics)

`generate(seed, density=N)` multiplies record volume (~201→881 at
×5) inside the same 90-day semantics. Result (seed 7):

| density | n_records | impl | quality | probe_bytes | score |
|---|---|---|---|---|---|
| ×1 | 201 | tms | 136 | 3 KB | 135.97 |
| ×1 | 201 | esr | 136 | 2.6 MB | 135.42 |
| ×3 | 541 | tms | 137 | 3 KB | 136.92 |
| ×3 | 541 | esr | 138 | 7.4 MB | 136.38 |
| ×5 | 881 | tms | 137 | 5 KB | 136.88 |
| ×5 | 881 | esr | 138 | 11.8 MB | 135.41 |

Two findings: (a) vertex-lookup impls (tms/lifemodel) keep probe cost
flat under volume — the architectural claim holds; (b) **the cost
weight is calibrated too weakly to select for efficiency** — replay
readers pay linear probe cost (2.6→11.8 MB) yet lose only ~0.1-2.6
pts of ~138. The natural fix is not a bigger coefficient but more
probes: a real user asks thousands of questions, and at ~1400 probes
the same mechanism would cost ~26 pts. A probe-storm variant is the
right next pressure, not weight hacking.

## Open frontier

- M1 ingest round (lab run_v5) in flight — first evolved-solution
  sample on the cumulative bench.
- **Probe-storm variant** (supersedes the cost-weight question): the
  scale-stress table above shows linear-cost readers lose only ~2.6
  pts even at 5× volume — efficiency selects only when probe COUNT
  grows, so multiply probes (more checkpoints per slot, per-slot
  purpose queries) rather than the coefficient.
- v7 candidates: partial export (export only a purpose's view),
  conflict probes (same-day contradictory sources), audit depth
  (ops with day/scope), probe-storm (see scale-stress finding).
- RESOLVED: NL query surface (lifemodel/query.py) verified end-to-end
  on seed 7 — state/as_of/subject(alias)/prov2/purpose/abstain all
  route and answer correctly through the typed-probe contract.
