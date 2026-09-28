# M4 retrieval-layer ablation — LongMemEval oracle 72-question stratified sample

- **Setup**: `lme_variants.py run --data longmemeval_oracle.json --per-type 12` — same 72 questions as the baseline runs (first 12 per type, `_abs` excluded). GLM-4.5-air extract (thinking off) + answer (thinking on), GLM judge (`--glm judge`, official anscheck prompts).
- **Controlled ablation**: each question is ingested ONCE into a LifeModel (cached export in `models/`), then every variant answers from an identical `import_state` restore — only the retrieval stage differs. Answer-side token/call counts below are per-variant totals over 72 questions.
- **Bugfix carried**: `lme.py judge_one` called a nonexistent `_ask` → every judge row was silently `False`. Fixed to `llm.complete`; all metrics here are post-fix.

## Results (GLM judge)

| variant | acc | Δ vs base | answer tokens | LLM calls | digest |
|---|---|---|---|---|---|
| **pick50** | **47.2%** | **+1.4** | **67.5k** | 72 | 112 KB |
| base (vertex≤25) | 45.8% | — | 74.8k | 77 | 98 KB |
| entity catalog | 45.8% | 0.0 | 71.3k | 72 | 112 KB |
| kwfilter (top-50→LLM) | 44.4% | −1.4 | 72.6k | 77 | 97 KB |
| twohop (pick→expand→refine) | 41.7% | −4.2 | 111.5k | 139 | 44 KB |
| pick10 | 40.3% | −5.6 | 88.1k | 113 | 46 KB |

base reproduces the stated baseline (45.8% = the OR-judged figure; prior GLM-judged v4 was 41.7% — same ballpark, ingest differs).

## by_type (GLM judge, n=12 each)

| type | base | entity | twohop | pick10 | pick50 | kwfilter |
|---|---|---|---|---|---|---|
| temporal-reasoning | 58.3 | 58.3 | 58.3 | 50.0 | 58.3 | 58.3 |
| multi-session | 16.7 | **41.7** | 16.7 | 8.3 | 33.3 | **41.7** |
| knowledge-update | **91.7** | 83.3 | 83.3 | 83.3 | 83.3 | 83.3 |
| single-session-preference | 16.7 | 8.3 | 0.0 | 8.3 | **25.0** | 8.3 |
| single-session-assistant | 16.7 | 16.7 | 16.7 | 16.7 | 16.7 | 16.7 |
| single-session-user | **75.0** | 66.7 | 75.0 | 75.0 | 66.7 | 58.3 |

## Read

- **Winner: pick50** — best accuracy AND fewest tokens/calls. Mechanism: at oracle scale most catalogs are ≤50 vertices, so `max_pick=50` makes retrieval a no-op (fallback renders everything) — it wins by *retrieving less*, i.e. skipping the error-prone LLM pick step when the digest is small anyway.
- **Starving recall loses** (pick10 −5.6) and **over-refining loses** (twohop −4.2 at 2× the tokens): every retrieval step that drops vertices loses answer-bearing history.
- **entity/kwfilter** match base on accuracy at similar cost — no free lunch from coarser catalogs or cheaper prompts.
- Honest caveat: n=72, ±1.4pt is within noise; the robust signal is the monotone direction (more rendered vertices ≥ better) and the call/token savings.
- **Landed**: `reader.aretrieve` default `max_pick` 25 → 50.

## Files

`hyp_<v>.jsonl` — per-question response + per-variant usage + selected vertices + digest bytes. `metrics_<v>.json` — judge output (per-row + by_type). `models/` — cached per-question model exports (664K; re-running any variant skips ingest). `run.log` — driver log. Harness: `tasks/life_model/external/lme_variants.py`.
