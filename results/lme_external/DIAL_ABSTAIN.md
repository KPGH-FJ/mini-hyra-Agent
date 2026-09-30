# Abstention-precision dial ablation — LoCoMo conv-0

Second fix-stack refinement round. PR #52's relaxed abstention lifted conv-0
33.3%→66.7% but cost adversarial precision (75%→58%: q156/q159/q163 produced
confident-looking answers from adjacent-but-insufficient memories). This
round dials `ANSWER_SYS` only — same ingest, same retrieval — to recover
adversarial precision without re-breaking answerable categories.

## Setup

- Ingest: conv-0 (19 sessions), LLMIngestor twostage, OR stealth/space-bunny-alpha
  (`reasoning.exclude`+`reasoning.max_tokens` bound), 593–720 records per arm run
  (ingest is LLM-stochastic; arms share one ingest each).
- Question set (n=22): all 12 cat5 adversarial rows from the conv-0 60-slice
  + 10 recall-guard questions v6 answered correctly (cat1/2/3) — the guard
  detects a dial turned too far into abstention.
- Arms = BASE ANSWER_SYS + one clause:
  - `evreq` — evidence rule: an answer must point to a specific entry
    (value+date); adjacent facts get "Memory only records X; it does not
    answer Y."
  - `presup` — presupposition check: if the question assumes something with
    no record, say it's not recorded instead of answering a related question.
  - `hedge` — bounded hedges: give the recorded part + flag the unrecorded
    part; honest partial over confident fabrication.
  - `evhedge` — evreq clause + hedge clause combined (4th arm, added after
    seeing evreq win the first three).
- Judge: OpenRouter stealth model, `judge_one` semantics (cat5 judged as
  abstention-or-not). Baseline: v6 OR-judged on the same 22 rows.

## Results (OR judge)

| arm     | adversarial (12) | guard (10) | total (22) | vs v6 |
|---------|------------------|------------|------------|-------|
| v6      | 7/12 = 58.3%     | 10/10      | 17/22 = 77.3% | —     |
| evreq   | 10/12 = 83.3%    | 7/10       | 17/22 = 77.3% | +25pp adv / −3 guard |
| presup  | 10/12 = 83.3%    | 6/10       | 16/22 = 72.7% | +25pp adv / −4 guard |
| hedge   | 10/12 = 83.3%    | 6/10       | 16/22 = 72.7% | +25pp adv / −4 guard |
| evhedge | (OR judge unavailable — pool exhausted; see Atria layer) | | | |

### Per-question deltas (cat5)

FIXED by all three single-clause arms: **q157, q159, q161** (v6 confab →
correct abstention). `evreq`/`presup` additionally fix **q163**. Only
`q152` regressed under evreq/presup (v6 correct-abstain → answered); hedge
kept it. `q156` stays wrong everywhere — the memory genuinely contains
positive-adoption records, a prompt clause can't fix that one.

### Guard-regression anatomy (the real cost)

- **Precise-date substitution** (q8, q9): v6's vaguer "week before June 9"
  passed; arms' tighter answers ("on June 2") got judged wrong — same fact,
  different granularity, judge-borderline.
- **Counterfactual over-abstention** (q14, all arms): "would Caroline still
  want counseling without support?" — gold wants inference ("likely no");
  every arm refused to infer.
- **q3** (all arms): picked "career options" over "adoption agencies" —
  a retrieval-slice artifact, not an abstention failure.
- `presup` q5: answer identical to v6's judged-yes — pure judge noise.

## Winner

**`evreq`** — same adv lift as the others (+25pp, 10/12 incl. q163) with the
smallest guard cost (7/10, and 2 of its 3 losses are judge-borderline date
granularity). Recommendation: ship the EVIDENCE RULE clause into ANSWER_SYS;
the residual guard cost is mostly the judge penalizing precise-date answers,
not true failures.

### ANSWER_SYS diff (winner)

```diff
   - Abstain ONLY if nothing is remotely relevant; then say exactly:
     "I don't have enough information to answer that."
   - Answer concisely, no preamble.
+
+  - EVIDENCE RULE: before asserting an answer, you must be able to point
+    to a specific memory entry (a value plus its date) that supports it.
+    If memory only supports adjacent facts — not the specific thing asked —
+    say exactly "Memory only records X; it does not answer Y."
+    Never present adjacent facts as the answer.
```

## Cross-judge layer (Atria-Dawn-Preview judge)

