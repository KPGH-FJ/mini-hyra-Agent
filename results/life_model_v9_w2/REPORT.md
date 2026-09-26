# LifeModel P3 r6 W2 — M4 serve-surface evolution, second window (run_v7) — report

- **Run**: `hyra run --task tasks/life_model --work run_v7 --solutions 100 --workers 4 --wall-clock 21600` — resumed on the SAME EB as W1 (W1 ended at 29 commits / 14 scored / 15 dead; W2 added ~19 more)
- **Model**: Atria-Dawn-Preview via `https://api.atria-asi.ai/v1`
- **Scored on**: `origin/main` HEAD `2bfa135` (v9.1 bench + PR #20 cap-truncation continuation fix). Winner re-scored post-window via `hyra eval` — identical score.
- **W2 harness fixes in play** (cherry-picked before restart): `min(max_tokens*2, 65536)` ladder clamp (d46a06f) + 60000-char proposal-base bound + contract-first task.md warning (0259e43).
- **Window**: ~6h (02:49–08:49 UTC).

## Headline

| entry | score | quality | cost_how | direction | parents |
|---|---|---|---|---|---|
| **s0040** | **156.942** | 157.00 | **measured** | exploit | s0009 |
| s0047 | 147.896 | ~148 | measured | exploit | s0009 |
| s0009 | 145.959 | 146.00 | measured | exploit | s0000 |
| s0007 | 144.913 | 145.00 | measured | exploit | s0000 |
| s0038 | 144.844 | ~145 | measured | exploit | s0009 |
| s0010 | 141.908 | ~142 | measured | exploit | s0000 |
| s0015 | 140.880 | ~141 | measured | exploit | s0007 |
| s0045 | 139.899 | ~140 | measured | exploit | s0009 |
| s0012 | 113.148 | ~113 | measured | exploit | s0004 |
| s0018 | 111.049 | ~111 | measured | exploit | s0009 |

**Best honest solution: s0040 = 156.942** — beats the W1 result (s0009 145.96) by +10.98; below the ~182 esr frontier but approaching lab#1's parallel 158.2. cost_how = `measured`; cost = 29.4KB asset + **2.1KB probe bytes** (lowest probe cost of the run — the serve router consults a minimal journal slice).

## s0040 — what moved it

Exploit on s0009 (event-sourced journal + serve router). Deltas that landed vs s0009:

- `subject` 0.438 → **1.0** (attribution fixed — was bleeding since W1)
- `drvprov` 0.0 → **0.333** (first nonzero derived-premise citation of the round)
- `nchange` 1.0 → 0.667, `transfer` 0.0 → **1.0** (reabsorbed the v9.1 regression), `probe_bytes` 16.1KB → **2.1KB** (probe-cost engineering: consult only the matched slice)
- Kept first/order/absent/xcmp/isconf/budget/prov2/unans/expdeny/revoked/cascade/derive/as_of/prov at 1.0; `partial` 0.667, `conf` 0.429, `ops` 0.6, `purpose` 0.75.

Per-type breakdown (s0040 on 2bfa135): state .868, stale .778, prov 1.0, **subject 1.0**, duration 0.0, unans 1.0, as_of 1.0, derive 1.0, purpose .75, **drvprov .333**, cascade 1.0, conf .429, nchange .667, prov2 1.0, budget 1.0, ops .6, retract 1.0, isconf 1.0, first 1.0, order 1.0, **join 0.0**, absent 1.0, **window 0.0**, **before 0.0**, revoked 1.0, partial .667, expdeny 1.0, xcmp 1.0, transfer 1.0.

**Remaining consistent zeros across ALL candidates**: `duration`, `join`, `window`, `before` — the deep-history/cross-slot families nobody has cracked. `conf` (.429), `ops` (.6), `partial` (.667) still partial-credit.

## EB stats (48 commits total, end of W2)

- **Scored**: 30 (incl. seed −2.60, four −1e9 malformed-contract submissions)
- **Dead**: 18 total = **15 from W1** (13 cap-400s + solve.sh exit 2 + cut-exhaustion) + **3 in W2**: `evaluator error: 'score'` ×3 (s0035, s0037, s0046 — eval crashes, not LLM-path; worth a look — same error string each time)
- **Zero LLM-path deaths in W2** — the 65536 clamp converted the deterministic killer into retries (`truncated; retrying max_tokens=65536` ×~6 observed, all recovered)
- **Stream-cut recovery carried the window**: ~10 mid-flight resumes logged (cont #1–#4), incl. one 12KB-chars save; several completions survived 3+ cuts
- Throughput: ~19 new proposals in ~6h ≈ same rate as W1 but with ~94% survival vs ~48%

## Recommendations for the PI

- W2's marginal gain came from serve-correctness consolidation (subject/drvprov/transfer up) + probe-byte cost engineering, not new storage. The remaining ~25-pt gap to esr lives in duration/join/window/before + ops/partial/conf.
- `evaluator error: 'score'` (3×) is the new dominant non-LLM killer — likely a probe-type output shape the evaluator chokes on; a harness-level try/except per probe would stop burning those commits.
- Context agent still returns non-JSON ~every cycle (pre-existing; harmless but starves inspirations).
- Per standing order: no further rounds started; session idles pending your go.