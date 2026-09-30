# LME-150 full-stack A/B: old-stack vs new-stack (Atria end-to-end)

**Verdict up front: the new stack is a net regression under Atria** — 78.0% vs
84.7% (−6.7pp), driven almost entirely by a multi-session collapse
(28% vs 72%). Every "fix" that won under the OR/GLM era did not transfer.

## Arms

- **old-stack** = `cd37477^` (525e1b9): twostage slot-merge ingest (default since
  34e912a) + pre-fix reader — two-stage `aanswer` (vertex catalog → LLM pick →
  render → answer), `max_pick=50`. i.e. *before* event-dates (cd37477),
  assistant-artifact decompose (6488b85), numbered-edge enumeration (8f0e60e),
  family expansion (#53), three-stage aanswer (#54).
- **new-stack** = `results/m4-answering-agg` tip (9d27d72): all of the above.
- Shadow via `LME_STACK_ROOT=results/oldstack` (lifemodel shadow + hyra symlink).

## Slice & backends

- `results/data_strat150.json` — the same 150-question stratified slice as the
  previous expanded exam (25/type).
- **Ingest + answer + judge all on Atria-Dawn-Preview** (`--answer-backend
  atria`, judge = default OpenAICompatLLM path). Zero `__answer_error__` rows,
  150/150 both arms.
- New arm reused 24 new-stack-era cached models from `lme_agg_ms`,
  `lme_completeness`, `lme_agg_tA` (same post-6488b85 ingest code); old arm had
  no valid-era cache (the earlier 150-q run never persisted models;
  `lme_retrieval/models` is pre-twostage e68ec05-era) and re-ingested all 150.
- **Caliber warning**: the Atria judge is stricter than OR/GLM and the answerer
  is much stronger — absolute numbers are NOT comparable to the 45.3%
  (OR-judged v5) or GLM-era figures. Only arm-vs-arm deltas are meaningful.

## Results (Atria judge, n=150)

| question_type | old | new | Δ |
|---|---|---|---|
| temporal-reasoning | 0.92 | 0.92 | 0.00 |
| multi-session | **0.72** | **0.28** | **−0.44** |
| knowledge-update | 0.96 | 0.92 | −0.04 |
| single-session-preference | 0.84 | 0.84 | 0.00 |
| single-session-assistant | 0.68 | 0.80 | +0.12 |
| single-session-user | 0.96 | 0.92 | −0.04 |
| **OVERALL** | **0.847** | **0.780** | **−0.067** |

## Attribution (per-question flips)

- `multi-session`: 11× old✓→new✗, 0× reverse — the entire regression.
- `single-session-assistant`: 4× old✗→new✓ vs 1× lost — new stack's only real gain.
- `knowledge-update`/`ss-user`/`ss-preference`: ≤2 flips each way — noise at n=25.

Sampled ms losses (old right → new wrong):

- `b5ef892d` (camping days total): old summed 5d Yellowstone + 3d Big Sur = 8;
  new answered 3 — dropped the second trip family even while noting it.
- `e831120c` (MCU+StarWars weeks): old summed both; new counted MCU and
  declared SW "not recorded" — candidate family missing from the extract table.
- `3a704032` (plants acquired): old counted 3 with provenance; new answered 5 —
  duplicate/mention records counted as distinct (over-enumeration).

## Mechanism read (honest)

The three-stage `aanswer` (retrieve → extract {value,date} JSON → deterministic
dedupe/sort/count → answer) was built to take arithmetic away from a weak OR
answerer — and it did (+16pp on OR). Under Atria the answerer is already strong,
so the extra extract+assembly stage only adds error channels: dropped candidate
families (under-count), dedupe-key collisions (over-count), and date-range
misfilters. Meanwhile the new ingest yields ~2.6× more records (median 60.5 vs
23/question) — richer memory helped `ss-assistant` (+0.12) but did not move ms.

This is a stack-level A/B by design: the ms regression is the joint effect of
heavier ingest + the three-stage reader; isolating which half carries it needs a
reader-only arm (old ingest + new reader, or vice versa) — cheap on cached
models if wanted.

## Cost

| arm | cumulative extract tok | answer tok | median recs/q |
|---|---|---|---|
| old | 928k prompt / 725k completion | (in same counters) | 23 |
| new | 721k / 933k* | | 60.5 |

*new-arm counters exclude ingest for the 24 cache-hit questions.

## Artifacts

- `results/reexam150_old/` `results/reexam150_new/`: `hyp_base.jsonl` (150 rows,
  0 errors), `metrics_base.json`, `run.log`, `judge.log`, `models/`
- `results/oldstack/`: the exact old-stack shadow used
- `results/data_strat150.json`: the slice
- Harness: `tasks/life_model/external/lme_variants.py` (Atria backend,
  `LME_STACK_ROOT`, deferral loop)
