# Abstention-precision dial ablation — LoCoMo conv-0

Second fix-stack refinement round. PR #52's relaxed abstention lifted conv-0
33.3%→66.7% but cost adversarial precision (75%→58%: q156/q159/q163 produced
confident-looking answers from adjacent-but-insufficient memories). This
round dials `ANSWER_SYS` only — same ingest, same retrieval — to recover
adversarial precision without re-breaking answerable categories.

## Setup

- Ingest: conv-0 (19 sessions), LLMIngestor twostage, OR stealth/space-bunny-alpha
  (`reasoning.exclude`+`reasoning.max_tokens` bound), 593–720 records per arm run
  (ingest is LLM-stochastic; arms share one ingest each).
- Question set (n=22): all 12 cat5 adversarial rows from the conv-0 60-slice
  + 10 recall-guard questions v6 answered correctly (cat1/2/3) — the guard
  detects a dial turned too far into abstention.
- Arms = BASE ANSWER_SYS + one clause:
  - `evreq` — evidence rule: an answer must point to a specific entry
    (value+date); adjacent facts get "Memory only records X; it does not
    answer Y."
  - `presup` — presupposition check: if the question assumes something with
    no record, say it's not recorded instead of answering a related question.
  - `hedge` — bounded hedges: give the recorded part + flag the unrecorded
    part; honest partial over confident fabrication.
  - `evhedge` — evreq clause + hedge clause combined (4th arm, added after
    seeing evreq win the first three).
- Judge: OpenRouter stealth model, `judge_one` semantics (cat5 judged as
  abstention-or-not). Baseline: v6 OR-judged on the same 22 rows.

## Results (OR judge)

| arm     | adversarial (12) | guard (10) | total (22) | vs v6 |
|---------|------------------|------------|------------|-------|
| v6      | 7/12 = 58.3%     | 10/10      | 17/22 = 77.3% | —     |
| evreq   | 10/12 = 83.3%    | 7/10       | 17/22 = 77.3% | +25pp adv / −3 guard |
| presup  | 10/12 = 83.3%    | 6/10       | 16/22 = 72.7% | +25pp adv / −4 guard |
| hedge   | 10/12 = 83.3%    | 6/10       | 16/22 = 72.7% | +25pp adv / −4 guard |
| evhedge | (OR judge unavailable — pool exhausted; see Atria layer) | | | |

### Per-question deltas (cat5)

FIXED by all three single-clause arms: **q157, q159, q161** (v6 confab →
correct abstention). `evreq`/`presup` additionally fix **q163**. Only
`q152` regressed under evreq/presup (v6 correct-abstain → answered); hedge
kept it. `q156` stays wrong everywhere — the memory genuinely contains
positive-adoption records, a prompt clause can't fix that one.

### Guard-regression anatomy (the real cost)

- **Precise-date substitution** (q8, q9): v6's vaguer "week before June 9"
  passed; arms' tighter answers ("on June 2") got judged wrong — same fact,
  different granularity, judge-borderline.
- **Counterfactual over-abstention** (q14, all arms): "would Caroline still
  want counseling without support?" — gold wants inference ("likely no");
  every arm refused to infer.
- **q3** (all arms): picked "career options" over "adoption agencies" —
  a retrieval-slice artifact, not an abstention failure.
- `presup` q5: answer identical to v6's judged-yes — pure judge noise.

## Winner

**`evreq`** — same adv lift as the others (+25pp, 10/12 incl. q163) with the
smallest guard cost (7/10, and 2 of its 3 losses are judge-borderline date
granularity). Recommendation: ship the EVIDENCE RULE clause into ANSWER_SYS;
the residual guard cost is mostly the judge penalizing precise-date answers,
not true failures.

### ANSWER_SYS diff (winner)

```diff
   - Abstain ONLY if nothing is remotely relevant; then say exactly:
     "I don't have enough information to answer that."
   - Answer concisely, no preamble.
+
+  - EVIDENCE RULE: before asserting an answer, you must be able to point
+    to a specific memory entry (a value plus its date) that supports it.
+    If memory only supports adjacent facts — not the specific thing asked —
+    say exactly "Memory only records X; it does not answer Y."
+    Never present adjacent facts as the answer.
```

## Cross-judge layer (Atria-Dawn-Preview judge)

The OR free-tier daily pool (1000 req/day, account-level) exhausted mid-round;
all four arms plus the v6 baseline were re-judged on Atria-Dawn-Preview for
an internally consistent second layer. Atria is a *stricter* judge — it marks
some "Memory only records X" abstention-forms and hedged partials `no` that
OR accepted, so guard-side numbers drop across the board. The adv ranking is
what matters and it is stable:

| arm     | adv (12) | guard (10) | total (22) | vs v6 (Atria) |
|---------|----------|------------|------------|---------------|
| v6      | 7/12 = 58.3%  | 7/10  | 14/22 = 63.6% | — |
| evreq   | **10/12 = 83.3%** | 5/10 | **15/22 = 68.2%** | +25pp adv / −2 guard |
| presup  | 10/12 = 83.3% | 4/10  | 14/22 = 63.6% | +25pp adv / −3 guard |
| hedge   | 9/12 = 75.0%  | 5/10   | 14/22 = 63.6% | +17pp adv / −2 guard |
| evhedge | 8/12 = 66.7%  | 5/10   | 13/22 = 59.1% | +8pp adv / −2 guard |

Cross-judge read:
- **evreq's adv precision is judge-robust** — 83.3% under both OR and Atria,
  the only arm that beats v6's total under the strict judge.
- **Adding the hedge clause backfires under strict judging** — evhedge drops
  to 66.7% adv: vaguer "recorded part + flagged gap" responses are less often
  credited as abstentions than evreq's clean "Memory only records X" form.
- Guard losses widen under Atria for every arm (v6 also loses 3) — consistent
  with a stricter judge on date-granularity and hedged answers, not an
  arm-specific defect.

## Caveats / costs

- ~340 OR calls for the dial proper + ~110 Atria judge calls; OR pool now
  exhausted again (next reset 2026-09-30 00:00 UTC).
- Ingest nondeterminism: arm ingests produced 593 vs 720 records across runs —
  same code, LLM extract variance. Adv deltas are consistent enough to trust
  directionally; single-question deltas carry judge+ingest noise.
- `evhedge` needs an OR-judge pass after the 00:00 UTC reset for a same-judge
  comparison against the other three arms.
