# M1 ingest-frontend variant ablation — LongMemEval oracle, GLM-judged

Harness: `tasks/life_model/external/lme_v.py` (same pipeline as `lme.py`;
variant knobs via env: `LME_THRESH`, `LME_ENTITY`, `LME_GRAIN`,
`LME_TWOSTAGE`, `LME_EXAMPLES`, `LME_CONC`). Data: `longmemeval_oracle.json`,
`--per-type 12` → the same 72-question stratified slice as `hyp_strat72_v3`
(abs-questions excluded). Extractor + answerer + judge all `glm-4.5-air`
(GLM_API_KEY), `thinking` disabled for extract / enabled for answer.

Reference points: lab#1's `metrics_glm_v3.json` = 0.375 on the same slice;
parent-quoted baseline 41.7%.

## Comparison table

| variant | knobs | accuracy | notes |
|---|---|---|---|
| **twostage** | free slots → LLM merge onto catalog | **0.431** | wins temporal .583, multi-session .333, assistant .25 — best overall |
| examples | catalog shown with sample values | 0.403 | best preference .333; multi-session regressed to .083 |
| t05 | thresh 0.5 + entity fold (ingest_llm parity) | 0.389 | parity baseline of the current ingestor |
| noent | thresh 0.5, entity fold OFF | 0.389 | entity folding is neutral at n=12/type |
| stock | lme.py as-is (no local canon, no entity fold) | 0.375 | reproduces lab#1 v3 = 0.375 exactly |
| t03 | thresh 0.3 (loose folding) | 0.361 | over-merging hurts (knowledge-update .667) |
| t07 | thresh 0.7 (strict folding) | 0.347 | under-merging also hurts |
| perturn | per-round extraction (≈3.4× calls/q) | 0.347 | worst value; 748 calls for the run vs ~98 |

## Reads

1. **Two-stage extraction is the only clear win** (+5.6pts over stock,
   +4.2 over parity): free slot minting then an LLM merge pass onto the
   catalog beats single-call forced-reuse — the merge model sees the whole
   session's new names at once instead of committing greedily mid-prompt.
2. **Local `_canon` threshold has a sweet spot at ~0.5** (parity .389 >
   .3 .361 > .7 .347); loose over-folds and strict under-folds.
3. **Entity-name folding is neutral** at this sample size (noent = t05).
4. **Per-round granularity is strictly worse** despite ~3.4× more calls:
   finer calls produce noisier, more fragmented records (perturn avg
   recs/q ≈ 87 vs ≈20 for session grain) which the digest then buries.
5. **Catalog examples help preferences** (the only variant to lift
   single-session-preference to .333) but hurt multi-session — sample
   values may anchor the extractor to stale phrasing.

## Artifacts

`hyp_v_{stock,t05,t03,t07,perturn,noent,twostage,examples}.jsonl` —
per-question responses; `metrics_v_*.json` — GLM judge outputs incl.
per-question rows.

## Recommendation

Adopt **two-stage extraction** as the M1 ingestor default (keep thresh
0.5 local canon as a safety net after the merge, entity fold on — it's
free). Candidate next ablations: merge with examples shown, or per-round
only inside sessions > N turns.
