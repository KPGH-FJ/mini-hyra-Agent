# P3 round 1 — M2 representation evolution results

**Runs (three windows, same `run_v2` EB):**
- W1: `hyra run --task tasks/life_model --work run_v2 --solutions 100 --workers 4 --wall-clock 14400` — 2026-09-23 15:38 → 20:12 UTC
- W2 (resumed, EB preserved): same command — 2026-09-23 20:17 → 2026-09-24 00:50 UTC
- W3 (resumed, EB preserved): same command — 2026-09-24 00:59 → 05:48 UTC

**Evaluator:** LifeStream v2 (97 probes; seed 7) — `score = quality − 0.002·KB(asset) − 0.0002·KB(probe) − 0.0002·tokens`
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
  72 error commits (all three windows). No solution claimed near-zero cost while answering
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

## Search dynamics / error rate (Atria 502 losses) — cumulative three windows

**The round was severely degraded by the upstream endpoint in ALL THREE
windows.** Combined: 74 commits in the EB; 72 of them are proposal errors,
all `llm failed after 8 retries: HTTP Error 502/503`.

| metric | W1 | W2 | W3 | total |
|---|---|---|---|---|
| commits | 25 | 24 | 25 | 74 |
| scored | 2 | **0** | **0** | 2 |
| dead on LLM failure | 23 | 24 | 25 | 72 |
| failed LLM attempts | 183×502, 1 timeout, 1 empty | 191×502, 8 non-JSON/truncated context-agent replies | 190×502, 4×503, 10 non-JSON replies, 41×401† | ~750 failed |
| successful LLM calls | 16 | ~a few (mostly non-JSON responses) | 13 (24.0k prompt / 15.5k completion tokens) | ~35 |

† W3's 41×401 were a **lab-side launch bug**, not Atria auth failures: the
first W3 invocation passed `$ATRIA_API_KEY` unexpanded as the literal key
value. Caught and relaunched with correct env within ~8 min; no commits
were produced in that interval (0 budget lost to it). All genuine upstream
failures in W3 were 502/503 gateway errors, same as W1/W2.

The wave ran essentially uninterrupted for **~14 h** across all three
windows (W1 start 15:38 → W3 end 05:48 UTC). Small probe curls succeeded
mid-wave several times (~2s latency) — including the "healthy" check that
preceded W3 — so the outage is windowed/request-size-sensitive rather than
a hard down: large context-agent / proposal prompts landed in bad windows
almost every time; the few calls that did get through returned unparseable
output (18× `context agent returned non-JSON` across W2+W3). W3's 13
successful API calls never completed a full context→proposal→eval pipeline.

**Operational lesson:** a single 200 on a small request does NOT mean the
wave ended — W3 was launched right after a verified 200 and still lost all
25 commits. Health-check the endpoint with a proposal-sized call before
spending a window.

Failed proposals are still committed as error entries and consume the
`--solutions` budget, so the wave burned ~72 of 300 total proposal slots
directly (all three windows ended on wall-clock, not budget).

Direction histogram across all 72 proposals (seed excluded):
exploit 53, explore 7, hybrid 7, fresh 4, repair 1 — the context agent
converged on exploit-after-first-win in W1 and stayed there through W3; the
search had committed to refining the bitemporal winner when it starved.

## Amendment — windows 2 & 3 outcome (updated 2026-09-24)

Resuming the same EB for a second AND third 4h window produced **zero new
scored solutions** in each: all 24 W2 commits and all 25 W3 commits died on
retry-exhaustion. The picture does not change:

- **Best score remains s0001 = 95.9952, cost_how = measured** (no new
  challenger; still above every baseline).
- **Per-family win rates across ALL scored solutions** — still n=1 evolved:
  | family | scored instances | best score | verdict |
  |---|---|---|---|
  | bitemporal ledger + per-slot history | 1 (s0001) | 95.9952 | winner by default |
  | event-log replay (seed) | 1 (s0000) | 88.863 | baseline reference |
  | episode+fact / event-sourced / subject-hearsay / graph | 0 | — | **never instantiated** — 72 proposals died before producing code |
- **Probe-type breakdown** unchanged: both scored solutions at 1.0 on all
  new v2 types (as_of / subject / cascade); sole loss remains `transfer`
  on s0001 (0.0).
- **Honesty audit** unchanged: 0 suspicious entries across all 74 commits;
  every error entry is an explicit retry exhaustion, not a scoring anomaly.

Conclusion: the M2 family race is **still open** — bitemporal-ledger holds
the only scored evolved sample (1/1 = 100% of the scored evolved set, but
n=1 across 12 h of wall-clock and 72 dead proposals). Statistical verdict
requires a healthy endpoint.

## Next round (P3 r2) recommendations

1. **Re-run this exact task when Atria is healthy** — three full windows
   now all returned n=1 scored (72 corpses between them): this is a lower
   bound, not a verdict. Resuming again with the same `--work run_v2` EB
   continues the search rather than restarting it — but only when the
   endpoint is actually up; another wave just burns wall-clock. Before the
   next window, verify health with a *proposal-sized* call, not a curl — a
   small-request 200 proved meaningless this round.
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
   exhausted proposals against `--solutions` — 72/74 commits were 8×502/503
   corpses, not real samples.

## Provenance

- Winning dir: `run_v2/eb/solutions/s0001` (direction=explore, parent=s0000,
  eval_version=0), copied here verbatim — `asset.py`, `solution.json`,
  `meta.json`, `solve.sh`, `proposal.txt`, `run.log`.
- Full EB + harness log: `run_v2/` on the lab machine (not committed).
- Dashboard served throughout at `hyra serve --work run_v2 --port 8000`.
