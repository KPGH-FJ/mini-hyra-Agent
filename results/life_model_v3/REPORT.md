# P3 r2 — M3 Update evolution: REPORT

Work dir: `run_v3` (fresh) · `hyra run --task tasks/life_model --work run_v3 --solutions 100 --workers 4 --wall-clock 21600` · model Atria-Dawn-Preview · launched 2026-09-24 17:53 UTC, inner loop done 2026-09-25 00:35 UTC (~6h + drain).

## Headline

| solution | score | cost_how | notes |
|---|---|---|---|
| s0000 (seed) | **89.3238** | reported | event-log replay; only scored solution |
| lifemodel v1 (incumbent, parent-measured) | 108.995 | measured | the bar — not in this EB |
| baselines (seed digest) | raw 106.5 / ledger 83.5 / rag 79.0 | — | |

**Zero evolved solutions scored.** All 34 proposals died on Atria 502 retry-exhaustion: 272 failed LLM attempts (34 × 8/8 exhaustion) + 14 non-JSON context replies; ~0 successful API calls all window. The wave ran unbroken for the entire ~6h. Parent's pre-launch "proposal-sized 200" was, once again, a gap — not health.

cost_how flag: s0000's `reported` is the frozen seed's own self-report (the harness doesn't meter the seed), same caveat as r1 — not spoofing, but not measured either. No `suspicious` entries in the EB.

## Quality breakdown (s0000, M3 probes)

| probe | quality | | probe | quality |
|---|---|---|---|---|
| state | 0.862 | | derive | **0.75** |
| stale | 1.0 | | cascade | **0.50** |
| prov | 0.962 | | retract | 1.0 |
| subject | 0.909 | | transfer | 1.0 |
| as_of | 0.889 | | | |

M3 cost: `probe_bytes` 59.67MB (seed replays stream per probe) − `asset` 10.8KB → total cost ≈ 11.7 → 101.0 − 11.7 = 89.32. `llm_tokens` 0.

The M3 contract bites exactly where parent predicted: **cascade 0.50 and derive 0.75** are the headline losses — the seed tracks deriveds flat with no supports-wiring, so dead-premise leaks bleed it (−0.5/dead-premise). post_import probes don't appear as their own breakdown key (no `import_state` → they score 0 by contract). ~19.7 points separate seed from the lifemodel v1 incumbent — the TMS/supports-tracking delta.

## Representation family race

- **Event-log replay** (seed): 1/1 scored, 89.3238 — correct-but-naive: no derived-registry, no probe meter.
- **TMS / supports-tracking / AGM / event-sourced re-derivation / materialized-view / bitemporal-rules** (the pre-seeded candidate families): **0 instantiations** — every proposal died before producing code. The race never ran; no verdict possible this window.
- Direction histogram over the 34 corpses: exploit 22 / explore 6 / fresh 4 / hybrid 2 / repair 1 — the search committed early to refining the seed lineage and starved.

## Error-rate summary

- 272 HTTP 502 (100% of failures) across 34 proposals — every single call exhausted 8/8 retries.
- 14 context-agent non-JSON replies (empty-body responses — overload signature).
- Duration: 17:53 → 00:35 UTC; 502s continuous from first proposal call to last (verified by log scan; zero gaps long enough for a proposal→eval pipeline to complete).

## Window table

| window | span | commits | scored | corpses | best |
|---|---|---|---|---|---|
| r2 only | 17:53–00:35 | 35 | 1 | 34 | s0000 = 89.3238 |

(Cumulative for run_v3 — fresh EB, no M2 carryover.)

## Next round

Same prescription as before, sharper: the M3 target is now precisely quantified — a supports-wired derived-registry that kills cascade leaks (0.50→~1.0) and derive misses (0.75→~1.0), plus `import_state` for post_import, plus a probe meter to cut 59.7MB→KB. If the lifemodel v1 package already implements supports tracking, the r3 race is whether evolution can beat 108.995, not whether it can find the family. Gate on N consecutive proposal-sized successes over ~1h before launching — this window's pre-launch 200 was a false positive.

## Provenance / lab notes

- r2 task files applied UNCOMMITTED to the working tree per parent instruction (disclosed pattern): `git checkout origin/feature/m3-round -- tasks/life_model/{bench/generator.py,evaluate.py,task.md,lifemodel_v1/asset.py} lifemodel/{ingest.py,store.py,model.py}` on top of main @16f037f. Dashboard v3 files also present uncommitted (feature/dashboard-research) — serving run_v3 at :8000.
- Results contents verbatim from `run_v3/eb/solutions/s0000/` (the only scored solution): asset.py, meta.json, run.log (empty — seed logs to EB only), solve.sh. `__pycache__` omitted.
- One operational note: at launch a `pkill -f "hyra serve"` self-matched the launcher shell's cmdline and killed it mid-command — run_v3 itself was unaffected (verified via /proc/environ); serve restarted cleanly. No commits lost.
- EB + dashboard remain live in run_v3 — resumable on demand (`hyra run --work run_v3` resumes; EB entries persist).
