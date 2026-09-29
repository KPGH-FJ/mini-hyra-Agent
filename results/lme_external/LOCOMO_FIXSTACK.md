# LoCoMo fix-stack re-validation — OR runner, conv-0 60QA + conv-1 47QA

**Scored HEAD**: `devin/1790614556-reader-personal` @ e97ae84 — the PR #52
fix stack (reader personalization clause, ingest empty-extract retry +
fuzzy `(on June 2023)` event-date verbatim, locomo cat4/cat5 semantics
fix). Fix stack was NOT yet merged to main at run time.
**Runner**: OpenRouter `stealth/space-bunny-alpha` for ingest + answer +
judge — GLM-4.5-air was quota-dead (HTTP 1113 balance exhausted).
**Judge**: OR anscheck, cat5 judged abstention-aware.
**Baselines**: v5 = pre-fix `hyp_locomo_p12.jsonl` (GLM ingest+answer),
OR-judged → `metrics_locomo_c0_v5_or.json`.

> Layer note: "before" is GLM-pipeline hypotheses judged by OR; "after"
> is OR-pipeline on the fix stack judged by the same OR. Cross-model —
> per-question flags are directional, not a clean A/B. GLM same-slice
> reconciliation is deferred until GLM balance is restored.

## 1. conv-0 — before → after (same 60-question slice, OR judge)

| category | v5 acc | v6 acc | v5 abstain | v6 abstain |
|---|---|---|---|---|
| multi-hop | 3/12 (25%) | 8/12 (67%) | 4/12 | 0/12 |
| temporal | 0/12 (0%) | 7/12 (58%) | 9/12 | 2/12 |
| single-hop | 4/12 (33%) | 10/12 (83%) | 8/12 | 1/12 |
| open-domain | 4/12 (33%) | 8/12 (67%) | 6/12 | 1/12 |
| **adversarial** | **9/12 (75%)** | **7/12 (58%)** | 9/12 | 5/12 |
| **overall** | **33.3%** | **66.7%** | 60% | 15% |

Headline: total accuracy doubles (0.333 → 0.667, +33.4pp); aggregate
abstention collapses 60% → 15%.

## 2. conv-1 — unseen-conversation control (OR judge)

| category | acc | abstain |
|---|---|---|
| multi-hop | 5/11 (45%) | 1/11 |
| temporal | 10/12 (83%) | 0/12 |
| open-domain | 6/12 (50%) | 1/12 |
| adversarial | 6/12 (50%) | 6/12 |
| **overall** | **57.4%** (n=47) | ~8.5% |

conv-1's QA slice has no cat3 (single-hop) rows. Temporal is the
strongest family here (83%) — same fix-stack effect on a conversation
the pipeline had never seen.

## 3. Reconciliation — what the fix stack bought, what it cost

Full per-question dump: `locomo_recon.txt` (qid, gold, v5 resp, v6 resp,
FIXED/REGRESSED/SAME flag per judge verdict).

**cat2 temporal — 7 FIXED / 5 SAME-F / 0 REGRESSED.** The fuzzy
`(on <month year>)` verbatim + relaxed abstention rescued exactly the
gold shape it targeted: "The week before 9 June 2023", "June 2023",
"the sunday before 25 May 2023" are now produced instead of abstained.
Remaining 5 fails: 2 still abstain (c0_q12 "10 years ago" birthday —
no session covers it; c0_q21 picnic week), q0/q20 off-by-one-day errors,
q1 wrong year entirely (said 2023, gold 2022).

**cat5 adversarial — 7 SAME-T / 3 SAME-F / 1 FIXED / 3 REGRESSED.**
This is the relaxed-abstention cost surface: q156/q159/q163 abstained
correctly under v5 but now emit grounded-*looking* answers (e.g.
"counseling services focused on trans people" for a never-discussed
counseling question). Counterpoint: the abstention judge accepted
several hedged non-answers as correct (q152/q155 — asserts "no record
of X, but related Y"), and q162 flipped FIXED (v5 hallucinated a
camping list; v6 correctly abstains). Net adversarial −17pp is the
honest price of the 60%→15% abstention collapse.

## 4. Run notes / caveats

- **GLM is down hard**: HTTP 1113 balance-exhausted (not rate limit) —
  needs recharge. All numbers here are OR-only.
- **OR reasoning params mattered enormously**: `stealth/space-bunny-alpha`
  burns the entire token cap on hidden reasoning for large prompts.
  Harness patch in `lme.py` (`_make_llm` + `GLMCompat`): OR calls route
  through GLMCompat with `reasoning.exclude=true` + `reasoning.max_tokens`
  =1024 on non-thinking calls, `effort:low` on answer calls, empty-
  completion → output-cap escalation (8192→65536), 300s timeout,
  retry backoff ×8 cap 120s. Result: conv-0 (19-session ingest + 60
  answers) finished in ~14min with **0 ingest failures / 0 answer
  errors**; earlier unpatched run burned >2h on ingest alone.
- OR `effort` and `reasoning.max_tokens` are **mutually exclusive** —
  sending both returns 400 (burned one batch of 4 answers before
  catching this).
- OR account free-tier daily pool (1000 req/day) was exhausted mid-day
  by failed-run retries; final run executed after the 00:00 UTC reset.
  Total chain consumption ≈ 340 calls (c0 ingest ~60 + 60 answers +
  c1 ingest ~45 + 47 answers + 107 judge calls).
- conv-1 `--api-key` ordering: argparse top-level args must precede the
  `judge` subcommand (first judge invocation failed on this; rerun
  manually with correct order).

## Artifacts

- `hyp_locomo_c0_or.jsonl` (60 rows) / `hyp_locomo_c1_or.jsonl` (47 rows)
- `metrics_locomo_c0_or.json` / `metrics_locomo_c1_or.json` (OR judge,
  per-row verdicts)
- `hyp_locomo_p12.jsonl` (v5 GLM hyp) + `metrics_locomo_c0_v5_or.json`
  (same-slice OR baseline)
- `run_locomo_conv.py` (conv-scoped runner), `compare_locomo.py`
  (before/after + reconciliation), `locomo_recon.txt` (full dump)
- `lme.py` harness patch (OR reasoning params + cap ladder + backoff)
