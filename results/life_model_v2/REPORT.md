# P3 round 1 — M2 representation evolution results

**Run:** `hyra run --task tasks/life_model --work run_v2 --solutions 100 --workers 4 --wall-clock 14400`
**Evaluator:** LifeStream v2 (97 probes; seed 7) — `score = quality − 0.002·KB(asset) − 0.0002·KB(probe) − 0.0002·tokens`
**Window:** 2026-09-23 15:38 → 20:12 UTC (wall-clock cap hit at ~19:38; ~34 min of retry-drain before exit)
**LLM:** Atria-Dawn-Preview via api.atria-asi.ai

## Headline

| solution | direction | score | quality | cost_how | asset_bytes | probe_bytes |
|---|---|---|---|---|---|---|
| **s0001 (winner)** | explore | **95.9952** | 96.00 | **measured** | 1,370 | 10,650 |
| s0000 (seed) | seed | 88.863 | 97.00 | reported | 9,762 | 41,563,849 |
| baselines (same stream) | — | raw 94.5 / ledger 74.0 / rag 77.0 | | | | |

**Best honest score: 95.9952, cost_how = `measured`.** Re-evaluated locally after
the run (`hyra eval`) — deterministic, reproduces exactly.

The winner trades **−1.0 quality** (loses `transfer`) for **−8.1 cost** vs the
seed: probe_bytes 41.5 MB → 10.65 KB (−8.31 pts), asset_bytes 9.8 KB → 1.37 KB
(−0.02 pts). Net **+7.13**. It beats every baseline including `raw` (94.5),
which costs more for lower quality.

## Honesty audit (cost_how)

- **suspicious entries: 0.** Every entry in the EB was checked: 2 scored +
  23 error commits. No solution claimed near-zero cost while answering
  non-trivially; no `stats()` hardcoding observed in the winner (metering is
  real — `probe_bytes()` accumulates `len(json.dumps(consulted))` per probe).
- Winner is `measured` (evaluator serialized `state()`/`probe_bytes()` itself).
- Seed is `reported` — honest but self-declared via `stats()` fallback
  (it predates the measured-cost convention; its numbers match v1 anyway).

## Quality breakdown by probe type (97 probes)

| type | s0000 (seed) | s0001 (winner) | v1/v2 |
|---|---|---|---|
| state   | 1.0 | 1.0 | v1 |
| stale   | 1.0 | 1.0 | v1 |
| prov    | 1.0 | 1.0 | v1 |
| retract | 1.0 | 1.0 | v1 |
| transfer| 1.0 | **0.0** | v1 |
| **as_of**   | 1.0 | 1.0 | **v2 new** |
| **subject** | 1.0 | 1.0 | **v2 new** |
| **cascade** | 1.0 | 1.0 | **v2 new** |

Both scored solutions handle all three new v2 probe families perfectly —
bitemporal history reconstruction (`as_of`), hearsay attribution
(`subject`), and `forget()` propagation into state AND history (`cascade`).
The **only** quality delta anywhere in the round is `transfer` on s0001: its
`_live_values` collects per-slot live values, but transfer probes want a
multi-value constraint bundle (e.g. week-planning) — the emitted
comma-joined answer missed the expected set. Worth fixing next round; it
is the sole known quality leak.

## Representation family of the winner

**Bitemporal ledger + per-slot history index** (survey taxonomy ≈ D 双时态表
with B 槽位账本 discipline; the hearsay side-channel is the surveyed
"subject-indexed hearsay store" applied orthogonally).

`s0001/asset.py` keeps, per slot, a sorted list of
`[value, valid_from, valid_to, known_since, expires_day, src, kind]`:

- **as_of** = interval-covering lookup over ONE slot's entries bounded by
  `known_since` — no stream replay (this is where the 41.5 MB → 10.65 KB
  probe_bytes collapse comes from).