The OR free-tier daily pool (1000 req/day, account-level) exhausted mid-round;
all four arms plus the v6 baseline were re-judged on Atria-Dawn-Preview for
an internally consistent second layer. Atria is a *stricter* judge — it marks
some "Memory only records X" abstention-forms and hedged partials `no` that
OR accepted, so guard-side numbers drop across the board. The adv ranking is
what matters and it is stable:

| arm     | adv (12) | guard (10) | total (22) | vs v6 (Atria) |
|---------|----------|------------|------------|---------------|
| v6      | 7/12 = 58.3%  | 7/10  | 14/22 = 63.6% | — |
| evreq   | **10/12 = 83.3%** | 5/10 | **15/22 = 68.2%** | +25pp adv / −2 guard |
| presup  | 10/12 = 83.3% | 4/10  | 14/22 = 63.6% | +25pp adv / −3 guard |
| hedge   | 9/12 = 75.0%  | 5/10   | 14/22 = 63.6% | +17pp adv / −2 guard |
| evhedge | 8/12 = 66.7%  | 5/10   | 13/22 = 59.1% | +8pp adv / −2 guard |

Cross-judge read:
- **evreq's adv precision is judge-robust** — 83.3% under both OR and Atria,
  the only arm that beats v6's total under the strict judge.
- **Adding the hedge clause backfires under strict judging** — evhedge drops
  to 66.7% adv: vaguer "recorded part + flagged gap" responses are less often
  credited as abstentions than evreq's clean "Memory only records X" form.
- Guard losses widen under Atria for every arm (v6 also loses 3) — consistent
  with a stricter judge on date-granularity and hedged answers, not an
  arm-specific defect.

## Caveats / costs

- ~340 OR calls for the dial proper + ~110 Atria judge calls; OR pool now
  exhausted again (next reset 2026-09-30 00:00 UTC).
- Ingest nondeterminism: arm ingests produced 593 vs 720 records across runs —
  same code, LLM extract variance. Adv deltas are consistent enough to trust
  directionally; single-question deltas carry judge+ingest noise.
- `evhedge` needs an OR-judge pass after the 00:00 UTC reset for a same-judge
  comparison against the other three arms.

## Merged-stack validation (all-Atria, post-dial)

After the dial, the landed `ANSWER_SYS` (commit ced208e, branch
`devin/1790614556-reader-personal`) = fuzzy-date + granularity + COUNTING +
PERSONALIZATION + EVIDENCE RULE + **SUBJECT CHECK** (the q156-autopsy clause).
This run validates that exact package verbatim — arm `merged` = live
`R.ANSWER_SYS` — on the same 22 questions, with answer+judge both on
Atria-Dawn-Preview (zero OR spend; pool exhausted until 09-30 00:00 UTC).

- Ingest: conv-0 19 sessions via Atria extract → 305 records (vs 593–720 on
  the OR ingests; lighter extract model → sparser memory, noted for caliper).
- Baseline for comparison: `evreq` single clause on the same Atria layer.

| arm    | adv (12) | guard (10) | total (22) |
|--------|----------|------------|------------|
| evreq  | 10/12 = 83.3% | 5/10 | 15/22 = 68.2% |
| merged | 10/12 = 83.3% | 5/10 | 15/22 = 68.2% |

**Aggregate: merged ≡ evreq — SUBJECT CHECK did not drag adversarial
precision or guard abstention.** The composition shifted though:

- FIXED vs evreq: **q152** (evreq's only net regression — clause recovers it
  verbatim: "the records describe Melanie's charity race experience, not
  Caroline's"), q3 (evreq retrieval-slice "Career options" → correct
  "adoption agencies"), q13.
- LOST vs evreq: **q161** (merged asserts "reminds her of art and
  self-expression" where evreq cleanly abstained — a confidence-side
  regression, not subject-related), **q8, q10** (guard over-fire, below).
- q156 still missed under the merged stack — answer asserts Melanie's
  excitement from her *adjacent* family records, the exact anatomy from
  Q156_SUBJECT_BIND.md: hardest swap type, clause doesn't cover "records
  about X exist and partially support the bridge".

### SUBJECT CHECK mechanics (the point of this round)

- cat5: fires on 10/12 — "the records describe **Y**, not X" is now the
  dominant abstention shape (q152/154/155/157/159/160/162/163 + two plain
  "Memory only records" forms). The clause visibly works at model level.
