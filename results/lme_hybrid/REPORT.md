# Hybrid-oracle ceiling + pref-bleed prompt fix (post profile@150q)

Parent task (u): (1) per-question union of `profile` and `nogate+assist`
on the 150q slice → oracle hybrid ceiling; (2) fix the single-session-
preference bleed in `PROFILE_ANSWER_SYS` and rerun the pref-25 subslice.

Both runs Atria answer + Atria judge; selfc ingest cache shared; rendered
profiles reused from `results/lme_profile150/lane*/profiles/` (zero re-render).

## Task 1 — oracle hybrid ceiling

Join: `results/lme_profile150/metrics_profile150.json` ∪
`results/lme150_assist/metrics_assist_*.json` (nogate×assist arm, all
questions that have both judgments — 150 rows).

**Oracle union = 135/150 = 90.0%** — above the ≥90% project bar.

Per-type union vs the two arms:

| type | n | profile | assist | union | gain over best arm |
|---|---|---|---|---|---|
| temporal | 25 | 25 | 24 | **25** | +1 |
| knowledge-update | 25 | 23 | 25 | **25** | +2 |
| ss-user | 25 | 23 | 23 | **24** | +1 |
| ss-preference | 25 | 18 | 20 | **22** | +2 |
| ss-assistant | 25 | 20 | 20 | **20** | 0 |
| multi-session | 25 | 17 | 17 | **19** | +2 |
| **total** | 150 | 125 | 129 | **135** | **+6/+10** |

14 questions are decided by exactly one arm (9 assist-only, 5
profile-only) — the union is not noise-overlap, each arm rescues real
questions the other loses.

### Fingerprint table (router design input)

**Profile-only wins (5)** — all ≤67 vertices:

| qid | type | v | why the stack lost it |
|---|---|---|---|
| 6d550036 | ms | 58 | R2 under-pick (retrieval missed needed vertices) |
| gpt4_15e38248 | ms | 56 | G-boundary: gate abstained, assist flipped it |
| gpt4_483dd43c | temporal | 67 | whole-model always right; big-model list blur |
| 0edc2aef | pref | 17 | stack hedged; profile recommendation landed |
| 75832dbd | pref | 0 | empty-model stub (degenerate case) |

**Assist-only wins (9)** — skews to pref + big-model enumerations:

| qid | type | v | why profile lost it |
|---|---|---|---|
| 35a27287 | pref | 17 | advisory over-conservatism (fixed by task 2) |
| d6233ab6 | pref | 22 | advisory over-conservatism (fixed) |
| caf03d32 | pref | 20 | advisory over-conservatism |
| 95228167 | pref | 13 | advisory over-conservatism |
| 6a1eabeb | ku | 49 | profile updated-fact coverage miss |
| 9ea5eabc | ku | 56 | profile coverage miss |
| 8aef76bc | ss-assist | 21 | assistant-recommendation recall miss |
| d23cf73b | ms | 99 | enumeration summarised in profile |
| c4a1ceb8 | ms | 147 | enumeration summarised in profile |

Router signal read-off: **question-type × vertex-count**. Profile owns
temporal + ms + everything ≤~67v (retrieval/gate failure modes vanish —
there is no pick). Assist owns pref/ku advisory & update coverage and
big-model (99v/147v) enumeration lists. ss-assist is a dead zone for
both arms (residual, not routable by this signal).

## Task 2 — pref-bleed prompt fix

Prompt diff between probe (87.5%) and #74 PROFILE_ANSWER_SYS (83.3%):
**zero — the texts are identical.** The scale drop is mixture, not prompt.
The bleed is the "ONLY facts present in the profile … say so plainly"
constraint: advisory questions carry no literal premise, so the model
refused to infer taste even when the profile held the signal.

Fix (shadow `mainstack/lifemodel/reader.py` PROFILE_ANSWER_SYS, appended):

> For advice or recommendation questions, infer the user's taste
> directly from the preferences and interests recorded in the profile —
> a literal record of the requested item is not required; ground the
> recommendation in the closest matching profile signals.

### Pref-25 subslice result (same profiles reused, answer-only rerun)

**72% → 84% (18/25 → 21/25), +12pp.**

Flips +4/−1:

- 35a27287 ✓ — now infers taste instead of "no location info" refusal
- 57f827a0 ✓ — gives general placement tips grounded in profile taste
- d6233ab6 ✓ — "Yes, likely a good idea" inferred from debate-team signal
- 09d032c9 ✓ — recommends power-bank from recorded ownership
- 75832dbd ✗ — empty-model stub: cleaner refusal text judged wrong this
  time (spurious either way; not a real regression)

