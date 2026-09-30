# LME Ingest-Fragmentation Test: offline consolidation arm (ms-25, all-Atria)

Round (i): the decisive arm — with retrieval/render fully exonerated
(rounds g+h), the only remaining variable is the ingest content itself.
Same reader (v_base) + same Atria answer/judge on **offline-consolidated**
new-ingest models: per-vertex LLM merge of same-fact/overlapping edges.

## Setup

- `consolidate.py`: for each of the 25 cached new-ingest models, one Atria
  call per model presenting every vertex's dated edges, returning JSON
  `{key: [{val,date,kind}]}` with same-fact edges merged; key-set and
  format validated (0 fallbacks — every model parsed clean).
- Answer arm = plain `v_base` via `lme_variants.py run --variants base`
  on `results/lme_consol/models/` (pre-populated → ingest zero-cost).
- Control = `results/lme_srcfix` base (28%, same slice/judge/reader, only
  the memory differs).

## Results

| arm | accuracy | median recs | total recs |
|---|---|---|---|
| base (new ingest) | 28% (7) | 102 | 2577 |
| **v_consol** | **36% (9)** | **78** | **2042** |

+3 wins (2e6d26dc, 46a3abf7, d23cf73b) / −1 loss (gpt4_59c863d7) vs base.

## The one datapoint that matters

**2e6d26dc is the only model that reached old-stack density (133→52) —
and it flipped to correct.** Its merge examples (from consol_stats.json):

```
self|family_members   7 edges -> 1
  twins Ava and Lily / David / Rachel / Mike / Emma / aunt / Sarah
  -> "aunt; David; Rachel; Mike; Emma; Sarah; twins Ava and Lily"
self|gift_selection   3 -> 1
  twin carriers + diaper cake / personalized blanket / nursery+bath gifts
  -> "twin baby carriers and a diaper cake; a personalized blanket with
      names; additional nursery and bath time gifts"
assistant|baby_store_recommendation  5 -> 1
  Buy Buy Baby / Amazon / Baby Depot / Target / specialty boutiques
  -> one merged list record
```

No information lost — enumeration items were scattered as one-record-per-
item fragments; merge restored single coherent records.

## But the merge is conservative overall

Median 102→78 (−24%); the ~55-rec old-stack target was only reached on
4/25 models (133→52, 82→32, 87→42, 71→29 — of which only the first is a
win; the other three stayed incorrect). Most models compressed only
obvious duplicates (146→138, 108→104, 55→54).

## Verdict

**Directional support, not decisive.** +8pp and the single deep-merged
model flipping correct are the first positive signal in three rounds —
consistent with fragmentation being *part of* the lesion. But:

1. 36% ≪ the ~60+ bar → at this merge depth, fragmentation repair alone
   does not recover the gap.
2. The three other deeply-merged models (32/42/29 recs) still lost —
   density alone isn't sufficient either.
3. Residual candidate: **record content quality** — what the decompose
   step wrote vs what the old stack wrote (context loss, wording
   degradation). Needs per-question record-level diff: same sessions,
   old-ingest records vs new-ingest records side by side.

Recommended next arm (as pre-scribed): record-diff dissection on a
handful of still-failing questions — or a forced deep merge (per-vertex
prompts / merge-until-≤2-edges instruction) to complete the density test.

## Artifacts

- `models/` — 25 consolidated model exports (drop-in cache format).
- `hyp_base.jsonl` + `hyp_consol_dedup.jsonl` (n=25, 0 error rows) —
  answers on consolidated memory.
- `metrics_consol.json`, `judge_consol.log`, `run_h{1,2}.log`,
  `consol{,2}.log`, `consol_stats.json` (per-model densities + 8 merge
  examples), `consolidate.py`.

## Caveats

- n=25, ±12pp batch variance; +8pp is inside noise — the causal signal
  is the deep-merge flip, not the score itself.
- Consolidation prompt ran once per model (cheap); per-vertex prompts
  would merge deeper at ~40× the calls.
- Old-stack ≈55-rec target hit on only 4/25 models.
