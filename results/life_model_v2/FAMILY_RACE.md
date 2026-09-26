# M2 family race — hand-implemented lit-survey baselines vs evolved champion

Date: 2026-09-24. Context: P3 r1 evolution produced n=1 scored solution
(72 proposals killed by the Atria 502 wave across 3 windows). To break the
n=1 deadlock, two surveyed representation families were hand-implemented
as permanent evaluator baselines (`EventSourcedBaseline`, `GraphBaseline`
in `tasks/life_model/evaluate.py`) and driven through the same LifeStream
v2 lifecycle (seed 7, 97 probes, forget@55).

## Tournament table

| impl | family | score | quality | asset KB | probe KB | how |
|---|---|---|---|---|---|---|
| es      | event-sourced aggregates      | **96.9956** | 97.0 | 1.68 |  5.01 | measured |
| graph   | subject claims graph          | **96.9956** | 97.0 | 1.68 |  5.01 | measured |
| s0001   | bitemporal ledger + slot hist | 95.9952 | 96.0 | 1.34 | 10.40 | measured |
| raw     | keep-all                      | 94.3057 | 94.5 | 9.53 | 876.25 | reported |
| seed    | naive full replay             | 88.8630 | 97.0 | 9.53 | 40589.70 | reported |
| rag     | keyword retrieval             | 76.8862 | 77.0 | 9.53 | 473.63 | reported |
| ledger  | LWW flat map                  | 73.9909 | 74.0 | 0.37 | 41.88 | reported |

## Per-probe-type breakdown (es & graph)

All eight probe types at 1.0 — state, stale, prov, subject, as_of,
cascade, retract, **transfer**. s0001 loses only `transfer` (0.0): it
treats the `_bundle` probe slot as a literal slot and emits nothing; the
two baselines emit every live self-claim value (same as seed).

## Verdict

1. **The winning representation is "per-(source, slot) temporal
   history"** — the family the three surveys converged on. Event-sourced
   aggregates, claims-graph edges, and bitemporal slot-history are the
   same idea in different clothes: group the record stream by
   (subject, slot), keep validity information, answer by lookup instead
   of replay. All three land at quality ceiling 97/97.
2. **Quality is saturated; M2 is now a cost game.** 4 different impls hit
   97/97. Remaining headroom: asset ~1.3 KB → score ceiling ≈ 96.999.
   s0001's asset is already smallest (1.34 KB) but its probe cost (10.4 KB)
   and transfer bug leave it behind the hand baselines (5.0 KB).
3. **The evolved champion is now #3.** Its single loss is a `_bundle`
   handling bug, not a family weakness — fixable, and it remains the
   leanest store. P3 r2 targets: (a) transfer-aware answers, (b) probe
   cost < 5 KB, (c) asset compression below 1 KB.
4. Baselines updated: every future eval now reports `es` and `graph`
   alongside raw/ledger/rag in the feedback digest — the evolved bar is
   96.9956, not 94.5.

## Reproduce

```bash
python3 tasks/life_model/evaluate.py tasks/life_model/seed_solution
# baselines digest inside feedback now includes es=96.9956 graph=96.9956
```
