# LifeModel P3 r6 W3 — M4 serve deep-history window (run_v7, same EB) — report

- **Run**: `hyra run --task tasks/life_model --work run_v7 --solutions 100 --workers 4 --wall-clock 21600` — third window on the SAME EB (resumed at 48 commits)
- **Model**: Atria-Dawn-Preview via `https://api.atria-asi.ai/v1`
- **Scored on**: `origin/main` HEAD `ac5ad15` (v9.1 + per-probe eval guard PR #27 + task.md from research/next-round-m4 PR #29). Winner re-scored post-window via `hyra eval` — identical score (bench deterministic).
- **Context seeding**: task.md replaced with the research/next-round-m4 version — deep-history specialization: unified (subject,slot,read_day)→ordered-edge traversal primitive `{day,value,rid,authority,alive}`, each deep-history type a thin fold over it; forbids per-type processors; points at s0095/s0040 as reference winners.
- **Window**: ~6h (07:29–13:29 UTC).

## Headline

| entry | score | quality | cost_how | direction | parents |
|---|---|---|---|---|---|
| **s0040** | **156.942** | 157.00 | **measured** | exploit | s0009 |
| s0063 | 149.649 | ~150 | measured | exploit | s0040 |
| s0047 | 147.896 | ~148 | measured | exploit | s0009 |
| s0071 | 146.896 | ~147 | measured | exploit | s0040 |
| s0009 | 145.959 | 146.00 | measured | exploit | s0000 |
| s0049 | 144.936 | ~145 | measured | exploit | s0040 |

**Best honest solution: s0040 = 156.942** — W2's winner survived W3; the deep-history seeding produced solid followers (s0063 149.65, s0071 146.90, s0072 124.97) but no new champion and **no deep-history family broke zero**.

## Deep-history outcome (the round's question)

- `duration`, `join`, `window`, `before`: **still 0.0 on every candidate including all W3 proposals** — the traversal-basis seeding did not crack them this window.
- Best W3 mover was consolidation, not depth: s0063 (149.65, exploit on s0040) — per-type numbers in EB meta if needed.
- `drvprov` stayed at s0040's .333; `conf` .429, `ops` .6, `partial` .667 unchanged — the serve surface has hit a hard plateau on this strategy family.

## EB stats (74 commits cumulative, end of W3)

- **W2→W3 delta**: +26 commits, +23 scored, +3 dead. W3 deaths: `no solve.sh` ×2 (s0050, s0061 — proposal format misses), `evaluator error: 'score'` ×1 (s0066 — fired BEFORE I pulled PR #27's per-probe guard; main now wraps per-probe).
- **W3 vs W1**: same proposal rate (~1/25min) but survival ~92% vs ~48% — the 65536 clamp + stream-cut recovery + cap-truncation continuation all working (PR #20's `truncated at cap; continuing` path saved ≥2 generations).
- Context agent still non-JSON every cycle (starves inspirations — proposals default to exploiting s0040, which is why every W3 candidate is an s0040-variant).

## Recommendations for the PI

- Deep-history is stubborn: the edge-traversal basis was seeded but candidates still fold it wrong — `duration`/`window`/`join`/`before` may need contract text with the expected output shape, not just the strategy hint. The probes' exact expectations are in `docs/PROBE_SEMANTICS.md`/`bench/`.
- The `no solve.sh` misses ×2 suggest the contract-first warning isn't fully sticking; consider printing the file-protocol skeleton verbatim in task.md.
- Per standing order: idle after this report; no new rounds until you assign.