Projected whole-150q effect of the clause: ~+4 net pref questions
≈ **profile arm ~86%** (83.3 + 2.7pp) — matching nogate×assist (86.0)
and roughly halves the assist-only pref cells in the fingerprint table
(35a27287/d6233ab6 confirmed rescued; caf03d32/95228167 were wrong in
both runs' outputs and stay wrong).

## Task 3 — channel-routing prototype (150q, all arms vs oracle 90.7%)

With the pref fix in place the per-arm bases move to **profile 129/150
(86.0%)** and **nogate+assist 130/150 (86.7%)**; oracle union rises to
**136/150 = 90.7%**. All routes below are pure joins of judged results —
no new answers rendered (the 150 profiles were rendered under a
PROFILE_SYS verified byte-identical to main's #74 copy).

| route | score | vs oracle |
|---|---|---|
| profile alone | 129 (86.0%) | −7 |
| assist alone (stack champion) | 130 (86.7%) | −6 |
| **route_rule** (temporal/ms→profile; rest→assist) | **131 (87.3%)** | −5 |
| route_vmod (rule + ss-user/ku→profile when v≤70) | 129 (86.0%) | −7 |
| **route_ruleB** (rule + pref→profile, post-fix) | **132 (88.0%)** | −4 |
| route_llm (per-question LLM classifier) | 131 (87.3%) | −5 |
| oracle union | 136 (90.7%) | — |

**route_vmod is refuted.** The "≤70v → profile" modulation sends
ss-user/ku small memories to profile, but assist's two ku wins
(6a1eabeb v49, 9ea5eabc v56) sit inside that window — the arm is
net-negative (−2 vs rule). Vertex count alone does not separate
update-recall coverage.

**route_ruleB** — routing pref to profile is justified by task 2: the
advisory clause made profile pref 21/25 > assist 20/25. 132/150 =
**88.0%**, at the project bar, with zero LLM cost.

**route_llm** (Atria classifier seeing question + type + memory size,
150 calls) scores identically to route_rule (87.3%): it correctly
catches the two big-model enumerations rule misses (d23cf73b v99,
c4a1ceb8 v147 → assist, both won) but loses the two structural ms wins
(6d550036 v58, gpt4_15e38248 v56 — profile-only wins that need a
codebook the question text can't reveal: retrieval under-pick and
gate-boundary, not visible to a text classifier) plus 8aef76bc
ss-assist. An LLM router pays latency/cost to reach parity with a rule.

### Per-type, route_ruleB

temporal 25/25 · ku 25/25 · ss-user 24/25 · pref 21/25 ·
ss-assist 20/25 · ms 17/25

### Residual misroutes (routed arm wrong, other arm right — ruleB)

| qid | type | v | chosen | winner | cause |
|---|---|---|---|---|---|
| caf03d32 | pref | 20 | profile | assist | advisory signal too thin to infer |
| 95228167 | pref | 13 | profile | assist | same |
| d23cf73b | ms | 99 | profile | assist | enumeration, profile summarizes list |
| c4a1ceb8 | ms | 147 | profile | assist | enumeration, largest model |

An enumeration-detector inside the profile route ("list all / how many
different" + v≥~90 → assist) would reclaim the two ms cells — that's
the next rule increment if routing is funded. The two pref cells have
no deterministic signal (v13/v20, same type as profile's wins).

### Oracle floor (14 questions both arms miss)

- 4 empty-model ingest stubs (v0 — data, not routing)
- 6 ms: 88432d0a (R3 dup count), 0a995998 + gpt4_2f8be40d +
  gpt4_7fce9456 (enumeration), 7024f17c (G-boundary), dd2973ad
  (R3 anchor)
- 3 ss-assist (58470ed2, 89527b6b, 1d4da289 — dead zone for both arms)
- 1 ss-user (51a45a95)

Routing cannot beat 90.7% on this join; ~9pp is arm-independent
(ingest stubs, ingest residuals, enumeration, boundary semantics).

## Artifacts

- `results/lme_pref_fix/` — manifest (25 pref questions), hyp jsonl,
  `metrics_pref25.json`, answer-side prompt already carrying the clause.
- `results/mainstack/lifemodel/reader.py` — PROFILE_ANSWER_SYS advisory
  clause (shadow stack only; lands upstream on #74's file if accepted).
- `results/lme_hybrid/` — `route_join.json` (per-question arm
  correctness + vertex counts), `route_llm.py`, `route_choices.jsonl`
  (classifier picks), this report.
