# P3 r6 W4 — run_v7 window 4 (deep-history + context-agent fix validation)

**Same EB as W1–W3 (run_v7), no reset. Scored on main HEAD `7fc5150` (v9.1 + PR #31 context-agent tolerant JSON + PR #32 byte-exact deep-history answer shapes).**

## Result

| | |
|---|---|
| **Best** | **s0096 = 166.958** |
| Direction | exploit on s0079 |
| Quality | 167.00 |
| Cost | **measured** — asset 20.8KB + probe 5.2KB (cheapest probe cost of the round) |
| Δ vs W3 best (s0040 156.94) | **+10.02** |
| vs frontier (tms 181 / esr 182) | −14.0 / −15.0 |

Runner-ups: s0091 164.964 (**explore**), s0079 160.816, s0087 158.903, s0040 156.942.

`best/` is the verbatim s0096 solution dir from `run_v7/eb/solutions/s0096` (asset.py 20.8KB, solve.sh, solution.json, meta.json, proposal.txt, run.log). Re-scored after the pull: identical 166.9583 (deterministic).

## Context-agent fix → explore/exploit recovery — YES, restored

W1–W3 direction mix: ~100% exploit (context agent returned non-JSON every cycle → inspiration queue starved).

W4 (PR #31 in tree): **exploit 16, explore 2, hybrid 2, repair 1** — first-ever explore/hybrid commits in run_v7.
- s0083 (explore, s0009) — first explore commit ever; died on eval crash (see deaths).
- **s0091 (explore, s0040) = 164.96** — the revived queue immediately produced a new leader, held it for ~1.5h.
- s0090 / s0097 (hybrid, s0079+s0040) — first-ever hybrids; scored low (63 / 106) but mechanism is alive.
- Zero `context agent returned non-JSON` warnings since W4 start (all 44 warnings in the log are pre-W4).

Verdict: the tolerant-JSON fix works — diversity is back, and it paid off within two commits.

## Deep-history family — zero broken on 3 of 4 stubborn types

| type | W3 best (s0040) | s0096 | |
|---|---|---|---|
| window | 0.0 | **1.0** | broke zero |
| before | 0.0 | **1.0** | broke zero |
| duration | 0.0 | **0.545** | broke zero (partial) |
| nchange | 0.667 | **1.0** | full |
| join | 0.0 | **0.0** | **still the only deep-history zero** |
| drvprov | 0.333 | 0.0 | regressed here (s0091 had .667) |

PR #32's byte-exact answer shapes are the clear cause — window/before/duration broke zero within the first window of the format hints landing. `join` remains the sole holdout (s0091, s0079, s0096 all 0.0).

## Full per-type (s0096)

state .868, stale .778, prov 1.0, subject 1.0, duration .545, unans 1.0, as_of 1.0, derive 1.0, purpose .75, drvprov 0.0, cascade 1.0, conf .429, nchange 1.0, prov2 1.0, budget 1.0, ops .6, retract 1.0, isconf 1.0, first 1.0, order 1.0, **join 0.0**, absent 1.0, window 1.0, before 1.0, revoked 1.0, partial .667, expdeny 1.0, xcmp 1.0, transfer 1.0.

Baselines: raw 107.5, ledger 87.0, rag 66.0, flat 58.5, tms 181.0, esr 182.0, graph 97.5.

## EB / window stats

- EB totals after W4: **99 commits / 75 scored / 24 dead** (dirs overall: exploit 91, explore 2, hybrid 2, repair 2, seed 1).
- W4 window: 21 commits / 18 scored / 3 dead / 2 malformed (−1e9). In-flight s0099+ at close may append on resume.
- **W4 dead-by-cause: all 3 = `evaluator error: 'score'`** (s0083, s0088, s0092) — the residual crash path: PR #27 guards per-probe crashes, but a whole-eval failure still returns a dict without `score` → KeyError at harness.py:108. This is now the dominant death mode (6 of 24 lifetime deaths).
- Zero LLM-path deaths in W4 (clamp + cut-recovery + cap-continuation all held; recoveries fired routinely in the log).
- Cheating check: none — cost_how=measured, probe_bytes 5.2KB (lowest of the round), no contract anomalies.

## Recommendations

1. `join` is the last deep-history zero — its expected shape (`v1→v2` cross-slot at transition day) may need a worked example in the contract, or the probe semantics differ from candidates' traversal model.
2. Add a total-crash fallback in the eval return path (`res` missing `score` → score 0 with error tag) — 'score' KeyErrors are now the #1 killer.
3. drvprov instability (.667 → 0 between siblings) suggests premise-rid tracking is fragile across variants.
