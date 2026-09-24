# P3 round 1 — M2 representation evolution results

**Runs (four windows, same `run_v2` EB):**
- W1: `hyra run --task tasks/life_model --work run_v2 --solutions 100 --workers 4 --wall-clock 14400` — 2026-09-23 15:38 → 20:12 UTC
- W2 (resumed, EB preserved): same command — 2026-09-23 20:17 → 2026-09-24 00:50 UTC
- W3 (resumed, EB preserved): same command — 2026-09-24 00:59 → 05:48 UTC
- W4 (resumed, EB preserved): same command — 2026-09-24 07:59 → 12:35 UTC
  (gated on a proposal-sized health probe succeeding first; evaluator
  working tree carried the new es/graph baselines from
  `research/m2-family-race` — see Provenance)

**Evaluator:** LifeStream v2 (97 probes; seed 7) — `score = quality − 0.002·KB(asset) − 0.0002·KB(probe) − 0.0002·tokens`
**LLM:** Atria-Dawn-Preview via api.atria-asi.ai

## Headline

| solution | direction | score | quality | cost_how | asset_bytes | probe_bytes |
|---|---|---|---|---|---|---|
| **s0001 (winner)** | explore | **95.9952** | 96.00 | **measured** | 1,370 | 10,650 |
| s0000 (seed) | seed | 88.863 | 97.00 | reported | 9,762 | 41,563,849 |
| old baselines (same stream) | — | raw 94.5 / ledger 74.0 / rag 77.0 | | | | |
| **new baselines (added mid-round)** | — | **es 96.9956 / graph 96.9956** | | | | |

**Best honest evolved score: 95.9952, cost_how = `measured`.** Re-evaluated
locally after the run (`hyra eval`) — deterministic, reproduces exactly.

