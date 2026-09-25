# P3 r3 — M1 Ingest + serve pressure (v5 bench): REPORT

Work dir: `run_v5` (fresh) · `hyra run --task tasks/life_model --work run_v5 --solutions 100 --workers 4 --wall-clock 21600` · Atria-Dawn-Preview · launched 2026-09-25 03:13 UTC, inner loop done 09:57 UTC (~6h + drain).

**Scored HEAD: a68e809 (v8g).** Run started on v5 semantics (136-probe contract); per parent instruction the bench was pulled to v8g before deliverables and the scored EB re-verified — see "Re-score under v8g".

## Headline

| solution | score (v5 eval) | score (v8g re-eval) | cost_how |
|---|---|---|---|
| s0000 (seed) | **55.8307** | **−2.6019** | reported (frozen seed self-report; not spoofing) |
| lifemodel v1 (parent-measured) | 135.97 (v5) | — | measured |
| baselines (v5 digest) | tms 128+ / esr 128+ / raw 104.5 / ledger 89.5 / rag 48.5 / flat 49.0 | tms 178.0 / esr 179.0 / raw 105.5 / ledger 85.0 / rag 64.0 / flat 54.5 | — |

**Zero evolved solutions scored.** All 36 proposals died on Atria 502 retry-exhaustion: 288 failed LLM calls (287×502, 1×DNS) + 20 non-JSON context replies; 0 successful proposal pipelines in ~6.7h. The wave ran effectively the whole window.

## Quality breakdown — s0000 under v8g (the current contract)

| probe | q | | probe | q | | probe | q |
|---|---|---|---|---|---|---|---|
| retract | 1.0 | | stale | 0.704 | | duration | 0.0 |
| unans | 1.0 | | subject | 0.625 | | purpose | 0.0 |
| expdeny | 1.0 | | state | 0.566 | | drvprov | 0.0 |
| transfer | 1.0 | | cascade | 0.5 | | conf | 0.0 |
| prov | 0.885 | | derive | 0.75 | | nchange | 0.0 |
| as_of | 0.889 | | | | | prov2 | 0.0 |
| | | | | | | budget | 0.0 |
| | | | | | | ops | 0.0 |
| | | | | | | isconf | 0.0 |
| | | | | | | revoked | 0.0 |
| | | | | | | partial | 0.0 |

quality=95.5 vs probe_bytes=501.8MB → **score −2.60**: on v8g the naive replay seed scores NEGATIVE — ~180 probes × full-stream replay is now the dominant loss (−98), ahead of all the serve/ingest gaps. Baselines moved up hard (tms 178 / esr 179): TMS-supports + event-sourced-replay families now sit ~178 above the seed's honest number.

## Families observed

- **Event-log replay** (seed): 1/1 scored — 55.83 (v5) / −2.60 (v8g). Correct-but-naive at every new probe type.
- **M1 ingest families** (source-authority / entity resolution / day-ordered / dedup / trust-weighted) **and** M4 serve families (router+views / abstention / budgeted packing / citation): **0 instantiations** — no proposal survived to eval.
- Directions over 36 corpses: exploit 28 / explore 3 / hybrid 2 / fresh 2 / repair 1.

## Endpoint asymmetry (lab observation, new)

The 20-min prober (single ~15KB call, spaced) **succeeded 6 times** during the window (62-146s latencies, 1785-4763 completion tokens) while the run's 4-concurrent proposal bursts got 502s ~100% of the time. Atria can serve isolated spaced calls but rejects concurrent bursts — the harness's parallelism is what the wave kills. A `--llm-concurrency 1`-style serialized mode would likely land proposals through gaps that bursts can't use.

## Window table

| span | commits | scored | corpses | best |
|---|---|---|---|---|
| 03:13–09:57 UTC | 37 | 1 | 36 | s0000 = 55.8307 (v5) / −2.6019 (v8g) |

## Next round

1. **Serialize LLM calls** (concurrency 1) or pace bursts to the endpoint's gap rhythm — the single biggest unlock; health exists but only for spaced calls.
2. Gate remains N-consecutive proposal-sized successes over ~1h — but ALSO verify a small concurrent burst (2-3 parallel calls) passes, since single-call health no longer predicts burst health.
3. Scoring target: under v8g the floor is negative — a winning solution needs probe metering (filtered/serve index → KB not MB) BEFORE quality work matters.

## Provenance / lab notes

- v5 task files via `git pull origin feature/m3-round` (merge onto local main, per parent command) at ~03:10; v8g HEAD pulled at ~10:05 for re-scoring per parent instruction. Earlier v4 files had been applied uncommitted then reverted — superseded.
- Results contents verbatim from `run_v5/eb/solutions/s0000/` (only scored solution): asset.py, meta.json, run.log (empty), solve.sh.
- Gate machinery ran before launch (4-consecutive-OK prescription): passed 1/4 probes before the v5 pivot — parent's direct verification served as launch signal instead. Recurring self-pkill footgun (pattern matching own cmdline) fixed by PID kills; 0 commits lost.
- EB + dashboard remain live in run_v5 on :8000 (resumable on demand).
