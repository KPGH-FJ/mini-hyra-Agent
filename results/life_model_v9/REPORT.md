# LifeModel P3 round 6 — M4 serve-surface evolution (run_v7) — report

- **Run**: `hyra run --task tasks/life_model --work run_v7 --solutions 100 --workers 4 --wall-clock 21600` (fresh EB; restarted once at ~19:52 UTC to pick up stream-cut recovery)
- **Model**: Atria-Dawn-Preview via `https://api.atria-asi.ai/v1` (OpenAI-compatible reasoning model)
- **Scored on**: HEAD `8024256` (v9.1 bench — 28 probe types incl. first/order/join/absent/window/xcmp + before + derived-revival semantics). The winner was re-scored on this HEAD via `hyra eval` after the window ended.
- **Context seeding**: task.md "What to explore" rewritten locally for M4 serve scope (uncommitted working-tree seed — context agents read it): budgeted packing, purpose views, journal audit serve, premise citation, conflict/confidence grading, attribution, refusal serve, plus v9 history-reasoning probes and the derived-revival clause.
- **Wall clock**: ~6 h active evolution (19:52–01:52 UTC).

## Headline

| entry | score | quality | cost_how | direction | parents |
|---|---|---|---|---|---|
| **s0009** | **145.959** | 146.00 | **measured** | exploit | s0000 |
| s0007 | 144.913 | 145.00 | measured | exploit | s0000 |
| s0010 | 141.908 | ~142 | measured | exploit | s0000 |
| s0015 | 140.880 | ~141 | measured | exploit | s0007 |
| s0012 | 113.148 | ~113 | measured | exploit | s0004 |
| s0018 | 111.049 | ~111 | measured | exploit | s0009 |
| s0025 | 100.280 | ~100 | measured | exploit | s0009 |
| s0008 | 85.379 | ~85 | measured | exploit | s0000 |
| s0016 | 62.633 | ~63 | measured | exploit | s0009 |
| s0004 | 51.717 | ~52 | measured | exploit | s0000 |
| s0023 | 26.956 | ~27 | measured | exploit | s0009 |
| s0000 (seed) | −2.602 | ~0 | reported | seed | — |
| s0011, s0026 | −1e9 | — | — | exploit | malformed output |

**Best honest solution: s0009 = 145.959 — below the round's target (s0040's 147.90) and the v9.1 frontier (~191–195).**
cost_how = `measured` (implements `state()` + `probe_bytes()`); cost = 19.2 KB asset + 16.1 KB probe bytes — the cheapest probe cost of the round (the serve router consults only matched journal slices).

## s0009 strategy (which serve family won)

s0009 is an exploit on the seed built as an **event-sourced journal + serve router**:

- day-authoritative `(day,arrival)` replay with **write-run boundaries** (retraction starts a new run) → `first`/`order`/`absent` = 1.0
- premise fixpoint killing/reviving derived facts (supports ids + premise-value divergence, transitive) → `derive`/`cascade`/`retract` = 1.0
- control ops rewrite the record log and append to a journaled op log surviving export→import → `ops` 0.6, `expdeny`/`revoked` = 1.0
- `state(scope)` scoped-export documents (slot filter; revoked purpose refuses → no doc) → `partial` 0.667
- full serve router covering all 28 probe types; real byte metering.

Quality by probe type (s0009 on v9.1, quality=146.00):

| family | probe types | s0009 | s0007 | s0015 |
|---|---|---|---|---|
| packing/serve | budget, purpose, transfer | **1.0 / 0.75 / 0.0** | 1.0 / 0.75 / 1.0 | ~similar |
| history-reasoning (v9) | first, order, join, absent, window, xcmp, before | **1.0 / 1.0 / 0.0 / 1.0 / 0.0 / 1.0 / 0.0** | 1.0 / 0.0 / 0.0 / 0.5 / 0.0 / 1.0 | — |
| conflict/confidence | isconf, conf | **1.0** / 0.429 | 1.0 / 0.429 | — |
| attribution | subject (+about) | 0.438 | 0.375 | — |
| audit | ops, nchange, duration, drvprov | 0.6 / **1.0** / 0.0 / 0.0 | 0.6 / 0.333 / 0.0 / 0.0 | — |
| refusals | unans, revoked, expdeny, retract, cascade, derive | all **1.0** | all 1.0 | — |
| scoped export | partial | 0.667 | 0.667 | — |
| classic | state, stale, as_of, prov, prov2 | .868 / .778 / 1.0 / .962 / 1.0 | .895 / .815 / 1.0 / 1.0 / 1.0 | — |

**Read**: the serve-seeded families took — `first`/`order`/`absent`/`nchange`/`isconf`/`xcmp`/`budget`/`prov2` all hit 1.0 on the winners (all were ~0.0–0.6 in round 5). The unsolved serve remainder, consistent across ALL candidates: `duration` (0.0 everywhere — days-since-run-start endpoint), `drvprov` (0.0 — derived premise citation), `join`/`window` (0.0 — cross-slot day lookup + window transitions), `before` (0.0 — new in v9.1, nobody implemented it), `ops` capped at 0.6 (journal entries miss the expected scope-string format), `partial` capped at 0.667 (scoped doc emitted but leaks/misses something), `subject` (.38–.44 — attribution still bleeds), `conf` .43.

## EB stats (final)

- **Commits**: 29 (1 seed + 28 proposals).
- **Scored**: 14 (incl. 2 malformed −1e9, 1 seed).
- **Dead by cause** (15):
  - `HTTP 400` at max_tokens=98304 — **13 commits**. Atria's hard cap is 65536 (`max_tokens must be an integer between 1 and 65536`); the 65536→98304 ladder rung makes every over-cap generation a deterministic 8-retry death. Dominant killer of this window.
  - solve.sh exit 2 — 1
  - stream cut 5× (exhausted the 4-continuation ceiling) — 1
- **Stream-cut recovery (6eb5177) worked**: multiple generations resumed mid-flight (cont #1–#3 observed, one with 21.5K chars already generated); only 1 commit died to cut-exhaustion.
- **Throughput**: ~28 proposals in ~6h on 4 workers (~1 scored/25min) — better than round 5's ~1/h.

## Recommendations for the PI

- **The 65536 cap is now THE bottleneck** — 13/15 dead commits were the 98304-escalation 400. One-line fix: cap the ladder at 65536 (retry at cap rather than past it). Would roughly double effective throughput.
- Serve surface is evolvable: 6 of the 12 seeded serve types hit 1.0. Next targets: `duration`, `drvprov`, `join`, `window`, `before` (all 0.0 on every candidate) + `ops`/`partial`/`subject`/`conf` partial credit.
- Dashboard: `hyra serve --work run_v7 --port 8000` live (v3 cockpit layout); preview URL reported to parent session.
