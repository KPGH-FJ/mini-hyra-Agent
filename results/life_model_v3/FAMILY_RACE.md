# P3 r2 — M3 Update family race

Question: which update mechanism keeps an asset correct when records
contradict, revise, retract, expire, and spawn derived facts?

## Families raced (hand-built from the M3 survey, docs/literature/m3_update.md)

| family | impl | idea |
|---|---|---|
| TMS premise maintenance | `TMSBaseline` | derived facts register premises resolved from `supports=[rec_id]`; every mutation ends in a fixpoint sweep killing dependents (transitive) |
| Event-sourced replay | `ESRBaseline` | raw log only; every answer replays the stream and recomputes live state incl. derived validity |
| control group | `raw`/`ledger`/`rag` (existing) | no premise tracking |

## Scores (22 seeds, LifeStream v3: 107–113 probes/seed)

| impl | avg score | quality | cost profile |
|---|---|---|---|
| **lifemodel v1 (TMS fold)** | **110.53** | full every seed | ~3.5 KB asset, ~4 KB probe |
| TMSBaseline | 110.54 | full every seed | ~3.8 KB asset, ~2 KB probe |
| ESRBaseline | 110.41 | full every seed | ~6.2 KB asset, **~650 KB probe** |
| raw/ledger/rag | 80–105 | misses derive/cascade | — |

Quality **saturates at 100%** for every correct implementation on every
seed — like M2, once the mechanism is right the race is cost-only.
TMS wins the family race: identical quality to event-sourced replay at
~320× cheaper probe reads (premise index vs full replay per probe).

## What the bench caught while building the baselines

- **Generator bug (fixed)**: `truth_events` replayed in construction
  order, not day order — the expiring declaration could overwrite a
  newer update. Day-sorted.
- **Generator bug (fixed)**: a derived's `supports` could point at a
  future change record whose value ≠ the premised live value — honest
  impls killed the derived at birth. Supports now name the record that
  actually carries the premised value.
- **Semantics pinned down**: expiry is a *slot-scoped lease evaluated at
  read day* — once declared, the whole slot lapses at expires_day;
  later writes without expiry do not renew it. Implementations doing
  edge-scoped or ingest-time expiry failed real probes (seeds 3/8/9).
- **Selection gradient verified**: flat derived tracking leaks dead
  premises (−0.5/probe); assets ignoring derived lose ~3 live probes;
  only supports-wired impls clear both.

## Round verdict

**Winner: TMS-style premise maintenance**, folded into `lifemodel/`
(store `drv`/`rsv` registries + `_prune` fixpoint on every mutation;
`live()` falls back to derived values; snapshot round-trips them).
lifemodel v1 now scores 112/112 on v3 seed-7 (was 109 — the fold closed
the live-derived gap) and max quality on all 22 sampled seeds.

Next open module: **M4 Serve** (context budget, abstention, per-use views).
