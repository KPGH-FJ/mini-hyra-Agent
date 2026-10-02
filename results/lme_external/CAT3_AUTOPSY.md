# cat3 autopsy — 62 judged-wrong questions, per-question lesion attribution

Corpus: all cat3 losses from the LoCoMo-10 final-stack run (`locomo_final_c{0..9}.jsonl`, PR #81). 62 rows = 38 refusals (ABSENT/SPLICED) + 23 answered-wrong + 1 ERROR. Each attributed to one lesion layer with transcript/snapshot evidence. **Verdict up front: the largest slice is NOT multi-hop reasoning breaking — it's two benchmark-property classes (external-knowledge golds, open-ended judge strictness) covering ~60% of losses. The real stack lesions are ~28%: gate treats inference questions as adversarial (~14 rows) + unresolved temporal anchors (~3 rows) + image-channel gap (~1).**

## Lesion clusters

### L1 — External-knowledge-fill (~20 rows, ~32%): gold entity never named in the dialogue
The gold answer is a *name* that never occurs in the conversation text; answering requires world knowledge or resolving an indirect description. The stack's records-only gate correctly sees nothing to bind — these are arguably *right* refusals measured as losses.

| q | gold | evidence |
|---|------|----------|
| c3_q73 | Indiana | "Indiana" 0 hits in conv-3 transcript |
| c3_q87 | Florida | "florida" 0 hits |
| c5_q43 | Minnesota | 0 hits |
| c5_q44 | Voyageurs National Park | 0 hits |
| c6_q6/q7 | Connecticut ×2 | 0 hits |
| c6_q16 | UNO | card game described, name never said; only an unrelated img_url token |
| c6_q17 | Mafia | "imposter" 0 hits; described not named |
| c7_q75 | Exploding Kittens | transcript: "a card game about cats, take cards one by one" — named nowhere |
| c6_q30 | Canada (July 2022) | "canada" 0 hits in conv-6 |
| c7_q28 | Colombia | only in an **image `query` field** ("colombian yoga studio…") — never in dialogue text |
| c7_q48 | Alaska | 0 hits |
| c8_q57 | California | 0 hits |
| c6_q0 | obesity | 0 hits — inference from weight/diet descriptions |
| c3_q14 | nickname "Jo" | name never used in text |
| c3_q85 | filmmaker | soft inference from film-festival submissions |
| c3_q60 | Nintendo Switch | records have "Xenoblade Chronicles" verbatim — gold itself justifies via world knowledge ("Xenoblade 2 is made for this console") |
| c4_q27 | Pomodoro | 0 hits — technique never named |
| c4_q28 | John Williams | 0 hits — Tim plays film themes, composer never named |
| c4_q32 | California or Florida | records: "tim is planning a trip to universal studios" — states require external geography of Universal parks |
| c4_q70 | SW Ireland filming locations | pure external knowledge |

### L4 — Open-ended inference, judge-strict (~18 rows, ~29%)
"Would/might/could X" questions whose gold is one of several defensible answers. Two sub-classes:

**(a) semantic match scored wrong (~6)**: the response leans the gold's direction without committing the token form.
- c2_q45 "Would John be open to moving to another country?" — response "deeply rooted in his community… running for local office… [US] goals" = gold "no, goals specifically in the U.S." — scored wrong.
- c0_q81 "move back to home country?" — "only records moved from Sweden 4 years ago" — implies no; gold "no; she's adopting children" — scored wrong.
- c0_q14/q27/q59/q77: same pattern (hedged lean-correct or records-only statement implying the gold direction).

**(b) different-but-valid (~12)**: model's recommendation is defensible and record-grounded, judge credits only the gold.
- c4_q5 Strand vs House of MinaLima; c4_q66 Star Wars: Thrawn vs Jedi Apprentice (both real SW books); c5_q53 wildlife biologist vs park ranger (near-equivalent); c4_q34 endorsements vs coaching; c4_q51 generic strength-yoga vs "Hatha"; c5_q19 hide-and-seek vs cooking dog treats; c5_q52 fold-into-hikes vs bird feeder; c5_q33 nature-escape plan vs hybrid job; c8_q20 ginger snaps/snack box vs cookbook/meal-service; c3_q66 writing/screenwriting vs zookeeper; c4_q19 described the org functionally vs its name (and "good sports" appears in transcript only as a *generic phrase* — "access to good sports programs" — the gold name is itself an external fill).
- c4_q53 yoga vs sprinting/running/boxing — model picked a record-attested activity; gold lists unrecorded ones → boundary between (b) and L1.

### L2 — Gate binds too strict on inference questions (~14 rows, ~23%): material in records, refused anyway
The sharpest mechanistic finding: **cat3 inference questions are structurally adversarial-shaped** — the asked fact is *supposed* to not exist literally; the correct move is grounded inference, which the gate preempts.

| q | gold | the record the verifier missed |
|---|------|--------------------------------|
| c4_q8 | Under Armour | "john has always liked under armour and thinks working with them would be cool" — verbatim |
| c4_q15 | John's friend/colleague | "john and anthony went to a charity event and competed" |
| c7_q40 | beach | "favorite nature spots are a park… and a nearby beach with waves" — "nearby" = lives close |
| c5_q20 | chicken | "audrey's favorite recipe is chicken pot pie" + roasted-chicken recipe |
| c7_q36 | ≤30, in school | engineering-school enrollment records |
| c7_q23 | prefers video games | video-game interest records |
| c6_q19 | lonely before Samantha | "only creatures that gave joy are dogs" + active dating records |
| c2_q64 | shelter coordinator/counselor | homeless-shelter volunteering records (soft inference) |
| c2_q41 | beach | beach-photo records (softer) |
| c3_q4 | hairless cats/pigs | fur-allergy records (hairless→no-fur is a one-step inference) |
| c3_q68 | four hikes | hike records exist; needs cross-record counting |
| c3_q84 | setbacks for both | career-setback records for Nate and Joanna |
| c8_q43 | every three months | multiple checkup records with dates — cadence uncomputed |
| c8_q5 | Canada (May) | SPLICED: Canada records bound to Aug only; May road trip was to Banff/Jasper (Canada↦Banff is *also* external geography) |

### L3 — Temporal-anchor ingest lesion (~3 rows, ~5%)
Fact is in records but its time anchor is a *relative phrase* never resolved to the session date — SELF-CONTAINED bullet satisfied in form, not substance.
- **c8_q71** "holiday season coinciding with Evan's wedding" (Christmas): record says `evan got married (on last week)`; session_21 timestamp = **26 Dec 2023** → wedding ≈ Dec 19–26 = Christmas season. "last week" never resolved → inference impossible.
- **c6_q12** "girlfriend during April 2022?" (presumably not): `james met a beautiful girl named samantha` carries **no anchor at all**; session_19 = **10 Aug 2022** → postdates April → negative inference derivable only with the date.
- c8_q5 shares the lesion: `evan went on a trip to canada (on last week)` (said 2023-08-07) — the May-vs-Aug disambiguation depends on the anchor the ingestor left relative.

### L5 — Reasoning miss, material present (~3 rows, ~5%)
- **c9_q4** (meet country): Calvin "tour ends soon → heading to Boston… let's meet up", Dave "catch you when I'm in Boston" — model answered **Japan** (Dave's wish-destination), ignoring the concrete Boston plan. Genuine inference error, not a gate problem.
- c0_q69 (Melanie's traits for Caroline): picked "empathetic/understanding" — attested-adjacent, gold "thoughtful, authentic, driven". Partial miss.
- c2_q8 (financial status): inferred "strain" from car-repair/job-loss records; gold "middle-class or wealthy" — defensible reading either way, judge chose gold.

### L6 — infra (1 row)
- c2_q50 ERROR (persistent Atria truncation).

## So what fixes cat3

1. **Biggest real lesion = L2 (~23%)**: inference questions get adversarial treatment. The gate asks "is the asked fact literally bound?" — for cat3 the right test is "are there records to *ground an inference*?" The assist stage already extracts candidates; an `inference-OK` path (premise_expected=False already exists for advisory questions — cat3 multi-hop questions need the analogous pass with record-grounded answering) would recover most of L2 without touching cat5 defense, since cat5 fakes fail a different test (atoms bound to the wrong owner/record configuration).
2. **L3 is a cheap general fix**: resolve relative anchors ("last week", "next month") to the session's absolute date at ingest; keeps SELF-CONTAINED honest. Also pays off on cat2 temporal questions.
3. **L1 (~32%) + L4 (~29%) are benchmark properties, not lesions**: external-knowledge golds can't be answered from records by design; open-ended judge strictness over-penalizes valid alternatives. If scoring against LoCoMo matters, a records+world-knowledge mode or a lenient "any reasonable answer" rubric would capture most of this — but that's a policy call, not a bug. ~20 of the 62 losses (≈1pp of total) are unrecoverable under a records-only mandate; ~18 more need judge/rubric changes.
4. **Image-channel gap (1 confirmed, likely more)**: `blip_caption`/`query` fields are never ingested (`normalize_turns` keeps only `text`) — c7_q28's Colombia exists only in an image query. If image QA is in scope, captions belong in turns.
5. Not supported by evidence: retrieval two-hop expansion as the primary fix — the material is overwhelmingly *in* the records (only ~1 true retrieval-side gap found); the failures are downstream at the gate/answerer.
