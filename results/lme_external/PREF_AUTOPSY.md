# Preference-type autopsy — LongMemEval v5 (150-question stratified slice)

Scope: `single-session-preference`, 25 questions in `hyp_strat150_v5.jsonl`.
Scores: **GLM judge 5/25 (20%)**, **OR judge 12/25 (48%)** — the weakest type
in the slice vs `single-session-user` 68%(GLM). OR–GLM gap is mostly rubric-fit
leniency, not different memory behaviour (see §4).

## 1. Error census (all 25 rows)

| bucket | definition | n (GLM) | qids |
|---|---|---|---|
| 拒答 — extraction lost whole session | `n_records=0` → forced abstain | **5** | 8a2466db, 06878be2, 75832dbd, 35a27287, caf03d32 |
| 拒答 — memory present, reader abstained | `n_records>0`, "I don't have enough information" | **5** | 0edc2aef(27), 32260d93(11), 6b7dfb22(17), 09d032c9(29), d6233ab6(13) |
| 答非所问 — answered, both judges reject | generic answer, preference unused | **3** | 195a1a1b, 38146c39, 75f70248 |
| 偏好部分命中 — GLM rejects / OR accepts | preference partially applied, rubric incomplete | **7** | afdc33df, 54026fce, 1a1907b4, d24813b1, 95228167, b6025781, a89d7624 |
| 抓错偏好 (old value) | stale/superseded preference served | **0** | — |
| 偏好粒度错 (too broad/narrow) | preference stored at wrong granularity | **0** | — |
| GLM-correct | | 5 | 06f04340, 57f827a0, 505af2f5, 1da05512, fca70973 |

Abstention alone = **10/20 GLM errors (50%)**, and **10/13 OR errors (77%)**.

## 2. Replay — where the preference fact actually dies

5 typical wrong questions replayed end-to-end through the production
`LLMIngestor` (twostage=True, GLM `glm-4.5-air`, thinking=disabled for
extract / enabled for answer) + production reader (`aretrieve` → `aanswer`).
Full dumps: `replay_pref_out.txt` (driven by `replay_pref.py`).

| qid | question essence | v5 failure | replay records | pref vertices in catalog | retriever picked them | digest shows them | reader outcome | **dead stage** |
|---|---|---|---|---|---|---|---|---|
| 8a2466db | Premiere-Pro learning resources | recs=0 abstain | **62** | yes (`self\|software_preference=Adobe Premiere Pro`, `feature_interest`×6, `creative_goal`) | yes (23/23) | yes | answered | **extract (transient)** |
| 0edc2aef | hotel for *Miami* trip | 27 recs, abstain | 19 | yes (`trip_destination=Seattle`, `hotel_preference=great view/unique`, `hotel_amenity=rooftop pool,hot tub balcony`) | yes (8/8) | yes | **abstained** | **reader** |
| 38146c39 | "cookies need something extra" | 11 recs, wrong | 26 | yes (`sugar_preference=turbinado richer flavor`, `sugar_type_preference=muscovado`, `nut_preference`, …) | yes (26/26) | yes | **abstained** | **reader** |
| d6233ab6 | attend HS reunion? | 13 recs, abstain | 28 | yes (`high_school_experience=debate team`, `high_school_courses=AP econ`, `social_connections`) | yes (16/16) | yes | **abstained** | **reader** |
| 09d032c9 | phone battery tips | 29 recs, abstain | 13 | yes (`tech_accessories=portable power bank + wireless charging pad`) | yes (13/13) | yes | **abstained** | **reader** |

### What the preference facts look like in the vertices
Extraction is **good**: preference statements land as `source=self`,
`kind=statement`, specific slot names (`sugar_preference`,
`hotel_amenity`, `high_school_experience`), concrete values
(`turbinado sugar adds a richer flavor`). Merge maps were all `{}` —
single-session questions have an empty catalog, so stage-2 merge had
nothing to fold and misrouted nothing. Retrieval selected every
preference vertex (catalogs ≤50 → all returned). **The digest the reader
saw contained the preference explicitly in every single reader-failure
case.**

### Stage attribution over the 20 GLM errors

| stage | errors | share | mechanism |
|---|---|---|---|
| **reader** | **~15/20** | **~75%** | 5 abstain-despite-memory + 3 answered-without-personalizing + ~7 partial-personalization (GLM-false/OR-true) |
| extract | 5/20 | 25% | whole-session extract returned empty/malformed once → `n_records=0` → forced abstain (single-session type has zero redundancy — one bad response kills the question) |
| merge | ~0 | — | no misrouting observed; merge maps empty on these single-session questions |
| retrieve | ~0 | — | catalogs all ≤50 → retriever returned everything; **latent risk** at >50 vertices: nothing guarantees a `pref` vertex survives the ≤50 pick |

## 3. Root cause (reader stage)

