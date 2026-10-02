# ss-assist double-blind attribution (the biggest shared-blind type)

ss-assist = the largest cell of the oracle floor: 20/25 union, 5
questions missed by BOTH channels (plus 8aef76bc missed by profile
only). All 25 models are small (3–33v, plus 2 empty stubs) — this type
is where the whole memory should fit, so misses can't be haystack.

Method: pulled gold + both channel answers + retrieval `selected`
vertices + profile text + raw model records per question; traced each
miss to the layer where the needed fact died. Verified against
`haystack_sessions` that the gold fact existed in the source.

## Lesion distribution (6 question-level misses)

| class | n | questions |
|---|---|---|
| **A — ingest missing content** | **5** | 6ae235be, 8752c811 (empty stubs) · 58470ed2 · 89527b6b · 1d4da289 |
| **B — profile lost detail** | 1 | 8aef76bc |
| C — answer-side reasoning | 0 | — |

**83% of ss-assist misses are pure ingest coverage.** Neither channel
can answer a record that was never written.

## Evidence chains (record → profile → channel output)

**58470ed2** (v13) — "what did Borges say about the center and
circumference": haystack contains the verbatim quote; decompose kept
thematic essay structure (`essay_thesis`, `essay_theme_*`,
`library_structure` = "hexagonal galleries") but dropped the quotable
line itself. Selected 12 vertices — all present, none carrying the
quote. → A, verbatim-quote loss: the decompose preserves *aboutness*,
not *citability*.

**89527b6b** (v6) — "what color was the Plesiosaur's scaly body":
haystack says blue; the four parallel chapter records
(`dinosaur_book_chapter_*`) keep colors for T-Rex (green) and
Triceratops (brown) but the Plesiosaur record drops it ("swimming with
colorful fish"). → A, sibling-record inconsistency: same schema, one
record lost the attribute the question asks for.

**1d4da289** (v3) — "examples of 2FA you mentioned": haystack contains
biometric/OTP; the model has 3 vertices **all `self|*`** — zero
`assistant|*` records for the entire assistant turn. → A, whole-turn
drop: the nastiest variant — an entire content-bearing turn yields zero
records and nothing downstream notices.

**6ae235be / 8752c811** — n_records=0 ingest stubs. → A.

**8aef76bc** (v21) — "what sealant for the newspaper vase": the record
`assistant|diy_project_newspaper_flower_vase` exists verbatim
("seal with Mod Podge for water resistance"), the assist arm retrieves
and answers correctly; the profile generalized the recommendation away.
→ B, the only profile-side loss.

## Why the other 19 questions answer right

When assistant records exist, both channels read them fine:
- retrieval picks `assistant|*` vertices (8aef76bc selected the Mod
  Podge vertex unprompted);
- the profile carries "Assistant suggested X" lines verbatim
  (70b3e69b → Manolo García; 8464fc84 → Roscioli line present in
  profile).

Correct-case anatomy: tiny model, a handful of `assistant|*` vertices,
question targets one salient assistant fact. The channel layer is
healthy — **record existence is the whole game.**

## Design input: assistant-facts coverage

The fix belongs at **ingest**, not at the answer channel:

1. **Per-session assistant-yield guard** — count fact-bearing assistant
   turns vs `assistant|*` records emitted per session; a zero-yield
   session (1d4da289) currently slips through silently. Mirrors the
   user-fact coverage guard proposed earlier for L3.
2. **Sibling-record attribute parity** — when N parallel records share
   a schema (4 dinosaur chapters), enforce attribute parity across the
   set (3 carry image-color → the 4th must too, else flag/repair).
   Catches 89527b6b-type selective attrition.
3. **Quote/citability retention** — for essay, recommendation and
   advice content, keep the verbatim citable line inside the record
   ("X said/claimed/recommended Y"). ss-assist questions ask exactly
   for those lines; thematic decomposition alone can't answer them.

An assistant-subgraph side channel (separate profile over `assistant|*`
vertices only) would fix only the B case (~17% of the class) — the
records aren't in the graph at all for A. Not worth a dedicated lane;
spend the effort at ingest.

## Artifacts

Analysis scripts inline in this commit's results dir;
`results/lme_ssassist/` — this report + `lesions.json` (per-question
class + evidence pointers).
