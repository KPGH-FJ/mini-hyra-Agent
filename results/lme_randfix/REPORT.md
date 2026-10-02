# Extraction-randomness lesion: union2 vs verify_pass (ss-assist-25, Atria)

## Scores

| arm | assist | profile | lesion-5 |
|---|---|---|---|
| flat baseline (guard-era) | 20/25 (.80) | 20/25 (.80) | — |
| union2 | 22/25 (.88) | 22/25 (.88) | 2/5 |
| **verify_pass** | **24/25 (.96)** | **24/25 (.96)** | **4/5** |

verify wins decisively: +16pp over flat, +8pp over union2, on BOTH channels.
Only miss (both arms, both channels): 8752c811 — known answer-side
miscount (Purpose vs Sound-effects 27th item), not an ingest lesion.

## Union2 mechanics — per-pass attrition quantified

- Two independent aextract passes/session (Atria has temperature=0.7
  default, NO seed param — passes are independent samples, no prompt
  perturbation needed).
- Merge: same slot + ≥0.5 value-overlap → keep richer; else keep both.
- Across 25 sessions: pass1=455 recs, pass2=461 recs, union kept
  **+353 records that pass1 lacked** → per-pass attrition ~40-75%:
  each pass samples a different subset of extractable facts.
- BUT union does not fix systematic skips: on 1d4da289 both passes
  dropped the whole assistant turn (3→4 merged, vs verify's 18);
  on 89527b6b both passes dropped the image-color attributes for the
  plesiosaur while keeping siblings (10 recs, color still absent).
- Cost/bloat: +1 call/session, models ~2x record count on healthy
  sessions (c4f10528: 32→66). Extra coverage is churn, not targeted.

## verify_pass mechanics

- One aextract, then audit call: session text + slim record list →
  "list ONLY missed attributes/entities/numbers/quotes".
- 71 found items over 25 sessions (~2.8/session). Types: process/step
  descriptions (refinery methods ×7, security practices ×8), verbatim
  quotes (Library-of-Babel ×5 — the 58470ed2 lesion class), image
  descriptions (Plesiosaur "blue scaly body"), advice/preference items,
  entity facts. All assistant-artifact content — exactly the lesion
  class from the ss-assist attribution.
- Model growth is surgical: c4f10528 +2 recs, but 1d4da289 +14 (the
  whole-turn rescue) — verify scales effort to the actual gap.
- Subsumes yield_guard's function: the audit found the zero-yield
  assistant turn without needing a zero-yield trigger.

## Lesion-5 ledger (vs yield-guard round)

| qid | lesion class | union2 | verify |
|---|---|---|---|
| 1d4da289 | whole-turn-drop | still wrong (both passes skip) | CORRECT (audit found 14 items) |
| 89527b6b | sibling attrition | still wrong (color skipped twice) | CORRECT (audit found image-desc) |
| 58470ed2 | quote loss | correct | correct |
| 6ae235be | transient stub | correct | correct |
| 8752c811 | answer-side miscount | wrong | wrong (95 recs — truly not ingest) |

## Verdict

**verify_pass is the mechanism**: directed gap-finding beats sampling
diversity — random attrition is not random across passes (systematic
skips correlate), so union can't rescue the lesions that matter.
Recommendation: implement as `aextract(verify=True)` switch (+1
call/session, always-on). union2 (aextract(k=)) not worth ×2 ingest —
its gains are churn, its failures are correlated.
