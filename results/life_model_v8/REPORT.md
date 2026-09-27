# LifeModel M4 — run_v8 deep-history serve round — report

- **Run**: `hyra run --task tasks/life_model --work run_v8 --solutions 100 --workers 4 --wall-clock 21600` — fresh EB (run_v5 hit its 100-commit cap; this round starts from seed)
- **Model**: Atria-Dawn-Preview via `https://api.atria-asi.ai/v1`
- **Bench**: v9.1 pinned from main HEAD at launch (f6820ad tree == origin/main bench files; ~199 probes/seed incl. `before` + v9 history families). **No bench mixing this round** — all 53 evals ran on v9.1.
- **Guidance applied**: `tasks/life_model/task.md` from `research/next-round-m4` (uncommitted at run time, per direction) — seeds the unified history-edge traversal `(subject,slot,read_day)→alive ordered write-segment edges` as the base inspiration, names s0095/s0040 as winners to study, and bans per-type processors.
- **Termination**: wall-clock cap — final live segment ran 04:01→11:53 UTC Sep 27 (7.87h process elapsed > 21600s; the cap is checked between inner-loop rounds). EB ended at **53 commits / 40 scored / 13 dead**, not the 100-solution cap.
- The box restarted ~14 times during the first day (each kill → resume on the same `--work run_v8`); the active monitor loop kept the final segment uninterrupted.

## Headline — who won

| entry | score | quality | cost_how | direction | parents |
|---|---|---|---|---|---|
| **s0030** | **152.390** | 153.00 | **measured** | exploit | s0001 |
| s0001 | 151.813 | 152.00 | measured | repair | s0000 |
| s0036 | 149.927 | 150.00 | measured | exploit | s0001 |
| s0049 | 149.347 | 150.50 | measured | exploit | s0030 |
| s0012 | 148.411 | 148.50 | measured | exploit | s0001 |
| s0011 | 144.427 | 144.50 | measured | exploit | s0001 |
| s0018 | 143.921 | 144.00 | measured | exploit | s0001 |
| s0022 | 143.848 | 144.00 | measured | exploit | s0001 |

**Winner: s0030 = 152.390** — exploit of s0001 (itself a repair of seed s0000). The whole scored field is one lineage: every top-8 entry descends from s0000/s0001. Direction mix across all 53 commits: 47 exploit, 3 hybrid, 1 explore, 1 repair, 1 seed.

s0030's proposal shows the M4 directive landing verbatim: *"the serve layer is rebuilt around one uniform (subject,slot,read_day) WRITE-RUN traversal instead of per-type readers. Deep-history probes are folds over that traversal."* (asset version tag `life-model-serve-run-edge`).

## Did deep-history families break zero? — partially

vs run_v5 winner s0095 (all five v9 history families = 0):

| family | s0095 (v5) | s0030 (v8) |
|---|---|---|
| first | 0 | **1.0** |
| order | 0 | **1.0** |
| absent | 0 | **1.0** |
| xcmp | 0 | **1.0** |
| nchange | 0 | **1.0** |
| isconf | 0 | **1.0** |
| partial | 0 | **0.667** |
| duration | 0 | 0 |
| join | 0 | 0 |
| window | 0 | 0 |
| before | 0 | 0 |
| drvprov | 0 | 0 |

**Verdict**: the traversal primitive cracked the *comparator* families (first/order/absent/xcmp + nchange + isconf) but none of the *interval-fold* families (duration/window/join/before/drvprov). The pattern is consistent: edge-day comparisons fold cleanly; anything needing per-day span integration or premise-chain resolution still fails.

Remaining losses on s0030: state .763, stale .778, purpose .75, partial .667, ops .6, conf .429 — plus the five zeroed families. Headroom to system baselines: tms 181 / esr 182 → **~28.6 pt** to tms; −6.5 vs run_v5 winner s0095 (158.911, 100-commit EB).

## Cheating check

Clean: **0 suspicious** across the EB — 39 entries `cost_how=measured`, 1 `reported`. Contract discipline held: only **1 contract-fail** (−1e9, s0010) out of 53 commits — the task.md contract-first warning did its job (vs 6/24 fails in run_v5 W3).

## Cost profile

Winner s0030: asset 28.4 KB + **probe 2.84 MB** + 0 LLM tokens → 153 − 0.056 − 0.554 = 152.390. The probe is ~45× heavier than s0095's 63 KB — the uniform traversal emits full edge lists instead of filtered slices, so **serve-cost engineering (selective edge emission / fold-in-serve) is the open exploit direction**. s0001 proved the cheap path exists (probe 473 KB at q=152); s0036 got probe down to 52 KB at q=150.

LLM usage (final process segment only; earlier segments' counters were lost to box restarts): 66 calls / 302k prompt / 2.05M completion tokens.

## Dead profile (13/53)

- **7 evaluator-crash** `evaluator error: 'score'` (s0006/s0016/s0019/s0027/s0034/s0038/s0045) — the evaluator itself raised KeyError 'score' on these entries; **new signature this round**, not a solution-side crash. Worth a look on the harness side — 13% of commits lost to it.
- **4 no-solution proposals** (s0007/s0015/s0032/s0040) — LLM produced no solve.sh.
- **1 contract-fail** −1e9 (s0010), **1 solve-exit-1** (s0021).

## Files

`best/` = s0030 verbatim (`asset.py`, `meta.json`, `proposal.txt`, `solution.json`, `solve.sh`; `run.log` is empty — eval output lives in `meta.json` feedback).
