# Grounded-inference gate + temporal-anchor resolution — LoCoMo arms

Two arms on top of the PR #81 final stack (relaxed gate + assist), Atria ingest/answer/judge, same snapshots.

- **Arm G — `premise_check="grounded"`** (reader): extends relaxed with a new verdict `GROUNDED_OK` — when the premise is `premise_expected` but atoms are unbound AND ≥1 atom did bind (entity context exists), the answerer gets a PREMISE NOTE block: state plainly the specific fact is not recorded, then give the best-supported inference from bound records; never present inference as recorded. `SPLICED` stays hard-refused.
- **Arm T — `_resolve_rel_anchors`** (ingest_llm): deterministic post-pass resolving `(on <relative phrase>)` to `YYYY-MM-DD` via session-day ordinal ± offset (last week→−7, next month→+30, yesterday→−1, ...). Validated on snapshots by replaying the resolver over hist edges (identical strings to ingest-time application).

## Headline numbers

| scope | baseline (final stack) | arm | delta |
|---|---|---|---|
| cat3 ×96 (all convs) | 34/96 = 35.4% | **44/96 = 45.8%** | **+10.4pp** (15 win / 5 lose) |
| cat5 sentinel ×112 (c0–c2) | 103/112 = 92.0% | **96/112 = 85.7%** | **−6.3pp** — holds ≥85% red line, real cost |
| cat2 ×321 (anchor arm) | 190/321 = 59.2% | **182/321 = 56.7%** | **−2.5pp** — net negative, see mechanism |

## Arm G verdict mix (cat3)
NO_PREMISE 31, GROUNDED_OK 35, SUPPORTED 11, SYNTHESIS_OK 4, ABSENT 3, SPLICED 2, ERROR 10→(swept) — the 35 GROUNDED_OK rows produced "no record + best-supported inference" answers.

### cat3 rescue profile — grounded inference also answers external-knowledge questions
Wins include not just the L2 binding failures (c4_q8 Under Armour, c7_q36 age, c7_q40 beach, c4_q15 Anthony, c3_q68-style counts) but **4 L1 external-fill questions the gate couldn't previously touch** — the inference tail legitimately uses world knowledge over a grounded record:
- c7_q28 Colombia ("vacation in Bogotá last summer" → Colombia)
- c7_q75 Exploding Kittens ("a card game about cats…" → the name)
- c4_q28 John Williams, c8_q57 California (Lake Tahoe → state)
- c8_q71 **Christmas** — the L3 target: resolved anchor "married (on 2023-12-19)" + grounded inference → holiday season. Joint arm win.
- c9_q4 — baseline's L5 reasoning miss ("Japan") corrected to "United States" (Boston meet plan bound).
Losses (5): 2 infra ERRORs (persistent truncation), 2 judge-draw flips on identical-verdict rows (c0_q30, c0_q2), 1 real regression — c2_q17 "What might John's degree be in?" answered an unfounded inference (poli-sci) where the no-record answer scored better. **Net real arm effect ≈ +11 after removing noise.**

### cat5 sentinel — the leak mechanism is precise, not diffuse
96/112 = 85.7%. Losses (16): 8 are **GROUNDED_OK inference-tail fabrications** — the response correctly says "no record of X" but then names a specific unrecorded value, which the judge counts as an answered-wrong rather than an abstention:
- c1_q97 "Where is Gina's HR internship?" → "no record of HR internship… best-supported inference: **fashion department of an international company**" — confident wrong value in the tail.
- c0_q186, c0_q159, c1_q96, c2_q154, c2_q161, c2_q181, c2_q179 — same form.
The other 51-8=43 GROUNDED_OK cat5 rows still scored correct — the judge reads "no record" as abstention whenever the tail stays generic; it only punishes confident specific guesses. Remaining losses: ~4 known benchmark mislabels (bowl/guitar/trophy/5K — transcript-verified), 2 judge-draw boundary rows, 2 wins offset.

**Refinement for v2** (not yet run): restrict the inference tail — forbid naming a concrete value for the asked slot when no record supports it ("give the closest grounded facts, do not guess the missing value"). The marker-gate idea (inference-words only) was tested against the data and rejected: 42/43 cat5 wins carry no inference marker, and 13/16 cat3 wins don't either — gating on `might/could` would kill most of the rescue for no extra defense.

## Tail-constraint dial — v2 and v3 re-runs (parent acceptance: cat3 ≥+8pp AND cat5 ≥88%)