- **retraction** = tombstone in `_RET` + closes open intervals; `retract`
  probes answer "已删除/未知".
- **hearsay** → `_HEAR` (day, slot, value, text, person), never touches
  self-state; subject probes match person (+ slot prefix / text fallback).
- **suggestion** → `_SUG`, never state; used only as transfer fallback.
- **forget(slot)** physically erases the slot from `_H`, `_RET`, `_SUG`,
  `_HEAR` — cascade-clean (this is what passes `cascade`).
- **state()** serializes the whole compact structure → 1.37 KB measured asset.

Why it won: the quality ceiling on this seed is ~97 and the seed already hits
it, so the gradient was almost entirely **cost**. Bitemporal intervals answer
temporal probes exactly while consulting only the touched slot's entry list —
the same answer the seed's full-replay produces, at ~3900× lower probe cost.
This is the literature's predicted shape (event-sourcing correctness without
event-sourcing query cost) — honest +0.002-per-KB scoring did the rest.

## Search dynamics / error rate (Atria 502 losses)

**The round was severely degraded by the upstream endpoint.** Of the 100
solution budget, 25 commits happened; 23 of them are proposal errors, all
`llm failed after 8 retries: HTTP Error 502: Bad Gateway`.

| metric | value |
|---|---|
| commits in EB | 25 |
| scored | 2 (seed + s0001) |
| dead on LLM failure | 23 (all 502 retry-exhaustion) |
| failed LLM attempts | 183 × HTTP 502, 1 × read timeout, 1 × empty completion (context agent) |
| successful LLM calls | 16 (28,987 prompt + 32,128 completion tokens) |
| attempt failure rate | ~92% |
| truncations | 1 (context agent; retried at 32k max_tokens, returned non-JSON) |

The 502 wave was near-continuous for the whole 4 h; a small probe curl to the
same endpoint succeeded mid-wave (17:55), so the outage looks
windowed/request-size-sensitive rather than a hard down — large
context-agent / proposal prompts landed in bad windows almost every time.
Failed proposals are still committed as error entries and consume budget, so
the wave burned ~23% of the 100-solution budget directly (the rest of the
budget was starved: wall-clock, not budget, ended the loop).

Direction histogram of dead proposals shows the context agent converged on
exploit-after-first-win early (17× exploit, 3× explore, 2× hybrid, 1×
repair, 1× fresh across all proposals) — i.e. the search had already
committed to refining the bitemporal winner when it starved.

## Next round (P3 r2) recommendations

1. **Re-run this exact task when Atria is healthy** — with n=1 scored this is
   a lower bound, not a verdict; `scan_new_commits`-style resumption with the
   same `--work run_v2` EB will continue the search rather than restart it.
2. **Target `transfer`** — the only lost probe type. The gap: bundle probes
   expect a set of values spanning slots/days; s0001 only emits one slot's
   live values (+suggestion fallback). A cross-slot live-set or a
   bundle-aware index should recover ~1.0 quality.
3. **Untested families this round** (never instantiated — proposals died):
   episode+fact two-layer, event-sourced projection, graph/hybrid. If quality
   is already saturated at ~97, they can only differentiate on cost; if
   r2 raises difficulty (longer streams, more conflicting writes), revisit
   them for quality.
4. **Endpoint resilience**: consider `--llm-concurrency 1` during 502 waves to
   avoid correlated 4-way retry storms, or a retry policy that doesn't count
   exhausted proposals against `--solutions` — 23/25 commits were 8×502
   corpses, not real samples.

## Provenance

- Winning dir: `run_v2/eb/solutions/s0001` (direction=explore, parent=s0000,
  eval_version=0), copied here verbatim — `asset.py`, `solution.json`,
  `meta.json`, `solve.sh`, `proposal.txt`, `run.log`.
- Full EB + harness log: `run_v2/` on the lab machine (not committed).
- Dashboard served throughout at `hyra serve --work run_v2 --port 8000`.
