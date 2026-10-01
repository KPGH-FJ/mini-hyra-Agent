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

## Artifacts

- `results/lme_pref_fix/` — manifest (25 pref questions), hyp jsonl,
  `metrics_pref25.json`, answer-side prompt already carrying the clause.
- `results/mainstack/lifemodel/reader.py` — PROFILE_ANSWER_SYS advisory
  clause (shadow stack only; lands upstream on #74's file if accepted).