Same GROUNDED_OK gate; only the PREMISE NOTE tail text varies.

| arm | tail contract | cat3 ×96 | cat5 ×112 |
|---|---|---|---|
| v1 (unconstrained) | "give the best-supported inference" | 44 = 45.8% (+10.4pp) | 96 = 85.7% |
| v2 (no concrete values) | "NEVER assert a concrete value for the missing slot" | 40 = 41.7% (+6.3pp) | **103 = 92.0%** |
| v3 (entailment-gated) | "concrete value ONLY when it follows directly from a bound record; no basis → abstain" | **44 = 45.8% (+10.4pp)** | **99 = 88.4%** |

- **v2 overshoots**: forbidding concrete values reverts legitimate named inferences to hedged non-answers — v1→v2 cat3 losses are exactly the L1 external-fill rescues (c8_q57 Lake Tahoe→state withheld; c7_q75 cat-card-game name withheld; c4_q28 composer; c4_q32 Universal→state; c7_q36/c7_q40/c0_q81/c2_q39 hedged). cat5 fully recovers to baseline 92.0% but cat3 drops below the +8pp bar.
- **v3 passes both bars**: +10.4pp ≥ +8pp and 88.4% ≥ 88% (not 90+). cat3 ties v1 — entailment clause preserves the external-fill rescues (c6_q30 Toronto→Canada asserted and won). cat5 residual leak is the same confident-tail shape — the model rationalizes a record basis that doesn't entail the value (c0_q186 "**Sara Bareilles**" as "best-supported inference"; c0_q156, c0_q190, c2_q162, c2_q167 similar; 5 of 8 v2→v3 regressions are this pattern). cat5 v3 losses vs v2: 8, wins: 3.
- **Noise caveat**: single-draw Atria judge flips run ±2–3 questions per arm; 88.4% sits within noise of the 88% line. Recommend 3× judge replication on the ~12 boundary rows before treating v3-vs-v2 cat5 delta as final.
- Data: `grnd2_*` / `grnd3_*` jsonl (each 208 rows: cat3 96 + cat5 112), same `grounded_arm.py` driver with `ARM_TAG` output prefix. c2_q185 marked answer-failed (truncated-retry loop).

### Dial frontier — what the three points say
The tail contract is a real operating-point dial between cat3 rescue and cat5 defense: unconstrained +10.4/85.7 → entailment-gated +10.4/88.4 → no-values +6.3/92.0. v3 dominates v1 (same cat3, +2.7pp defense); v2 buys +3.6pp more defense for −4.1pp cat3. Pick v3 as the shippable default; v2 is the option if cat5 ≥90 is ever required.

## Arm T — anchor resolution: net negative as implemented
Wins 23 / losses 31. The loss mechanism is **granularity overshoot**: coarse phrases got day-precision dates the text never claimed — "(on last month)" said in October resolves to a specific September *day*, so "when did X" answers fabricate (or collide with) a wrong day, and some atoms then fail binding. 23 wins are real (absolute dates unblock computations, e.g. the c8_q71 joint win), but the naive -30d/-7d map is wrong for month/week phrases.

**v2 design (recommended, unmeasured)**: resolve with matching granularity — "last month" → `YYYY-MM` of prior month, "last week" → "the week of YYYY-MM-DD", "a few days ago" → span. Keep day-resolution only for phrases that name a day ("yesterday", "last Tuesday"). Do NOT ship the current `_REL_DAYS` map as-is.

## Data
`grnd_cat3_c{0..9}.jsonl` (96), `grnd_cat5_c{0..2}.jsonl` (112), `anch_cat2_c{0..9}.jsonl` (321), driver `grounded_arm.py` — all per-question rows carry verdict + response + judge outcome. Infra: ~34 congestion ERROR rows swept once; residuals counted.

## Bottom line
- **Grounded gate**: ship v3 for review — +10.4pp cat3 AND 88.4% cat5 sentinel, meets both acceptance bars; residual cat5 cost is confined to confident inference tails that rationalize a record basis (candidate future hardening: verifier-side entailment check instead of prompt contract).
- **Anchor resolver**: correct lesion, wrong granularity — needs v2 before merging; L3 lesions provably fixable (c8_q71).
- cat3 45.8% still trails other categories; residual = benchmark external-fill (~L1) and open-ended judge strictness (~L4) — see CAT3_AUTOPSY.md.
