# P3 run_v9 — fresh EB, M4 serve deep-history focus (s0096-study seeding)

**Fresh EB (run_v9), task.md seeded with "STUDY THE CURRENT CHAMPION" (s0096's `run_edges` primitive + remaining targets). Scored on main HEAD `2406903` (v9.1 + eval-verdict-scan #35).**

## Result

| | |
|---|---|
| **Best** | **s0008 = 157.9096** |
| Direction | **fresh** (parents=[]) — greenfield regen, 8th commit of the run |
| Quality | 158.00 |
| Cost | **measured** — asset 42.8KB + probe 34.5KB |
| vs prior best (s0096 166.958, run_v7 EB) | **−9.05** — did NOT beat the banked champion |
| vs frontier (tms 181 / esr 182) | −23.1 / −24.1 |

Runner-ups: s0013 151.960, s0026 151.940, s0014 151.802, s0009 150.962 (explore), s0010 150.944 (explore).

`best/` is the verbatim s0008 solution dir from `run_v9/eb/solutions/s0008` (asset.py ~42KB / 784 lines, solve.sh, solution.json, meta.json, proposal.txt, run.log). Re-scored after pulling to `2406903`: identical 157.9096 (deterministic).

## s0096-study seeding — adopted wholesale, minus one regression

s0008's asset is the studied design verbatim: append-only journal, erasure rewrites the log, retraction opens a new write-run, ONE serve primitive `run_edges(slot, read_day, about)` folded into every deep-history type, traversal meters only the requested edge list.

- s0008 reached 157.91 on commit #8 of a cold EB — run_v7 needed ~40 commits to reach ~157. The champion-study seeding compressed the climb massively.
- Per-type is s0096's profile minus one column: **subject .438** (s0096 had 1.0) — that single regression accounts for the entire ~9pt gap to the champion.

## Direction diversity from cold start — healthy

Dirs: exploit 14, explore 6, hybrid 4, fresh 2, repair 2, seed 1. The leader came from `fresh`; explore produced three of the top six (s0009/s0010/s0006, ~150-151). Exploit mostly regressed off the leader (s0017/s0018/s0025 exploiting s0008 scored 90-114 — cheap variants that lost the fold completeness).

## Deep-history family — status

window 1.0, before 1.0, nchange 1.0, first 1.0, order 1.0, absent 1.0 — all inherited at full score from the studied design. **join 0.0 — still the sole deep-history zero.** **drvprov 0.0** — regressed from s0096's .667 (instability persists across candidates). duration .545 (unchanged plateau).

## Full per-type (s0008)

state .868, stale .778, prov 1.0, subject .438, duration .545, unans 1.0, as_of 1.0, derive 1.0, purpose .75, drvprov 0.0, cascade 1.0, conf .429, nchange 1.0, prov2 1.0, budget 1.0, ops .6, retract 1.0, isconf 1.0, first 1.0, order 1.0, **join 0.0**, absent 1.0, window 1.0, before 1.0, revoked 1.0, partial .667, expdeny 1.0, xcmp 1.0, transfer 1.0.

Baselines: raw 107.5, ledger 87.0, rag 66.0, flat 58.5, tms 181.0, esr 182.0, graph 97.5.

## EB / window stats

- **29 commits / 21 scored / 8 dead** + 2 malformed-contract scores (−1e9: s0003, s0028).
- Dead-by-cause: **`evaluator error: 'score'` ×4** (s0011 fresh, s0021 hybrid, s0023 exploit, s0024 explore — the whole-eval crash path, still unguarded), proposal-no-solve.sh ×3 (s0005, s0015, s0022), solve.sh exit 1 ×1 (s0004). Zero LLM-path deaths (clamp + cut-recovery + cap-continuation held; routine stream-cut resumes in the log).
- LLM usage this window: 66 calls / ~1.95M completion tokens.
- Cheating check: cost_how=measured; real measured cost used for scoring. One contract-honesty flag: the asset's own `stats()` endpoint self-reports asset_bytes=889 / probe_bytes=2082 vs measured true 42812 / 34522 — under-reporting is cosmetic (evaluator trusts only measured) but worth watching if stats() ever feeds scoring.
- task.md diff included in this branch for audit (the s0096-study seeding block).

## Recommendations

1. `join` remains 0 across every candidate in both EBs — likely needs a worked example in task.md, not just a shape hint.
2. `evaluator error: 'score'` total-crash fallback is now the #1 killer (4/8 deaths this run; 10 lifetime) — wrap the eval call site so a crashed eval returns score 0 + error tag instead of KeyError.
3. subject regressed 1.0 → .438 when regenerating fresh — attribution logic (entity-alias/subject-of-record) is the most fragile fold; a targeted exploit on s0096 restoring subject while keeping its serve cost may recover the ~9pt gap cheaply.
4. drvprov flip-flops .667 → 0 between siblings — premise-rid tracking is load-bearing but brittle.
