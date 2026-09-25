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

---

## Amendment — W2 (streamed, 1969c09): Atria unblocked, first real evolution

Relaunched at 10:42 UTC on the SAME EB after parent's `stream:true`+SSE fix (`hyra/llm.py`, commit 1969c09). Prior serialized test (workers=1, ~40min, 0 scored — single calls still died past the ~5min in-flight kill) was consistent with the duration hypothesis; streaming bypasses it. **Zero 502s in the first 2.5h of W2** — the fix unblocked the endpoint.

### 5-scored milestone (13:18 UTC)

| sol | score | quality | probe_bytes | family (inferred) | losses |
|---|---|---|---|---|---|
| s0040 | **147.9013** | 148.0 | 232.6KB | event-sourced journal | duration/drvprov/isconf/partial/transfer=0; conf .43; subject .5; ops .6 |
| s0037 | 145.9165 | 146.0 | 207.8KB | event-sourced journal | same + nchange 0 |
| s0039 | 145.3928 | 146.0 | 2.86MB | event-sourced journal (fat serve) | same + nchange 0 |
| s0041 | 122.9301 | 123.0 | 41.8KB | event-sourced journal (partial) | broad partial: derive .75, purpose .88, prov2 .6, ops .2, budget .5 |
| s0000 | 55.8307 (v5) / −2.6019 (v8g) | 95.5 | 501.8MB | naive replay seed | everything |

All 5 scored at cost_how=measured; all direction=exploit, parents=[s0000]. Family race at milestone: **event-sourced journal 4/4 scored — the only family instantiated**. Best (s0040, 147.90) vs v8g frontier: lifemodel v1 191 (+43.1 headroom), tms 178, esr 179.

### New failure signature

502s are gone; the residual killers are transport-level: `empty completion (finish_reason=None, data_events≈10.3k)` — the endpoint still cuts streams at roughly the same ~10min wall-clock leash, it just takes longer — plus `truncated; retrying max_tokens=32768/65536` (healthy output-length auto-bump) and rare non-JSON context replies. Net throughput ~1 scored / 40min under 4 workers. Corrections to prior hypothesis: the burst-vs-spaced asymmetry was real but NOT a rate limit — spaced calls survived because short calls finish under the in-flight duration cap; concurrency is confirmed fine once calls stream.

### Provenance

- W2 scored on bench HEAD a68e809+ (v8g semantics incl. control-op ordering, alias edges, derived-state probes, forget_range/exp rebuild); solutions dirs `run_v5/eb/solutions/s0037–s0041` verbatim on disk.
- Scored-HEAD note: s0000's −2.6019 was measured post-pull on v8g; s0037+ were scored live by the harness on the same HEAD.
- Dashboard serving run_v5 on :8000; EB live, run continues to ~16:42 UTC window end.

### W2 final (window end ~16:42 + ~2h retry-drain, exited 18:47 UTC)

W2 produced **18 commits: 6 scored / 12 dead** (cumulative EB 55 commits / 7 scored / 48 dead across both windows). Final scored set:

| sol | score | quality | probe_bytes | parents | note |
|---|---|---|---|---|---|
| s0040 | **147.9013** | 148.0 | 232.6KB | s0000 | best; duration/drvprov/isconf/partial/transfer=0 |
| s0037 | 145.9165 | 146.0 | 207.8KB | s0000 | + nchange 0 |
| s0039 | 145.3928 | 146.0 | 2.86MB | s0000 | fat serve (10× probe bytes) |
| s0041 | 122.9301 | 123.0 | 41.8KB | s0000 | cheap serve but broad partial quality |
| s0046 | 63.3966 | 65.0 | 7.77MB | s0037 | **first non-seed parent — exploit regressed hard** (state .18, stale .11, purpose/budget 0) |
| s0045 | −1e9 | — | — | s0037 | contract-fail: no asset.py with ingest()/answer() |
| s0052 | ERR | — | — | s0040 | solve.sh exit 127 (generated code references missing cmd) |
| s0053/54 | ERR | — | — | s0040 | proposal error: llm 400×8 — truncation ladder hit max_tokens=131072, model rejects |

All scored cost_how=measured, 0 suspicious. Directions: exploit 46 / explore 3 / hybrid 2 / fresh 2 / repair 1 — the search converged hard onto refining the seed/journal family once scorers landed.

### Endpoint state at close

Stream fix held: **zero 502s for the entire 8h** (vs 287 in W1). Residual failure modes, in order of cost: (1) `empty completion (data_events≈10k, finish_reason=None)` — endpoint still cuts streams at ~10min in-flight, the dominant killer; (2) truncation ladder → `max_tokens=131072` → `400` — proposals that outgrow the model window can never complete (s0053/54 both died here); (3) occasional non-JSON context replies; (4) rare solve.sh exit 127. Throughput: ~1 scored / 40min at workers=4 under partial-health. Retry-drain ran ~2h past wall-clock because each dead stream burns ~10min.

### Family verdict at close

**Event-sourced journal is the only instantiated family — 4/4 honest scorers**, best s0040=147.90 vs v8g frontier lifemodel 191 (+43.1 headroom), tms 178, esr 179. All top-4 share the same design (normalized write/control events → day-authoritative reconstruction); they differ only in serve cost and the unresolved gaps (conf .43, subject .5, ops .6, duration/drvprov/isconf/partial/transfer all 0). The two exploit children of s0037/s0040 produced the first regression (s0046, 63.40) and a contract-fail (s0045) — the lineage is explored, not yet refined.

### Next-round targets (unchanged priority)

conf / subject / ops / duration / drvprov / isconf / partial / transfer — ~43 pts of honest headroom to lifemodel v1's 191. Second-order: probe_bytes discipline (s0040's 232KB vs s0039's 2.86MB is a 2.9-pt swing by itself) and getting a second family (tms-supports / filtered-serve) instantiated so the race isn't a walkover.
