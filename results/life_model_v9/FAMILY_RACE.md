# LifeStream v9 — history reasoning + derived revival

Bench v9 (commit 9fbffab): ~199 probes/seed, 28 types. Six new
history-reasoning families (`first`/`order`/`join`/`absent`/`window`/
`xcmp`) test *run-relative* temporal recall — earliest write of the
current run, ordered surviving run values, cross-slot joins at a
transition day, post-day-40 stability, in-window transitions, and
entity-vs-self same-slot comparison. All probe answers derive from
one edge-walk over `self|slot` history — the representation's
temporal spine doing the work.

## The derived-revival discovery (the deep find this round)

Bug chain found while re-verifying 8 residual fails on the 40-seed
sweep (seeds 194/224): `elder_plan` alive in truth, dead in the model.

- Derived `elder_plan` registers fine at feed (premise r0006 resolves).
- Mid-feed, `exercise` updates → `_prune` kills it permanently.
- `forget_range@[28,29]` then erases **the killer write itself**.
- Truth replays the *rewritten* log: SKIP drops the update → premise
  holds again → derived is **alive** at read day 90.
- Model's registry had no way back — the entry was deleted, not just
  marked dead.

**Rule pinned (contract clause 13):** an erasure rewrites the record
log, so derived state must be *rebuilt from the log*, not merely
re-pruned. Implementation: `_drv_log` keeps every derived event; every
erase op replays surviving events in (day,arrival) order against the
post-erasure rsv/live state — events whose own edge died stay dead,
premises that came back revive the derived. Same semantics the
evaluator scores, mirrored inside the store.

Two companion truth-side fixes (evaluator-as-system-under-test):
- `derive`/`cascade` expectations must follow `state_at(ckpt,
  read_day)` — a hardcoded "已删除" is wrong whenever the killer sits
  in the SKIP window.
- `must_not` stale decoys must exclude values live at read day (a
  decoy equal to the live value punishes the correct answer −0.5).

## Verification

- 20-seed sweep: **3941/3941 probes clean** (was 8 fails before the
  three fixes).
- Contract suite 30 clauses: lm **30/30**; esr passes revival clauses
  for free (replay semantics), tms fails them (registry without
  rebuild) — matches the bench gap honestly.

## Frontier (seed 7, v9)

| impl | quality | gap vs lm |
|---|---|---|
| lifemodel v1 | **195/195** | — |
| esr | 182 | −13 (entity/alias + isconf + v9 history) |
| tms | 181 | −14 (same + revival rebuild) |
| raw | 107.5 | — |
| ledger | 87 | — |
| rag | 66 | — |
| flat | 58.5 | — |

Best evolved (v8g): s0040 = 147.90 — still ~47 under the frontier;
the gap lives in serve surface + v9 history handlers the labs are
now chasing (run_v5 W3, run_v7 M4 serve round in flight).

## Residual gap breakdown (seed 7, per probe type)

esr 182 / tms 181 — losses concentrate in the v9 history family,
which is exactly where their record models have no semantics:

| type | tms | esr | why |
|---|---|---|---|
| first | 1.0/2 | 1.0/2 | earliest-of-run reads need run detection |
| order | 0/1 | 0/1 | transition lists need compressed history |
| absent | 0/2 | 0/2 | "never said X" needs absence proofs |
| window | 0/2 | 0/2 | interval transition counts |
| xcmp | 0/1 | 0/1 | cross-entity same-slot compare |
| isconf | 0/3 | 0/3 | conflict detection needs claim-vs-claim |
| subject/conf/prov2/ops | ~4 small | ~3 small | alias/ops-journal edges |

lm covers all of these from the same `hist` edges — the handlers
are thin lenses over one structure; the baselines lose because the
structure itself lacks the history surface, not because of scoring
quirks.