- Guard over-fire ×2 (q8, q10), mechanism identified at data level:
  **Caroline is speaker_a = the user.** Her self-statements ingest as
  `user·slot` lines; the questions name "Caroline". SUBJECT CHECK's rule
  ("a fact may only be attributed to the person its line names") then reads
  `user` ≠ `Caroline` → abstains "records describe you (the user), not
  Caroline". The content was right — q10's response literally contained
  "4 years" — but the attributed-abstention frame scores as a non-answer.
  Fix direction: either ingest names the persona on self-lines
  (`caroline·slot` instead of `user·slot`, and consistently — the same
  persona currently appears as both `caroline (per self)·` and `user·`),
  or ANSWER_SYS bridges "the user is <persona>". Without that, `user·`
  lines are invisible to every question that names the persona.
- probe_subject.py (official clause verbatim, 9-vertex model, Atria):
  **5/5** — subject_swap → "the adoption entries describe Caroline",
  4 controls clean, zero over-kill at small scale. Output in
  `probe_subj_out.txt`.

Cost: 0 OR calls; ~130 Atria calls (ingest ~40 + 22 answers + 22 judge +
probe ~6, plus retry churn under lab#1's shared-key 429 congestion).
OR-judge review pass of the merged arm still queued for the 09-30 reset.

---

## Expanded adversarial coverage — all cat5, conv-0..2 (merged stack, all-Atria)

**Headline: 95/112 = 84.8%** — the n=12 dial slice (83.3%) held up at ~9x scale.
conv-0 is the outlier, and its misses are a different failure mode
(ingest mislabeling, not clause misses).

| conv | speakers | cat5 n | adv_acc | ingest |
|------|----------|--------|---------|--------|
| conv-0 | Caroline/Melanie | 47 | 35/47 = **74.5%** | 336 records, 19/19 ok |
| conv-1 | Jon/Gina | 24 | 22/24 = **91.7%** | 305 records, 19/19 ok |
| conv-2 | John/Maria | 41 | 38/41 = **92.7%** | 410 records, 31 ok + 1 partial |
| **total** | | **112** | **84.8%** | 1051 records, 69/70 sessions |

### Watch item 1: does SUBJECT CHECK catch real subject-swaps?

**Yes — wherever labels tell the truth.** Verbatim rationales:

- c0_q154: "Memory only records that **Caroline's** chosen adoption
  agency helps LGBTQ+ folks with adoption; it doesn't record anything
  about an agency Melanie is considering or whom it supports."
- c0_q180: "Memory only records that Caroline used to go horseback
  riding with her dad … it does not record any activity Melanie used to
  do with her dad."
- c2_q156: "Memory records that Rob invited **John** (his colleague) to
  a beginner's yoga class — not Maria."
- c2_q157: "The only one-year-old child mentioned is **Kyle**, who is
  John's son (per Kyle himself, stated 2023-03-06) — not Maria's."
- c2_q169: "Memory only records Maria's church membership — she joined a
  nearby church on 2023-05-05 … It does not record John joining a
  church."

Attribution-style abstentions are the dominant correct shape — the
clause names the right owner and the wrong subject explicitly.

### Watch item 2: true adv precision at n=112 — and where it still fails

conv-0 wrong-12 decomposition (verbatim responses checked):

- **8 ingest-mislabel subject swaps** — Melanie self-reports landed
  under `user·`/`assistant·`/`son (per self)` labels (EXTRACT_SYS maps
  `about=null` → "the user", both speakers). Reader trusts the labels
  and asserts Melanie's facts as Caroline's: q168-170 (running/shoes),
  q186 (Ed Sheeran — `user·music_tastes`), q191/194/195 (son's accident
  — `son (per self)`), q198 (family camping — `user·…tradition`).
- 1 pure assertion (q161 bowl reminder).
- 1 bridge confab (q156 — Melanie-side family records bridged into an
  adoption answer; the known hard case).
- 2 debatable (q184 piano, q188 transition setback — real Caroline
  content, benchmark ambiguity).

conv-1 wrong-2: c1_q91 "Jon's store" — Jon has a dance studio, the store
is Gina's; model bridged studio→store. c1_q95 confabulated "trophy" for
Gina's contest prize.

conv-2 wrong-3: q162 scope-bridge (John's nature/photography interests
asserted as "art appreciation"); q168 borderline (correct abstention on
faith + listed community actions — judge scored as answer); q186
confabulated "homeless shelter" as Maria's 5K cause.

### Root cause (data-level, not prompt-level)

The labeling gap is symmetric and it poisons the very labels the clauses
read: named speakers' self-reports emit `user·`/`assistant·`/`X (per
self)` labels with no persona name. SUBJECT CHECK can only reject swaps
whose labels expose the true owner (`melanie (per self)·…`) — it cannot
catch swaps the ingest hid under the user side. conv-0 is mislabel-heavy
(74.5%); conv-1/conv-2 emit persona names (`jon·`/`gina·`,
`john·`/`maria·`) and the same stack hits 91.7%/92.7%.

Fix direction (same as the guard over-fire fix): ingest-side persona
naming — self-reports from a named speaker emit `<name>·slot`, never
`user·`/`assistant·`. E.g. EXTRACT_SYS line: "the user is <speaker_a
name>; self-reports get about=<that name>". Prompt-level patching cannot
recover swaps the labels already lied about.

### Ingest ops notes (conv-2 course-correction)

- Terse-JSON nudge on extract prompts ("output the JSON array only, no
  reasoning dump"): kept 31/32 sessions under cap. The unpatched run
  spent ~2h ingesting with one session grinding truncation-retries;
  patched run did 32 sessions in ~85min under the same 429 congestion.
- 600s per-session timeout + halve-body fallback fired once:
  `2023-07-03` (29 turns) → **partial**, +8 records — zero sessions
  lost, zero failed. Truncation was **not** systemic — Atria chain stays
  viable with the nudge.
- Per-session checkpoints (`ingest_c{ci}_progress.json` + model snapshot
  after every session) make kill/restart lossless; `adv_cov.py` resumes
  from done/partial/failed sets.

Cost: 0 OR calls. ~1200 Atria calls total across the three convs
(ingest ~1050 + 112 answers + 112 judges + retry churn).

Files: `adv_merged_c{0,1,2}.jsonl` (hypotheses),
`adv_merged_c{0,1,2}_metrics_atria.json` (judged rows),
`ingest_c{0,1,2}_atria.json` (LifeModel snapshots — reloadable),
`ingest_c2_progress.json` (partial marker), `adv_cov.py` (runner).
Measured HEAD: worktree ced208e + lme.py OR/Atria patch (unchanged
reader.py).

---

## Closing items — audit cost verdict + counterfactual lesions

### 1. audit pass cost verdict — PROMOTED (optional switch)

Measured on conv-0 (19 sessions): stock = 2 calls/session
(extract + merge); audit arm = 3 (+1 audit call ~1.7K tok in /
~530 tok out). Marginal = **exactly +1 call/session ≈ +42K tok/conv
→ +2.1pp** (91.5% vs clause-only 89.4%). Meets the ≤1 call/session
threshold → packaged as `LLMIngestor(audit=True)` second defense,
opt-in; falls back to unaudited records on shape loss or error.
Commit `03ccd0f` on `devin/1790614556-reader-personal` (#52);
smoke-verified under the merged SPEAKER BINDING clause (16 records,
all named sources).

### 2. Counterfactual-inference lesions — clause prototype hit its ceiling

Probe: 10 lesion cat5 questions (audit's remaining c0 misses + c1/c2
non-attribution misses), merged ANSWER_SYS + PRESUPPOSITION CHECK
clause on the same model snapshots. Judged **2/10** — but the rows
decompose into four distinct families:

- **Lexical premise-swap — clause catches it**: c2_q186 ("organize" vs
  recorded "participate" — verbatim: "No record of Maria organizing a
  5K…only records Maria **participating**"), c0_q166 (place-to-create).
- **Benchmark-label artifacts — NOT model failures** (transcript-
  verified): c0_q161 — `caroline|hand_painted_bowl` is a real record
  (session_4: Caroline's friend made it for her 18th birthday,
  "reminds her of art and self-expression" — the answer the model
  gave); c0_q184 — `caroline|guitar_playing` (session_15, acoustic
  guitar, verbatim); c0_q188 — `caroline|hike_bad_experience` (real
  setback). These cat5 labels are wrong: the questions ARE answerable
  and the model answers them correctly. **Re-scored against
  transcript truth, audit's conv-0 precision is ~46/47 (97.9%)** —
  its only true error is q182 below.
- **Spliced/composite premise — clause blind**: c0_q182 splices two
  REAL records across speakers: Melanie's flowers (session_8, painting
  together) + Caroline's neighborhood walk (session_14, rainbow
  sidewalk). Each half is recorded under a different person/event, so
  per-fact premise tests pass — the miss is that the premise parts
  never co-occur in one record. Deepest lesion type found.
- **Detail confabulation / semantic-equivalence bridge — clause
  partial**: c1_q95 invents "trophy" (win recorded, prize object not);
  c2_q162 scopes nature-photography into "art appreciation"; c1_q91
  treats Jon's studio as his "store" — semantic-paraphrase bridges the
  model believes are synonyms.

**Verdict**: passive prompt clauses are exhausted on this surface —
the residual family needs a reader-side *mechanism*, not wording:
a premise-verification step (extract the question's premise parts →
require a single record carrying them → else abstain), or an
audit-style post-read check ("does each asserted detail appear
verbatim in memory?"). Recommend that as the next reader round
rather than a fourth clause.

Files: `presup_probe.py`, `presup_probe.jsonl`,
`presup_probe_metrics_atria.json`; audit cost numbers in
`attr_*` artifacts.

---

## Premise-verification prototype — mechanism beats the clause ceiling

Reader-side stage (`aanswer(premise_check=True)`, `PVERIFY_SYS` +
`_pverify`/`_numbered_records`/`_pv_abstain` in reader.py): decompose
the question's presupposed atoms (who / event / asked-detail), each
must bind to ONE single numbered record — cross-record assembly =
SPLICED, no record = ABSENT, both abstain with an explicit
"records contain A and B but not the combined claim" rationale.
v2 rule: event atoms bind on same-event restatement; the asked-detail
must appear in the bound record's own words (quote required — no
synonym/category/world-knowledge bridge).

**14-question probe, Atria, saved snapshots: 13/14**
| kind | score | detail |
|---|---|---|
| lesions (must abstain) | 6/7 | q182 splice ABSENT; q156 bridge ABSENT (the case no clause ever caught — "no record of Melanie having an adoption process of her own"); q91 store→studio ABSENT (v2 entity-noun rule); q162 art-scope ABSENT; q166/q186 lexical ABSENT/SPLICED. Sole residual: **q95 trophy — the verifier itself bridged "won first place" → "trophy"**; needs a stricter detail check (e.g. two-pass or verbatim-grep gate), not wording. |
| guards (must answer) | 5/5 | zero over-fire: q161 bowl / q184 guitar / q188 setback (v1 over-fired on paraphrase-gap — fixed by event-restatement rule) + q3 adoption-agencies + q10 4-years all answered. The 3 cat5-labeled guards carry gold=None — rows adjudicated against the transcript (answers verify). |
| adv_ctrl (stay abstain) | 2/2 | c1_q79, c2_q152 |

v1 → v2: +1 guard rescued (paraphrase-gap over-fire), +1 lesion caught
(entity-noun store≠studio). Cost: +1 call/question (the verify stage;
fail-open on parse failure) — same marginal economics as the ingest
audit pass. Files: `pv_probe.py`, `pv_probe.jsonl` (+`_v1`),
`pv_probe_metrics_atria.json`, `pv_probe_metrics_atria_adj.json`.
Flagged open: gate-on-all-questions vs adversarial-only — no over-fire
observed at n=14, so gate-all is viable at +1 call/q.

---

## Premise-verification v3.1 — deterministic detail gate + gate-all wired

`PVERIFY_SYS` + `_pverify`/`_pv_gate`/`_numbered_records`/`_pv_abstain`
in reader.py; `aanswer(premise_check=True)`; **gate-all on the
benchmark path**: locomo.py and lme.py answer calls pass
`premise_check=True` (API default stays False). The deterministic gate
layers two hard checks over the verifier's verdict:
- detail atom's claimed `answer_detail` must word-form-match its bound
  record's own text (abstract question-type nouns skipped); on a miss
  it first rebinds to a record that does carry the detail (`rebound`),
  else `detail-not-in-record` → ABSENT;
- event/detail atoms bound under different record owners → SPLICED.

**14-question probe (Atria, saved snapshots): judge-raw 8/14,
transcript-adjudicated 12/14**
| kind | raw | adj | notes |
|---|---|---|---|
| lesions | 4/7 | 6/7 | q182/q156/q162 ABSENT; q91 ABSENT via `detail-not-in-record` ("store" not in studio records); q95 "trophy" = CORRECT ANSWER — session_9 verbatim "one of my trophies" (4th benchmark mislabel found); residual q166/q186 = verifier bound event atoms to semantically-adjacent records (gate can't police lenient bindings). |
| guards | 2/5 | 5/5 | q3 rescued by `rebound` (verifier bound detail to wrong record #; gate repaired instead of abstaining); q161/q184/q188 gold=None mislabels, all transcript-verified correct. |
| adv_ctrl | 2/2 | 2/2 | |

**Eval-integrity finding**: 4 of the 10-item lesion set were cat5
mislabels all along (trophy/bowl/guitar/hike-setback all literally in
transcript). cat5 adversarial precision ceiling < 100% — treat cat5
misses as "not gold-matched", not necessarily "confabulated".

Files: `pv_probe*.jsonl` (v1/v2/v3/final), `pv_probe_metrics_atria.json`,
`pv_probe_metrics_atria_adj.json`. Cost: +1 call/question (verify);
fail-open on parse failure.

## Premise-on OR-judged full-coverage pass — 112 cat5, conv-0..2

Same stock-ingest snapshots as the merged arm (reader-side verify is
the only delta); answers on Atria, **both arms re-judged by OR
stealth** (`pv112.py --judge`) so the comparison sits under one judge.

**Strict OR-judged: premise_on 101/112 = 90.2% vs merged 96/112 =
85.7% → +4.5pp under the same judge.** Baselines held: merged arm was
83.3% (22q) / 84.8% (112q) under Atria — OR reads it at 85.7%, and
premise_on does not lose precision under the OR judge, it gains.

Adjudicated layer (transcript-forensic per row):
| | OR-strict | adjudicated |
|---|---|---|
| premise_on | 90.2% | **94.6%** (106/112) |
| merged | 85.7% | 89.3% (100/112) |

pv112's 11 OR-judged misses decompose to: 4 benchmark mislabels
(q161 bowl="art and self-expression" verbatim, q184 piano, q188
breakup, c1_q95 trophy — all transcript-confirmed correct answers),
1 judge-borderline on a correct abstain (q167: B&W bowl is Melanie's,
SPLICED-abstain marked wrong while merged's "No—Melanie made it" was
marked right — abstain-phrasing variance), 1 false abstain on an
answerable question (q178 — see the autopsy below: Oscar IS ingested
with correct attribution; the miss was an under-informative ABSENT,
not a recall gap),
4 real who-swap confabulations (q189/q192/q194/q195: the
painting-to-keep-busy / accident / scared kids / life-is-precious
records all belong to **Melanie**, attributed to Caroline), and 1
premise-nuance hedge (c2_q186: Maria *participated in* the 5K for a
homeless shelter; John *organized* a different 5K for veterans —
response surfaced the caveat but still answered).

Flip detail (same-judge): premise_on **fixed 9** — including
**q156, the canonical unfixable subject-swap** (Melanie-friend's
adoption bridged onto Caroline for three straight rounds; verify
bound the who-atom to Melanie's records, found no adoption event,
ABSENT). Lost 4: q167+q178 (abstain-side, above) and q189+q192
(who-swap confab, below).

**Who-swap residual is a snapshot-label artifact, not a gate
failure**: pv112 ran on *stock* ingest snapshots whose records carry
generic `user·`/`assistant·` owners, so `_pv_gate`'s cross-owner check
sees a single owner and cannot fire. Probe on the audit-ingest
snapshot (`attr_audit_c0_atria.json`, named `caroline·`/`melanie·`
labels) with `premise_check=True`: q189/q192/q194/q195 → **all four
clean ABSENT with correct attribution** ("no record of Caroline's
children"). Combined stack (audit/bind ingest + premise_check)
removes the entire remaining confabulation class observed in this
pass.

Files: `pv112.py`, `pv112.jsonl` (verdicts+atoms per question),
`pv112_metrics_or.json`, `adv_merged_metrics_or.json` (same-judge
merged re-score).

## Ingest-recall autopsy (conv-0 s13/s17/s18) + SUBJECT-bullet arm

Ordered task: line-by-line said-vs-stored accounting on the q178
session plus the q189/q192/q194/q195 sessions, then an EXTRACT_SYS
"named entity + attribute coverage" bullet arm on the same sessions.

**q178 premise correction (second falsification of a recall-gap
hypothesis).** Oscar is *not* missing from ingest: the stock conv-0
snapshot carries `self|caroline|pets` "Has a guinea pig named Oscar"
**and** `self|oscar|oscar_favorite_food`, both correctly attributed
(session_13, Caroline: "yup, I do- Oscar, my guinea pig"). The
question ("Is Oscar Melanie's pet?") is a subject swap; pv112's
ABSENT was semantically correct — its only defect was being
uninformative (no true-owner pointer), which made it judge-fragile
(see noise finding below). **No recall gap existed here.**

**Coverage accounting** on the three implicated sessions (s13
roadtrip accident/pottery injury, s17 adoption/friend/painting, s18
support network): ~38/40 spoken entities+attributes land in records
(~95%). The systematic defect is **subject binding**, not coverage —
~5 records in these sessions carry possessive-pronoun values with
topic-owner keys: `self|son|son_accident` = "Her son got into an
accident", `self|kids|kids_accident_reaction`, `self|friend|friend_
adoption`, `self|pottery_injury_break`, `self|accident_fear`. The
person vanished from both key and value; the verifier binds
"Caroline's son" to name-free records, and `_pv_gate`'s cross-owner
check sees only topic owners. All 4 who-swap confabs bound on
exactly these records.

**Arms** (Atria, package EXTRACT_SYS vs +SUBJECT bullet):

| metric | A = package (SPEAKER BINDING) | B = +SUBJECT bullet |
|---|---|---|
| records (s13/s17/s18) | 22 / 19 / 7 = 48 | 23 / 24 / 8 = 55 |
| topic/pseudo-entity `about` | 3 (friend, melanie_s_son, melanie_s_kids) | 1 (melanie_s_buddy) |
| leading-pronoun values | 3 ("Her buddy", "Her art", "Her kids") | **0** |
| extra coverage | — | +adoption_consideration, grand_canyon, support splits; no junk records |

`SUBJECT_BULLET` (tested): *"a fact whose grammatical subject is a
possessive pronoun (\"her son\", \"my kids\", \"his dog\") belongs to
the SPEAKER — about=null, never about=\"son\"/\"kids\"/an object noun.
Resolve the pronoun inside the value so it names the speaker."*

Verdict: recommend adding the bullet to EXTRACT_SYS — it removes the
residual pronoun-value surface (the who-swap binding substrate) and
helps verbatim-grep readers; cost is +15% records, all meaningful.
Pending parent sign-off before it lands in `ingest_llm.py`.

**Deviating from the ordered arm, honestly**: the literal
"coverage" bullet would only recover ~1 marginal item
(Melanie-considering-adoption); coverage was never the lesion. The
SUBJECT bullet targets the lesion the accounting actually found.

## Informative-abstention arm + an OR-judge noise correction

Mechanism (PR #64): `_pv_abstain(verify, records, model)` — when the
asked entity is recorded under a different owner, the refusal names
it (pool = full `hist`, needed because the true-owner key isn't in
the retrieved listing); SPLICED found-parts are annotated with their
bound record's owner.

Probe results (`info_abstain_probe.py`, `info_abstain.jsonl`):
- q178 → "Memory has no record of the pet being Oscar; **Oscar is
  recorded under caroline: 'Has a guinea pig named Oscar who has
  been great'**, so it does not answer the question." — OR judge
  3/3 yes.
- q167 → "…made a black and white bowl **(recorded under melanie)**…"
  — 3/3 yes.
- Controls: q152 / c2_q152 clean abstains emit no note; c1_q95 and
  c2_q186 verdicts unchanged.

**Judge-noise correction to the earlier claim**: re-judging the
*bare* phrasings 3× each gives 3/3 yes too — the single-draw 'no's
that motivated this arm (and the q167/q178 "phrasing sensitivity"
reported above) were OR-judge draws on borderline abstain rows
(~1/3 no-rate per draw), **not** phrasing sensitivity. The arm's
confirmed value is correction info inside refusals — useful to users
and softer judges — not a demonstrated acceptance flip. Treat any
single-draw judge flip on abstain rows as noise until replicated 3×.

Files: `recall_ab.py`, `recall_ab.json`, `info_abstain_probe.py`,
`info_abstain.jsonl`.

## Self-sufficiency bullet verification (lab#1 phase-1 text, cross-benchmark)

Arm C: package `EXTRACT_SYS` + lab#1's SELF-CONTAINED RECORDS bullet
verbatim ("named subject + complete fact + temporal anchor inline;
no bare values; no split-date vertices"). Re-extracted conv-0
s13/s17/s18 — record-form check only, no scoring
(`selfcontained_ab.py`, `selfcontained_ab.json`).

**Verdict: the bullet repairs the lesion where it matters — the
record VALUE — and leaves a cosmetic residue in `about` keys.**

| | A_stock (same-run control) | C_selfcontained |
|---|---|---|
| s13 recs / topic-about / pronoun-only | 21 / 0 / 0 | 22 / 0 / 0 |
| s17 recs / topic-about / pronoun-only | 15 / 1 / 1 | 16 / 1 / **0** |
| s18 recs / topic-about / pronoun-only | 11 / 0 / **4** | 8 / 1 / **0** |

- The who-swap substrate is gone at value level: "Her son got into
  an accident" → "**Melanie's** son got into an accident during the
  family roadtrip"; "Her kids give her the strength" → "Melanie
  wishes she were as resilient as her kids"; "Her family enjoyed the
  Grand Canyon" → "Melanie's family went to the Grand Canyon…".
  Zero pronoun-only values in all three sessions (vs 4 in A_stock).
- Residual: `about` still emits topic nouns in 2 records
  (`melanie|son|son_accident`, `melanie|buddy|friend_adoption`) —
  the bullet constrains record *content*, not the `about` field,
  exactly as predicted. Harmless in practice: the vertex owner is
  still `melanie`, and the now-named value lets the verifier bind
  "Caroline's son" correctly instead of freely.
- vs. my SUBJECT bullet (Arm B): B additionally disciplines `about`
  (0 topic-about). C covers the failure class; B is marginally
  cleaner on key semantics. Either fixes the lesion; B⊂C on values,
  C⊄B on `about` — a one-line `about` discipline note inside the
  self-contained bullet would get both.
- Extraction is non-deterministic: A_stock counts differ across runs
  (22/19/7 vs 21/15/11) — comparisons are within-run only.

## Self-sufficiency deterministic post-check (diagnostic prototype)

`selfcheck.py`: per-record lint — `no_subject`/`bare_fragment`
(no name + no self-marker; +no verb = fragment), `temporal_unanchored`
(temporal word without "(on …)"), `about_nonperson`, `generic_source`.
Ran on post-bullet products: LoCoMo Arm C records + a fresh
selfcontained-bullet re-extract of lab#1's 3 LME autopsy sessions
(b5ef892d/e831120c/3a704032, raw turns from `data_ms25.json` on
results/m4-decomp-ms; lab#1's own re-extract artifacts weren't
pushed, so this is an independent re-run).

**Residual violation rates (post-bullet):**

| set | recs | clean | flags |
|---|---|---|---|
| LoCoMo s13/s17/s18 (arm C) | 46 | 43 (93.5%) | 2 about_nonperson, 1 temporal ("a while ago") |
| LME b5ef892d (camping) | 111 | 104 (93.7%) | 7 temporal — mostly FP |
| LME e831120c (movies) | 47 | 47 (100%) | 0 |
| LME 3a704032 (plants, the catastrophic session) | 81 | 45 (55.6%) | 30 no_subject, 10 bare_fragment, 6 temporal |

**True residuals vs FP decomposition** (per-flag manual audit):

- TRUE residuals ≈ 5%: concentrated on 3a704032 self-records —
  `basil_plant_location: "balcony"`, `snake_plant_origin: "got from
  sister (on last month)"` (item lives in the KEY not the value —
  L2 residue), `fern_pest_problem: "tiny moving dots crawling…"`,
  `basil_soil_type: "general-purpose potting mix"`,
  `snake_plant_status: "doing great…"`, plus 2 real unanchored
  acquisitions ("bought from a nursery two weeks ago"). The
  previously-catastrophic L2 session still leaks ~10 fragments.
- FP class 1 — assistant imperatives (~30 flags): care-tip records
  are subjectless *by genre* ("choose pot 1-2 sizes larger",
  "mist 2-3 times per week") — `no_subject` should only fire on
  `self|*` / named-person records; generic advice can't carry a
  person referent. Recommend gating no_subject to self/named-src.
- FP class 2 — month-word collisions: "may take a few weeks",
  "every Saturday from June to October" in generic knowledge —
  need case-sensitive months or capital-required match.
- Edge — "a while ago": fuzzy temporal that cannot be anchored;
  flag informative but shouldn't count as violation.

**Verdict**: self-sufficiency bullet holds at ~95% true-clean; the
residual is real but small and concentrated on the worst historical
session (3a704032). selfcheck is deployable as a snapshot lint NOW;
a repair pass (re-ask on flagged `self|*` records only, or
deterministic merge-fragment-into-parent) would chase ~5% — worth it
only if benchmark deltas justify; recommend lint-first, repair
deferred. Tuning items: gate no_subject to self-records,
case-sensitive months, allow-list fuzzy temporals.

Files: `selfcheck.py`, `lme_autopsy_reextract_{qid}.json` (3 files).