The winner trades **−1.0 quality** (loses `transfer`) for **−8.1 cost** vs the
seed: probe_bytes 41.5 MB → 10.65 KB (−8.31 pts), asset_bytes 9.8 KB → 1.37 KB
(−0.02 pts). Net **+7.13**. It beats all three original baselines but sits
**below the two new permanent baselines** (es / graph, 96.9956 — same
per-(source,slot)-history family, quality 97.0 incl. transfer, probe 5.01 KB,
asset 1.68 KB — see FAMILY_RACE.md on `research/m2-family-race`, PR #9).

## Honesty audit (cost_how)

- **suspicious entries: 0.** Every entry in the EB was checked: 2 scored +
  96 error commits (all four windows). No solution claimed near-zero cost while answering
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

## Search dynamics / error rate (Atria 502 losses) — cumulative four windows

**The round was severely degraded by the upstream endpoint in ALL FOUR
windows.** Combined: 98 commits in the EB; 96 of them are proposal errors,
all `llm failed after 8 retries: HTTP Error 502/503`.

| metric | W1 | W2 | W3 | W4 | total |
|---|---|---|---|---|---|
| commits | 25 | 24 | 25 | 24 | 98 |
| scored | 2 | **0** | **0** | **0** | 2 |
| dead on LLM failure | 23 | 24 | 25 | 24 | 96 |
| failed LLM attempts | 183×502, 1 timeout, 1 empty | 191×502, 8 non-JSON replies | 190×502, 4×503, 10 non-JSON, 41×401† | 192×502, 7 non-JSON replies | ~940 failed |
| successful LLM calls | 16 | ~a few | 13 (24.0k/15.5k tok) | 8 (14.9k/7.5k tok) | ~40 |

† W3's 41×401 were a **lab-side launch bug**, not Atria auth failures: the
first W3 invocation passed `$ATRIA_API_KEY` unexpanded as the literal key
value. Caught and relaunched with correct env within ~8 min; no commits
were produced in that interval (0 budget lost to it). All genuine upstream
failures in W3 were 502/503 gateway errors, same as W1/W2/W4.

The wave ran essentially uninterrupted for **~21 h** across all four
windows (W1 start 15:38 → W4 end 12:35 UTC). Failure modes: fast 502
bursts (W1–W3) alternating with hang-until-timeout periods (gate probes
#1–#3 all died at 180 s). Small probe curls succeeded mid-wave several
times; W4 was launched through a 20-min **proposal-sized gate** (≥4 KB
prompt, 8192 max_tokens, 180 s timeout) that passed at 07:59 with a real
200 + 2,371 generated tokens — the wave resumed ~20 min later and killed
every proposal anyway. W4's 8 successful API calls (mostly the launch-gap)
never completed a full context→proposal→eval pipeline.

**Operational lesson (confirmed twice now):** even a proposal-sized 200 is
only a *gap* indicator, not health — W3 launched after a verified small 200,
W4 launched after a verified large 200, and both lost 100% of commits.
Realistic next step: require N consecutive gated probes (e.g. 3 successes
over ~1 h) before spending a window.

Failed proposals are still committed as error entries and consume the
`--solutions` budget, so the wave burned ~96 of 400 total proposal slots
directly (all four windows ended on wall-clock, not budget).

Direction histogram across all 96 proposals (seed excluded):
exploit 77, explore 7, hybrid 7, fresh 4, repair 1 — the context agent
converged on exploit-after-first-win in W1 and hardened further (W4 was
24/24 exploit); the search had committed to refining the bitemporal winner
when it starved.

## Amendment — windows 2, 3 & 4 outcome (updated 2026-09-24)

Resuming the same EB for THREE additional 4h windows produced **zero new
scored solutions** in each: all 24 W2, 25 W3, and 24 W4 commits died on
retry-exhaustion. W4 additionally ran against the updated evaluator
carrying the two new permanent baselines (see Provenance). The evolved-side
picture does not change — but the family-race context did:

- **Best evolved score remains s0001 = 95.9952, cost_how = measured** —
  still no new evolved challenger, and now **1.0 pt below the new
  permanent baselines** es/graph at 96.9956.
- **Per-family rates across ALL scored solutions** — still n=1 evolved,
  plus the two hand-implemented reference impls (FAMILY_RACE.md):
  | family | scored instances | best score | verdict |
  |---|---|---|---|
  | per-(source,slot) temporal history — es impl | 1 (baseline) | 96.9956 | reference bar |
  | per-(source,slot) temporal history — graph impl | 1 (baseline) | 96.9956 | reference bar |
  | same family — bitemporal ledger + slot hist | 1 (s0001) | 95.9952 | only evolved sample |
  | event-log replay (seed) | 1 (s0000) | 88.863 | baseline reference |
  | episode+fact / subject-hearsay / other | 0 | — | **never instantiated** — 96 proposals died before producing code |
  All three scored members of the winning idea (es, graph, s0001) are the
  same family in different clothes: group the stream by (subject, slot),
  keep validity, answer by lookup not replay — quality ceiling 97 on all
  three; the deltas are implementation details, not family.
- **Probe-type breakdown** unchanged: both scored evolved solutions at 1.0
  on all new v2 types (as_of / subject / cascade); sole loss remains
  `transfer` on s0001 (0.0) — FAMILY_RACE.md confirms it's an impl bug
  (bundle slot treated literally), not a family weakness: es/graph emit
  every live self-claim value and score transfer 1.0.
- **Honesty audit** unchanged: 0 suspicious entries across all 98 commits;
  every error entry is an explicit retry exhaustion, not a scoring anomaly.

Conclusion: on the evolved side the race is **still open at n=1** (16 h
wall-clock, 96 dead proposals). But the representation question itself
looks answered: three independent impls of per-(source,slot) temporal
history saturate quality at 97 — s0001's remaining gap to es/graph is
engineering (transfer bug + 10.4 KB probe vs 5.0 KB), fixable in r2.

## Next round (P3 r2) recommendations

1. **r2 targets (per parent): fix `transfer`, probe <5 KB, asset <1 KB.**
   s0001's gaps vs the es/graph bar are precisely known: emit every live
   self-claim value for `_bundle` probes (recovers the 1.0 transfer loss),
   and get probe cost from 10.4 KB toward 5.0 KB; asset is already best
   (1.34 KB) but <1 KB is the stated r2 bound.
2. **Re-run evolution only when Atria is durably healthy** — four full
   windows all returned n=1 scored (96 corpses between them). A single
   gated 200 (small OR proposal-sized) was proven meaningless twice; gate
   on several consecutive proposal-sized successes over ~1 h. Resuming
   with the same `--work run_v2` EB continues the search.
3. **Untested evolved families** (never instantiated — proposals died):
   episode+fact two-layer, subject-hearsay standalone. With quality
   saturated at ~97 they can only differentiate on cost; if r2 raises
   difficulty (longer streams, more conflicting writes), revisit them for
   quality.
4. **Endpoint resilience**: consider `--llm-concurrency 1` during 502 waves
   to avoid correlated 4-way retry storms, or a retry policy that doesn't
   count exhausted proposals against `--solutions` — 96/98 commits were
   8×502/503 corpses, not real samples.

## Provenance

- Winning dir: `run_v2/eb/solutions/s0001` (direction=explore, parent=s0000,
  eval_version=0), copied here verbatim — `asset.py`, `solution.json`,
  `meta.json`, `solve.sh`, `proposal.txt`, `run.log`.
- Full EB + harness log: `run_v2/` on the lab machine (not committed).
- W4 evaluator note: the es/graph baselines live on `research/m2-family-race`
  (PR #9), not yet on main at launch time — the lab applied that branch's
  `tasks/life_model/evaluate.py` to the working tree (uncommitted) so W4's
  `baselines=` digest included es/graph. Scoring rules unchanged; all other
  frozen files untouched.
- Dashboard served throughout at `hyra serve --work run_v2 --port 8000`.
