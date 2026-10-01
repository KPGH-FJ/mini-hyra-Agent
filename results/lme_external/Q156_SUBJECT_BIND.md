# q156-type unsolvable-case attribution — subject-binding failure

Follow-on to `DIAL_ABSTAIN.md`. Question asked: is q156 ("What is Melanie
excited about in her adoption process?", cat5/adversarial, gold=None) a
fixable retrieval problem or does it need a new counterfactual/conflict
mechanism? **Verdict: reader-side subject-binding failure — fixable at
prompt level. No new mechanism needed.**

## Ground truth anatomy (locomo10 conv-0)

The adoption arc belongs entirely to **Caroline**, not Melanie:

| session | who | fact |
|---------|-----|------|
| s2 D2:8 | Caroline | "Researching adoption agencies — dream to have a family" |
| s2 D2:13 | Melanie→Caroline | *asks* "Anything you're excited for in the adoption process?" |
| s2 D2:14 | Caroline | "Thrilled to make a family for kids who need one" |
| s8 | Caroline | council meeting, "more determined to adopt" |
| s13 | Caroline | "I applied to adoption agencies!" |
| s19 | Caroline | "I passed the adoption agency interviews!" |

Melanie's own records are elsewhere: charity race, kids' summer break,
camping plans, self-care. **q156 is a subject-swap trap** — the question
presupposes an attribute-of-Melanie that exists only as
attribute-of-Caroline. The surface topic ("excited about adoption
process") is genuinely retrievable; only the subject is wrong.

## Memory state: attribution survives the pipeline

Replayed extraction on session_2 (Atria, adoption segment). Records come
out correctly attributed — `about` carries the person name:

```
source='self' about='caroline' slot='adoption_agency_research'
source='self' about='caroline' slot='adoption_motivation'   # "Thrilled to make a family"
source='self' about='caroline' slot='single_parent'
source='self' about='melanie'  slot='camping_plans'
source='self' about='melanie'  slot='charity_race'
```

In the reader digest these render as `caroline (per self)·adoption_*` —
the subject is *visible in the label*. So the defect is not extraction,
not merge, not retrieval: **the reader transfers a fact across subjects
because nothing in ANSWER_SYS binds the question's subject to the line's
subject.**

v6 and all four dial arms answered "Melanie is excited about adopting…"
— the classic confab: on-topic evidence exists (Caroline's excitement),
so evreq's "adjacent facts" clause passes a surface check and fails the
real one.

## Subject-check clause — probe evidence

Probe = synthetic LifeModel, 9 vertices mirroring the real catalog shape
(6 caroline·adoption_* + 3 melanie·*), no retrieval LLM calls (catalog
≤50 → all selected). Atria-Dawn-Preview reader, 6 probes:

| probe | result |
|-------|--------|
| q156, base ANSWER_SYS | correct attributed abstention ("entries I have are for Caroline") — Atria subject-binds natively on a small digest |
| q156, +SUBJECT CHECK | cleaner form: "records describe Caroline, not Melanie — Caroline is thrilled to…" |
| "When is Melanie camping?" | correct answer preserved — no over-abstention |
| "Is Melanie excited about Caroline's adoption?" | attributed abstention (no Melanie-feelings vertex exists — correct) |
| "What is David excited about?" | clean abstain |
| "…excited about in Caroline's adoption process?" | attributed abstention (defensible) |

The clause's target isn't Atria (which already binds) — it's the OR
stealth reader that confabbed on the real conv-0, and larger digests
where subject attention dilutes.

### Proposed clause (appended to ANSWER_SYS alongside evreq)

```diff
+  - SUBJECT CHECK: each memory line names who it is about ("caroline
+    (per self)·slot" / "user·slot"). An answer may only attribute a fact
+    to the person its line names. If the question asks about person X but
+    the matching records are about person Y, say the records describe Y —
+    e.g. "the records describe Y's adoption process, not X's". Never
+    silently transfer one person's facts to another.
```

## Classification for the dial roadmap

| q156-type property | where it lives | fix |
|---|---|---|
| topic retrievable, subject swapped | reader prompt | SUBJECT CHECK clause (probe-verified) |
| topic absent entirely (q157/159/161/163) | reader prompt | evreq/presup clauses (shipped-class) |
| premise presupposes unrecorded state (q152) | mostly prompt | evreq form catches some |
| needs genuine counterfactual inference (q14) | inference gap | defer — counterfactual-exception clause or later mechanism |

Recommended next validation: when the OR free pool resets (2026-09-30
00:00 UTC), run the dial harness once more with ANSWER_SYS = base+evreq+
subject-check on the same 22-question set — expected adv ≥83.3% with
q156 joining the FIXED set.

## Probe/environment notes

- Atria rejects OR-style `reasoning` params (HTTP 400) — probes must call
  GLMCompat without `extra_body` on Atria.
- Atria as judge is stricter than OR on hedged/abstention forms
  (DIAL_ABSTAIN Atria layer) — but as *reader* it subject-binds natively.
- Cost: ~20 Atria calls total for this autopsy; no OR consumed.