`ANSWER_SYS` frames memory as a lookup corpus: answer *only* what memory
supports, else abstain. Preference questions are exactly the class where
the question is generic ("tips for battery life?", "hotel for my Miami
trip?") and memory's job is to **personalize** — the answer isn't in
memory, the *user's taste* is. The reader sees no literal question→fact
match and defaults to abstention. Same mechanism, softer version, in the
7 GLM-false/OR-true rows: it answers but only partially applies the
preference (rubric wants the *specific* prior preference referenced —
e.g. turbinado, the power bank — and a generic list fails it).

The 5 `recs=0` cases are a **transport-robustness** hole, not a design
one: replay produced 19–62 clean records for the same sessions. One
unparseable/empty GLM response during the original run silently yielded
0 records (`_json_list` → `[]`); with `sessions=1` there is no other
session to cover the loss.

## 4. Judge asymmetry note

GLM judge rejects 15/25 vs OR 13/25 — the 7-row gap is all partial
personalization: answers that mention user interests generically pass
OR's rubric-fit judge but fail GLM's official LongMemEval judge, which
requires the response to *reflect the specific stated preference*.
So the OR figure (48%) overstates fixable headroom modestly; under a
stricter judge ~1/3 of preference answers are "close but not specific".

## 5. Fix hypotheses (testable on the same 150-slice, GLM judge)

**H1 — reader personalization clause (expected +6–10 pp on pref).**
Extend `ANSWER_SYS` (or a preference-aware variant of it):
> For advice/recommendation questions, preference, interest and goal
> entries in memory are always in scope — use them to personalize the
> answer even when the question does not restate them. Abstain only
> when memory contains nothing about the topic AND nothing about the
> user's tastes.

Recovers the 5 abstain-despite-memory cases directly and the
partial-personalization rows partially. Predicted pref ≈ 0.50–0.65
(OR judge already shows 0.48 is reachable today).

**H2 — extract retry-on-empty + `pref_` slot convention (expected +4–6 pp on pref).**
(a) `aingest_session`: if `aextract` yields 0 records for a session,
retry the call once before moving on — kills the silent whole-session
loss (5/20 errors).
(b) Convention: preference statements → `source=self` + slot prefix
`pref_*`; retriever then always includes `self|pref_*` vertices in the
digest regardless of the ≤50 pick. Immunizes the latent retrieval gap
and gives the reader an explicit "durable taste" signal to key on for
H1. Both halves are independently A/B-able.

Not supported as fixes: changing merge canon (merge wasn't the failure),
narrowing slots (granularity was correct), dedup of stale preferences
(no update conflicts in this type — zero old-value errors observed).

## 6. LoCoMo cross-check (`hyp_locomo_p12.jsonl`, `--per-type 12`, conv-0, 60 QAs)

`/home/ubuntu/locomo/locomo10.json` was absent on this box; pulled the
canonical file from `snap-research/locomo` (the repo `locomo.py` names).

**Label caveat — `locomo.py`'s CAT dict is swapped vs this file's
semantics.** In `locomo10.json`, category 5 rows carry no `answer`
field (2/446 only) = the adversarial/unanswerable class; category 4 is
the answerable open-domain class (841/841 answered). So the parent's
"cat5 open-domain" slice is empirically cat4 here, and judged-by-type
numbers are reported against the file's real semantics.

| category (file semantics) | n | abstained | judge acc |
|---|---|---|---|
| 1 multi-hop | 12 | 4 | 0.083 |
| 2 temporal | 12 | 9 | 0.000 |
| 3 single-hop | 12 | 8 | 0.250 |
| 4 open-domain *(locomo.py's "adversarial")* | 12 | 6 | 0.250 |
| 5 adversarial/unanswerable *(locomo.py's "open-domain")* | 12 | 9 | 0.000* |

*cat5 has no gold answers to judge against; abstention is the intended
behaviour there, so 9/12 abstentions is not a failure signal.

**Cross-benchmark verdict: same disease, higher dose.** Overall
abstention 36/60 = 60% — including 6/12 on answerable open-domain and
8/12 on single-hop questions where a memory corpus should help. The
reader's "only answer what memory literally supports" default produces
cross-benchmark over-abstention; it is not a LongMemEval-preference
quirk. (Caveat: conv-scoped LoCoMo ingest also stores both speakers via
`about=`, so part of the cat2/3 abstention is retrieval-entity
fragmentation — but 60% overall vs ~40% non-preference abstention in the
LME slice points at the same reader default.)

## 7. Artifacts

- `replay_pref.py` — replay driver (extract → merge-map → catalog → retrieval picks → digest → answer per question)
- `replay_pref_out.txt` — full dumps for the 5 replayed questions
- `hyp_locomo_p12.jsonl` + `metrics_locomo_p12.json` — LoCoMo comparison
- `lme_v.py` — import fix for the post-refactor module layout (`_json_list`/`EXTRACT_SYS` → `lifemodel.ingest_llm`, `ANSWER_SYS`/`_iso`/`render_vertices` → `lifemodel.reader`)
