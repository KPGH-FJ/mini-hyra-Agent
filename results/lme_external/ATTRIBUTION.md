# Speaker-attribution fix — named-persona binding (LoCoMo conv-0, all-Atria)

Follow-up to the expanded adversarial coverage round (`DIAL_ABSTAIN.md`):
conv-0's 74.5% adv-precision outlier was traced to **ingest-side speaker
mislabeling**, not a reader-clause failure. This round fixes attribution
at ingest with two ablation arms.

## Headline

| arm | ingest | conv-0 cat5 adv_acc | Δ vs stock |
|-----|--------|--------------------|------------|
| stock (merged stack) | EXTRACT_SYS user/assistant frame | 35/47 = **74.5%** | — |
| **bind** | SPEAKER BINDING clause | 42/47 = **89.4%** | **+14.9pp** |
| **audit** | stock extract + attribution audit pass | 43/47 = **91.5%** | **+17.0pp** |

Reference: clean-label convs (conv-1 91.7%, conv-2 92.7%) — both arms
land at that ceiling. **The clause is sufficient** and costs zero extra
calls; audit adds +2.1pp at +1 call/session.

## Root cause (code-level)

`locomo.py::normalize_turns` marks every turn `role="user"` — a
two-person chat is dressed as a user/assistant session, with the real
speaker name surviving only inside `content` as `Name: text`.
`EXTRACT_SYS` then frames "a user and an AI assistant": both speakers'
self-reports get `about=null` (`user·slot`) or `source="assistant"`
(`assistant·slot`), and relayed third-party facts land on
`about=X (per self)` where "self" is unnamed. The reader-side SUBJECT
CHECK can only read labels — it cannot reject a swap the label already
lied about. 8/12 conv-0 adversarial misses were exactly this.

## Arms

- **bind** (`attr_ab.py::BindIngestor`): extract prompt replaced by
  BIND_SYS — `source` = the `Name:` prefix's lowercase name,
  `about=null` = the speaker themself, generic `self`/`user`/`assistant`
  forbidden; body rendered as bare `Name: text` lines (no outer
  USER/ASSISTANT tag). Snapshot: 44 named vertices after 4 sessions —
  zero generic labels (`caroline|lgbtq_support_group_attendance`,
  `melanie|painting_hobby`, ...).
- **audit** (`attr_ab.py::AuditIngestor`): stock extract unchanged,
  then one AUDIT_SYS pass per session re-aligns every record's
  source/about to the utterance its `text` quote came from. Same schema
  in and out; on array-shape loss the arm falls back to the unaudited
  records (did not trigger).

Snapshots: bind 256 records, audit 269 — vs stock 336. Bind emits no
assistant-side artifact records (there is no assistant) — fewer, more
precisely-owned records; coverage did not suffer (its two regressions
are judge-boundary, not missing facts).

## Per-question deltas (vs stock)

All 9 attribution-driven misses fixed under **both** arms:

`c0_q168/169/170` (running — Melanie's `assistant·` records),
`c0_q186` (Ed Sheeran — `user·music_tastes`), `c0_q191/194/195`
(son's accident — `son (per self)`), `c0_q198` (family camping —
`user·…tradition`), and **`c0_q156`** — the previously unfixable
bridge confab. Under audit the extract even surfaced the true
semantics verbatim: *"memory only records that her friend's adoption
makes Melanie feel like maybe she should adopt too; it does not
describe Melanie's own adoption process"* — i.e. q156's presupposition
was wrong at the content level, not just the speaker level.

Regressions:

- bind −2: `c0_q166` (bridged Melanie's kids-values into a "place she
  wants to create" answer — scope bridge), `c0_q189` (correct
  premise-denial — pottery is `melanie|pottery_*`, Caroline only
  `pottery_interest` — but the hedged "she's been keeping busy
  painting" tail scored as an answer; judge-boundary).
- audit −1: `c0_q182` (asserted Melanie "found lovely flowers" — true
  fact — under a false "neighborhood walk" premise; hedge-assert
  boundary).
- bind-only win over audit: `c0_q182`; audit-only wins over bind:
  `c0_q166`, `c0_q189` — audit's unchanged stock coverage edges out
  bind's narrower record set on both borderline items.

## Verdict & what shipped

- **Clause is sufficient**: +14.9pp to the clean-label ceiling at zero
  marginal cost → promoted into `EXTRACT_SYS` as a conditional SPEAKER
  BINDING block (fires only when lines carry `Name:` prefixes;
  user/assistant semantics preserved for single-user chats like
  LongMemEval). Commit `c53a6d2` on `devin/1790614556-reader-personal`
  (PR #52 branch); smoke-verified verbatim through the stock
  `USER: Name:` body path — 11/11 records named, cross-person record
  `melanie|about=caroline` correct.
- **Audit is the optional second pass**: +2.1pp at +19 calls/conv;
  worth it where the residual ~8% matters (bench evals), not as the
  default ingest path.
- **Remaining failure surface** (post-attribution): hedge-vs-assert
  judge boundary (q182/q189-type), scope bridges (q166-type), pure
  no-record assertions. Next dial if chased: stricter "deny the
  presupposition, don't offer a near-fact" reader wording.

## Ops notes

- Both arms: 19/19 sessions ok, 0 partial, 0 failed; ~30-35min each
  under ongoing 429 congestion (shared key).
- Cost: 0 OR. ~200 Atria calls total (bind ~95, audit ~105 incl. 19
  audit calls, 94 judge).
- Measured HEAD: `devin/1790614556-reader-personal` dfaa6bd +
  lme.py OR/Atria patch (same reader as the expanded round).

Files: `attr_ab.py` (arms runner), `attr_{bind,audit}_c0.jsonl`
(hypotheses), `attr_{bind,audit}_c0_metrics_atria.json` (judged rows),
`attr_{bind,audit}_c0_atria.json` (reloadable snapshots),
`attr_{bind,audit}_c0_progress.json`.
