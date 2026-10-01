# Residual lesion dissection: the 10 remaining ms-25 misses after v_selfc

Post-fix audit of the 10/25 questions `v_selfc` still misses (60% arm).
Method: per-question check — does the missing evidence exist in the
selfc model? was its vertex `selected` into the digest? where did the
answer go wrong?

## Lesion classification table

| qid | gold | answered | evidence location | lesion |
|---|---|---|---|---|
| 0a995998 | 3 | 1 | **all 45 vertices in digest** (boots pickup, blazer dry-clean, sweater lent) | R1 answer-side undercount |
| 80ec1f4f | 2 | 1 | all 32 in digest; `niece_museum_visit` = 2nd museum **in digest** | R1 answer-side undercount |
| d682f1a2 | 3 | 2 | 3/3 picked; all 3 services inside `food_delivery_reliance`+`fresh_fusion_delivery` | R1 answer-side undercount |
| c4a1ceb8 | 3 | 2 | 3rd citrus (lemon) inside `sangria_plan` record **in digest** | R1 answer-side undercount |
| d23cf73b | 4 | 3 | `ethiopian_restaurant_experience` + `cuisine_preference` **in digest** | R1 answer-side under-inclusion |
| 88432d0a | 4 | 5 | duplicate sourdough records (same attempt, 2 dates) → read as 2 bakes | R1 overcount via dup (+R3 ingest dedup) |
| gpt4_7fce9456 | 4 | "4" | enumerated the townhouse **itself** + dropped Cedar Creek property | R1 composition/boundary error |
| dd2973ad | 2 AM | hedged | bedtime record exists but anchored "last Wednesday"→May 24 (needed ~May 17); model refused instead of answering 2 AM | R1 over-hedge (+R3 anchor misresolve) |
| 6d550036 | 2 | 1 | **4/58 vertices picked** — 2nd project lives in unpicked vertices | R2 retrieval under-pick |
| gpt4_2f8be40d | 3 | 2 | **9/99 picked** — Jen&Tom barn wedding vertices unpicked | R2 retrieval under-pick |

## Roll-up

- **R1 answer-side = 8/10** — evidence was rendered in the digest; the
  model still under-counted, over-counted via duplicates, mis-composed
  the enumeration, or hedged instead of answering.
- **R2 retrieval under-pick = 2/10** — severe under-selection on large
  catalogs (4/58, 9/99); missing items' vertices never reached the digest.
- **R3 ingest residuals = 2 contributing** — anchor misresolution
  (dd2973ad "last Wednesday"→May 24 vs needed ~May 17) and duplicate-fact
  redundancy (88432d0a sourdough attempt recorded twice).

## Implications

1. Retrieval/ingest is now largely clean: 8/10 misses have the decisive
   evidence **inside the rendered digest** — the failure is downstream
   of retrieval.
2. The residual is the aggregation/composition step — precisely what the
   three-stage code-assist (`assist=True`, opt-in, validated on OR at
   +16pp but injecting errors under Atria) was built for. A next cheap
   arm: re-run these 10 with `assist=True` to see whether deterministic
   candidate-table composition fixes R1 without its Atria-side costs.
3. R2's under-pick (4/58, 9/99) is real but minority — pick-floor
   (min_pick or second-pass "anything missed?") could cover it.
4. R3: two small ingest fixes — date-resolution sanity (relative
   anchors resolved against the *question's* temporal context, not just
   session date) and intra-session dedup (same attempt twice).

## assist=True rescue run on the 10 residual questions (round k+)

Hypothesis tested: three-stage's error injection earlier may have come
from broken ingest, not the candidate-table itself. Re-ran the 10
misses on the clean selfc models (zero re-ingest), `aanswer(assist=True)`,
Atria judge.

**Result: 5/10 rescued, 0 regressions among them**

- WIN: 80ec1f4f (2 museums incl. niece visit), c4a1ceb8 (3 citrus incl.
  lemon), d23cf73b (4 cuisines incl. Ethiopian), d682f1a2 (3 services),
  gpt4_2f8be40d (3 weddings — assist's extraction stage additionally
  recovered an R2 under-pick: Jen&Tom vertices reached the table).
- Still MISS: 0a995998 (2 vs 3, improved), 6d550036 (R2 under-pick
  persists — table can't fix unpicked vertices), 88432d0a (overcount via
  duplicate record persists — R3), dd2973ad (anchor misresolve — R3),
  gpt4_7fce9456 (candidate table bound only 1 property — enumeration
  regressed further but was already wrong).

**Interpretation**: partially confirms "assist is ingest-quality-
dependent, not judge-dependent": on clean ingest it rescued half the
residual with no loss on those five. But the remaining failures are
structural — R2 under-pick, R3 dup/anchor — not answer-side, so assist
cannot be the single fix. Projected combined ceiling on this slice if
assist were on: ~20/25 (80%), pending a full-slice run to confirm no
flips lost on the 15 already-correct questions.

Artifacts: `hyp_assist.jsonl`, `metrics_assist.json` (Atria 5/10).
