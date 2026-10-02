# Domain-sectioned profile answering (sec_pick / sec_all) on >=60v memories

Parent task: attack the .91→.74→.67 haystack inflection by indexing the
rendered profile into its `## ` domain sections. Three arms on the 22
questions whose models have >=60 vertices (60-99v n=19, 100+v n=3):
sec_pick (roster → pick 1-3 sections → answer on those), sec_all
(same split, all sections fed back), flat baseline = the profile@150q
numbers (pref questions under the advisory-clause prompt).

Atria answers + Atria judge; cached renders reused (PROFILE_SYS verified
byte-identical to main #74). Roster entries carry domain title + bullet
count + top-3 entity hints (`### ` sub-headers where present, else
leading words of first bullets) — per the vertex-pick failure lesson,
no blind picking.

## Scores (≥60v slice, n=22)

| arm | 60-99v | 100+v | total |
|---|---|---|---|
| flat (baseline) | 14/19 (.74) | 2/3 (.67) | 16/22 (.73) |
| **sec_pick** | 13/19 (.68) | 2/3 (.67) | 15/22 (.68) |
| **sec_all** | 15/19 (.79) | 3/3 (1.00) | 18/22 (.82) |

## Verdict

**sec_pick refuted** — misses the >=.80-in-both-bins bar by a wide
margin and is net-negative vs flat (−1). Flips: rescued d23cf73b
(enumeration found its section), lost ce6d2d27 and 3a704032 (the pick
dropped the section holding the answer). Same failure signature as the
vertex-level pick experiments: the selection stage is blind to which
section actually carries the needed fact, and a wrong pick is
unrecoverable downstream. Domain granularity did not fix it.

**sec_all is the interesting arm**: identical content, zero losses, +2
rescued — and the two rescues are exactly the big-model enumerations
(c4a1ceb8 v147, d23cf73b v99). Just re-presenting the profile under
explicit "PROFILE SECTIONS:" framing helped list-aggregation. Gain is
real but small-n: 100+v bin is n=3.

sec_pick ≪ sec_all on the same content isolates the cause: the loss
lives entirely in the pick stage, not the sectioned representation.

## 100+v section stats (second-level-index input)

d682f1a2 (100v): 8 sections, ~15.4 bullets/section
c4a1ceb8 (147v): 11 sections, ~13.8 bullets/section
b5ef892d (128v): 9 sections, ~15.6 bullets/section
a3838d2b (97v, near-bin): 9 sections, ~9.7 bullets/section

Sections stay ~8-11 wide even at 147v — a second level would only
shrink each section ~2-4 bullets; probably marginal. n=3 though: treat
as weak evidence, not a verdict.

## Format caveat found & fixed

2/22 cached profiles render headers as `### ` or `**Title**` instead of
`## ` (PROFILE_SYS doesn't pin the marker level). First-pass splitter
missed them → answered on empty input. Splitter now cascades `## ` →
`### ` → `**Title**`; if domain indexing ships, PROFILE_SYS should pin
the section marker. Affected questions rerun; numbers above are clean.

## Artifacts

`results/lme_secpick/` — manifest.json (22 items), secpick.py,
hyp_both.jsonl (pick roster + both answers), hyp_sec_pick.jsonl /
hyp_sec_all.jsonl, metrics_sec_pick.json / metrics_sec_all.json.
