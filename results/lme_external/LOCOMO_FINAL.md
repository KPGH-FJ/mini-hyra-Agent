# LoCoMo-10 final-stack full benchmark — 1986 questions

**Stack under test**: current merged ingest (SPEAKER BINDING + SELF-CONTAINED RECORDS + about-discipline, EXTRACT_SYS as of #65) + `aanswer(premise_check="relaxed", assist=True)` — the "final stack" as wired on `tasks/life_model/external/locomo.py:129`. Answer+judge all Atria (`Atria-Dawn-Preview`). Driver: `results/lme_external/locomo_final.py` (3-phase: per-session ingest snapshots → parallel answers → judge).

**Timing note**: run executed on PR-head `05f4199` (#73 was still open at launch); #73 has since merged (`4e3758f`) and `main` is byte-identical at the call site, so these numbers measure what is now on main.

## Scorecard (Atria strict judge, ABS_NOTE on empty golds)

| conv | n | strict | acc | cat1 | cat2 | cat3 | cat4 | cat5 |
|------|-----|--------|-----|------|------|------|------|------|
| c0 | 199 | 129 | 64.8% | 17/32 | 24/37 | 7/13 | 40/70 | 41/47 |
| c1 | 105 | 70 | 66.7% | 5/11 | 20/26 | — | 23/44 | 22/24 |
| c2 | 193 | 124 | 64.3% | 18/31 | 16/27 | 3/8 | 47/86 | 40/41 |
| c3 | 260 | 177 | 68.1% | 17/37 | 26/40 | 1/11 | 76/111 | 57/61 |
| c4 | 242 | 151 | 62.4% | 15/31 | 15/26 | 2/14 | 61/107 | 58/64 |
| c5 | 158 | 107 | 67.7% | 20/30 | 14/24 | 0/7 | 39/62 | 34/35 |
| c6 | 190 | 120 | 63.2% | 8/20 | 17/34 | 4/13 | 52/83 | 39/40 |
| c7 | 239 | 150 | 62.8% | 9/21 | 26/42 | 4/10 | 63/118 | 48/48 |
| c8 | 196 | 115 | 58.7% | 13/37 | 16/33 | 8/13 | 40/73 | 38/40 |
| c9 | 204 | 128 | 62.7% | 15/32 | 16/32 | 5/7 | 48/87 | 44/46 |
| **all** | **1986** | **1271** | **64.0%** | **137/282 (48.6%)** | **190/321 (59.2%)** | **34/96 (35.4%)** | **489/841 (58.1%)** | **421/446 (94.4%)** |

## The headline: defense holds at scale, over-refusal is now the dominant loss

Loss decomposition (715 judged-wrong rows), by whether the row refused or answered:

| cat | losses | refused (ABSENT/SPLICED) | answered wrong | infra (ERROR/empty-verdict) |
|-----|--------|--------------------------|----------------|------------------------------|
| 1 | 145 | 64 | 76 | 5 |
| 2 | 131 | 96 | 31 | 4 |
| 3 | 62 | 38 | 23 | 1 |
| 4 | 352 | 287 | 58 | 7 |
| 5 | 25 | 4 | 20 | 1 |
| **all** | **715** | **489 (68%)** | **208** | **18** |

- **cat5 adversarial precision 94.4%** (421/446) on the full set — up from 84.8% on the conv-0..2 subset and 85.1% on the conv-0 sentinel. The 25 misses: 20 answered-when-should-refuse (includes the ~4 known benchmark mislabels — bowl/trophy-type items whose "wrong" answer is actually in the transcript), 4 refusals the judge scored wrong, 1 infra.
- **68% of all losses are refusals on answerable questions** — not hallucinations. Cross-checking the gold answer's tokens against the conv's own ingest snapshot: ~80% of refused losses had the gold literally present in records (cat4: 271/288). Verified examples: c4_q79 ("john signed a nike deal for basketball shoes and gear" + "in talks with gatorade" both in records → refused), c4_q96 ("harry potter and the philosopher's stone is special to tim" verbatim → refused), c4_q100 ("teammates for four years" verbatim → refused), c3_q96 ("Nate loves action and sci-fi movies" → refused).
- **Mechanism**: the relaxed gate's atom-binding still treats many legitimate questions as unbound/spliced — multi-record answers (q79: two sponsors in two records), paraphrase gaps ("loves action and sci-fi" vs "type of movie he enjoys most"), and ownership mis-binding. The same machinery that yields 94% cat5 precision refuses ~25% of answerable questions. This is the frontier: splice-detection cannot yet distinguish adversarial fake-composites from legitimate multi-fact questions.
- Residual refusal losses without gold in snapshot (~20%, esp. cat2 45/96) are ingest recall gaps (e.g. c3_q92 gaming-room lighting: zero mentions in records).

## Verdict distribution (all 1986)

SUPPORTED 858 · ABSENT 671 · SPLICED 239 · SYNTHESIS_OK 152 · NO_PREMISE 39 · ERROR 20 · unparseable-verify 7.
cat5 alone: ABSENT 321 + SPLICED 98 refusals vs SUPPORTED 21 (the 20 wrong + 1 lucky hit).

## Run integrity / honest caveats

- Ingest: 262/262 sessions terminal, **0 failed, 8 partial** (halved-turns fallback after extract timeout: c3 2022-10-06, c4 2023-10-13, c5 2023-04-02 + 2023-08-24, c7 2023-08-19, c8 2023-12-31, c9 2023-10-25 + 2023-10-29). New `ingest_final_c*` snapshots — old `ingest_c{0,1,2}` snapshots predate the merged ingest bullets and were NOT reused.
- 44 rows hit the 900s answer timeout on first pass (truncation/stream-cut loops); a resume sweep re-answered all — 24 recovered to real verdicts, **20 persistently ERROR** (Atria truncation poison; judged as losses except 5 cat5 rows the judge counted as abstentions — slight cat5 score inflation, noted for honesty). 7 rows have empty verdict (unparseable verify JSON → fail-open answer; 6 scored losses).
- Judge = Atria strict grader + ABS_NOTE when gold empty (convention-consistent with all prior arms). Single-draw judge noise on borderline abstentions ~1/3 — per-row verdicts may wobble on re-judge; aggregates stable.
- cat5 "answered-wrong" includes ≥4 confirmed benchmark mislabels from earlier forensic rounds (the item is genuinely answerable in transcript); true defense-miss count is lower than 20. Transcript-verified mislabels inflate neither the score nor the miss list — they are reported as losses where judged so.

## Data files

`locomo_final_c{0..9}.jsonl` (per-question: qid/category/question/gold/response/verdict/correct), `locomo_final_c{0..9}_metrics_atria.json`, `locomo_final_metrics_atria.json` (aggregate), `ingest_final_c{0..9}.json` + `_progress.json` (snapshots + session status), `locomo_final.py` (driver).
