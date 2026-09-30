# LME Catalog-Crowding Repair Ablation (multi-session-25, all-Atria)

Round (g): three pick-layer repair arms vs base on the new-ingest cache,
all answers and judging on Atria-Dawn-Preview (answerer=judge).

## Setup

- Slice: `results/data_ms150_25.json` — the multi-session 25-question subset
  of strat150 (same questions as the R1/R2 decomposition and the #54 round).
- Ingest cache: `results/lme_catfix/models/` — 25 models copied verbatim from
  `results/reexam150_new/models/` (new-stack ingest; ingest cost = 0, every arm
  sees identical memory).
- Runner: `tasks/life_model/external/lme_variants.py run --variants base famcatalog budget closure`,
  two parallel halves (13+12 qids) on the same out-dir; error rows deduped out
  for judging (`hyp_*_dedup.jsonl`, n=25/arm, 0 error rows).
- Judge: `lme.py judge` with default backend = Atria (`OPENAI_*` env).

## Scores

| arm | accuracy | correct | mechanism-zone (>50 catalog, n=9) | noise-zone (≤50, n=16) |
|---|---|---|---|---|
| base | 28.0% | 7 | 3/9 | 4/16 |
| famcatalog | 36.0% | 9 | 4/9 | 5/16 |
| **budget** | **40.0%** | **10** | **4/9** | **6/16** |
| closure | 32.0% | 8 | 3/9 | 5/16 |

References on the same slice (Atria judge): old-stack 72%, R1 (old ingest +
new reader) 84%, R2/new-stack ≈ 28-32%.

## Instrumentation (from per-question hyp rows)

| arm | median picked | median digest | median records | total tokens |
|---|---|---|---|---|
| base | 25 | 4,186 B | 102 | 118.8k |
| famcatalog | 27 | 3,363 B | 102 | 111.2k |
| budget | 26 | 4,254 B | 102 | 107.9k |
| closure | 32 | 5,183 B | 102 | 123.2k |

closure delivers the designed crowding relief (digest +24%, picked 32 vs 25);
famcatalog/budget barely change digest volume.

## Structural finding that reframes the round

**Every vertex key in all 25 new-ingest models is 2-part `src|slot`** — the
`about` entity domain degenerates to exactly two blocks, `user` and
`assistant` (e.g. 6d550036: 148 keys = 30 user + 118 assistant).
Consequences:

- `famcatalog` presents a 2-block catalog; the LLM picks one or both sides.
  Picked-family → all members = effectively **render-all with a drop risk**
  when only one side is picked — not the intended semantic-family targeting
  (clothing_item/dry_cleaning families live in the *slot* part, which the
  #53 head-prefix expansion already covers).
- `closure`'s same-about closure likewise pulls the whole `user`/`assistant`
  side of picked vertices ≈ half-render-all (hence its +24% digest).
- `budget` is mechanically ≈ base on this slice: `min(len,50)` equals base's
  `max_pick=50`, and on the 16 ≤50-catalog questions both short-circuit to
  render-all. 2 of its 3 extra wins sit in that identical-mechanism zone —
  its headline 40% is sampling/prompt-format noise, not crowding relief.

## Per-question overlap

- `c4a1ceb8` (catalog 67): won by **all three** repair arms, lost by base —
  the single clean mechanism datapoint (wider coverage helped).
- `6d550036` (catalog 148, largest): won only by famcatalog (≈render-all).
- Remaining arm-vs-base diffs all sit on ≤50-catalog questions = noise.

## Verdict

**No validated winner — nothing landed in reader.py.**

1. Nominal winner budget (40%) is a noise artifact: it cannot mechanistically
   differ from base on 16/25 questions and only ties on the 9-question
   mechanism zone.
2. All pick-layer repairs land 32-40% vs the 72-84% old-ingest cell: even
   full-catalog rendering recovers at most +1 net question in the mechanism
   zone. **Pick-layer crowding is refuted as the dominant harm** of the new
   ingest — consistent with the completeness round (big150 render-all also
   failed to win).
3. The residual gap must sit upstream: new ingest produces ~102 median
   records vs old ~55 — denser, more fragmented memory where coverage is not
   the binding constraint. Next lever candidates: ingest-side record
   consolidation/dedup targeting ~old-stack density, or answer-side
   robustness to 100+-record digests.

## Artifacts

- `hyp_{base,famcatalog,budget,closure}.jsonl` (raw, may contain error rows)
  + `hyp_*_dedup.jsonl` (judged, n=25) with `selected`, `digest_bytes`,
  `n_records`, `usage` per row.
- `metrics_*.json` per-arm accuracy + per-question `correct` flags.
- `models/` = copies of `results/reexam150_new/models/` (25/150 questions;
  see that dir for provenance — not re-committed elsewhere).
- `judge_*.log`, `run_h1.log`, `run_h2.log` — run/judge logs.
- Variant implementations: `v_famcatalog`, `v_budget`, `v_closure` in
  `tasks/life_model/external/lme_variants.py` (VARIANTS dict).

## Caveats

- n=25 with documented ±12pp batch variance: ±2-3 question diffs are noise.
- Atria judge is strict; absolute values not comparable to OR/GLM numbers.
- The 9-question mechanism zone is underpowered — a 1-question edge is the
  largest signal available; treat all arm rankings as directional only.
