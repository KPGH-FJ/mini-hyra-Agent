# Yield-guard verification (ss-assist A-lesion re-ingest)

Parent task: arm_zero (zero-assistant-yield top-up) + arm_parity
(arm_zero + sibling-record coverage check), re-ingest the 5
A-lesion questions (1d4da289 / 89527b6b / 58470ed2 + the two empty
stubs 6ae235be / 8752c811), re-answer on both channels, flip vs the
flat baseline where all 5 were wrong.

Selfc extraction stack (bullet re-applied; the mainstack shadow
predates #65). Atria throughout.

## Scores on the 5 lesion questions

| arm | assist channel | profile channel |
|---|---|---|
| flat baseline | 0/5 | 0/5 |
| arm_zero | 4/5 | 3/5 |
| arm_parity | **5/5** | **5/5** |

## Guard evidence (per-session triggers — the causality ledger)

| qid | sessions | zero_trigger | parity_trigger | rescued by |
|---|---|---|---|---|
| 1d4da289 | 1 | **YES** (both arms: +16/+14 assistant recs) | — | **guard** |
| 89527b6b | 1 | no (9 assistant recs existed) | no | re-extract luck |
| 58470ed2 | 1 | no | no | re-extract luck (parity run kept the quote: 10 vs 5 recs) |
| 6ae235be | 1 | no | no | stub self-heal (23 recs this time) |
| 8752c811 | 1 | no | no | stub self-heal (101 recs this time) |

**Causal accounting**: the guard fired exactly once across 10 arm-runs
— on 1d4da289's whole-turn-drop session, precisely the failure mode it
was built for, and rescued it on both channels in both arms (+16/+14
assistant records carrying biometric/OTP). **Causal rescue = 1/5.**
The other 4 rescues are re-extraction variance: same sessions, same
prompts, different yields (5 vs 10 recs on 58470ed2 between arms). The
Plesiosaur color and the Borges quote survived *this* decompose by
luck — attribute-level attrition is stochastic per-extract and would
relapse.

**arm_parity heuristic is dead on arrival**: length-ratio sibling check
never fired (Plesiosaur record is ~same length as siblings — the
dropped color is 4 words inside a 150-char record). The 5/5 parity
score is zero's score plus luck; the parity check contributed nothing.
Attribute attrition needs semantic parity (schema-slot comparison), not
string metrics — matching the warned complexity trap.

**Bonus finding**: both empty stubs were transient ingest failures, not
persistent lesions — plain re-ingest produced 23 and 101 records.
Nondeterministic ingest yield is itself worth guarding (a session that
drops to 0 records today may produce 100 tomorrow — or vice versa).

8752c811's one miss on arm_zero/profile is an answer-side count error
("Purpose" vs gold "Sound effects" — miscounted the 27th list item),
not ingest; the parity run answered correctly — channel variance.

## Verdict vs the acceptance bar

Raw: arm_zero recovers 4/5 (assist) ≥ 3/5 — but **mechanism-caused
rescue is 1/5**. Recommend shipping arm_zero anyway on its own merits:
it fires exactly once, precisely, on the catastrophic silent failure
(whole-turn zero yield), costs nothing when quiet, and its rescue is
clean. Attribute-level attrition (4/6 of ss-assist lesions) is a
different disease — stochastic per-extract — for which neither guard
detects; the honest next lever there is extract-side determinism
(seed/temperature or a consistency-merge pass), not answer-side work.

## Artifacts

`results/lme_yieldguard/` — questions.json, guard_ingest.py,
guard_answer.py, arm_{zero,parity}/models/*.json + guard_log.jsonl +
profiles, answers.jsonl, hyp/metrics per arm×channel.
