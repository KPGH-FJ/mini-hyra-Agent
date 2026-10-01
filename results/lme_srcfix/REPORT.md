# LME Source-Dilution Repair Ablation (multi-session-25, all-Atria)

Round (h): three source-aware arms vs base on the new-ingest cache, testing
the "user facts diluted by assistant artifact edges" hypothesis. Assistant
edges = 62.5% of all rendered history across the 25 models (1610 vs 967).

## Setup

- Slice: `results/data_ms150_25.json` (ms-25), all-Atria answer+judge.
- Ingest cache: `results/lme_srcfix/models/` — byte-identical copies of
  `results/lme_catfix/models/` (= `results/reexam150_new/models/` ms subset);
  not re-committed, see that dir for provenance.
- Arms: `srcprior` (partitioned catalog: user block detailed-first,
  assistant keys listed bare), `splitsrc` (base pick then top-up until
  ≥60% of selected vertices are user-source), `tiered` (base pick; user
  vertices render all edges, assistant vertices collapse to
  label+count+first-edge — 0/25 questions were assistant-type so the
  exception never triggered). `splitsrc`/`tiered` share base's `aretrieve`
  picks; only `srcprior` re-prompts the picker.

## Scores

| arm | accuracy | correct | +wins / −losses vs base |
|---|---|---|---|
| base | 28.0% | 7 | — |
| srcprior | 28.0% | 7 | +d682f1a2 / −6d550036 |
| splitsrc | 32.0% | 8 | +{2e6d26dc,3a704032,c4a1ceb8} / −{6d550036,gpt4_59c863d7} |
| tiered | 32.0% | 8 | +{2e6d26dc,46a3abf7,c4a1ceb8} / −{6d550036,gpt4_59c863d7} |

## Dilution verification (per-question medians)

| arm | picked u:a | rendered-edge u:a | user edge share | tokens |
|---|---|---|---|---|
| base | 15:12 | 31:42 | 42% | 105.8k |
| srcprior | 13:12 | 31:42 | 42% | 109.6k |
| splitsrc | 16:12 | 31:42 | 42% | 101.6k |
| tiered | 15:12 | 31:12 | **72%** | 120.9k |

- `srcprior`: partition did not shift picks (LLM already preferred user
  vertices ~55%) — mechanism no-op on this slice.
- `splitsrc`: +1 median user vertex; rendered-edge ratio unchanged
  (assistant vertices carry ~2× the edges, so vertex-quota ≠ edge-quota).
- `tiered`: **the only arm that mechanically de-diluted the digest** —
  assistant edges 42→12, user share 42%→72%.

## Verdict

**No winner — dilution refuted.** The single arm that verifiably removed
assistant-edge dilution (`tiered`, 72% user share) gained only +1 net
question vs base; `splitsrc`/`srcprior` moved picks/digest negligibly and
landed at noise level. Combined with round (g)'s crowding refutation:

- coverage repair (famcatalog/budget/closure): ≤ +1 net real win
- dilution repair (src-aware this round): ≤ +1 net win, *with* the dilution
  actually fixed in the digest

→ the ms 72→28 gap is **not located in the retrieval/render layer at all**.
Across both rounds the residual sits in either ingest content quality
(what the records say, not how many are rendered) or the answer step on
100+-record digests. Recommend: stop iterating pick/render variants;
next levers are (a) ingest-side record consolidation/dedup toward old-stack
~55-rec density (directly comparable cached re-run possible), or
(b) an answer-side arm on identical digests.

## Artifacts

- `hyp_{base,srcprior,splitsrc,tiered}.jsonl` + `*_dedup.jsonl` (judged,
  n=25/arm, 0 error rows) with `selected`/`digest_bytes`/`usage` per row.
- `metrics_*.json`, `judge_*.log`, `run_h1.log`, `run_h2.log`.
- Variants `v_srcprior`/`v_splitsrc`/`v_tiered` in
  `tasks/life_model/external/lme_variants.py`.

## Caveats

- n=25, documented ±12pp batch variance: ±1-2 question diffs = noise.
- Atria judge strict; absolutes not comparable to OR/GLM.
- `tiered`'s edge-share win is measured on rendered lines (assistant
  vertices count 1 edge each post-compression).
