# LifeStream probe semantics (pinned)

How every probe type is scored, what evaluator-fired ops do, and which
fields a probe carries. This is the spec evolved solutions evolve
against — the contract suite (`tests/test_lifemodel_contract.py`)
encodes the same invariants as executable checks.

## Probe fields

| field | meaning |
|---|---|
| `ckpt` | read day the answer is evaluated at (18/36/54/72/90) |
| `type` | probe family (below) |
| `slot` | the claim slot under test |
| `expect` | scalar or list — scored substring match on the answer |
| `must_not` | list of leak strings — any hit scores −0.5 immediately |
| `about` | entity the claim is about (`None`/`absent` = self) |
| `person` | the claimer for subject probes |
| `day` | explicit day for as_of |
| `purpose`/`purpose_slots` | use-view name + its slot list |
| `slots`/`budget` | packing probes: slot list, byte cap |
| `op` | ops audit: `forget`/`forget_range`/`correct`/`revoke_purpose` |
| `partial` | scoped-export content check — answer is the doc, not an answer() |
| `post_import` | also score on the day-72 export→import snapshot |
| `post_partial` | answer taken from the scoped export doc (not answer()) |
| `value` | prov probe's queried value |
| `supports` | (records only) derived premises `[record_id]` |

## Scoring

- `must_not` hit → **−0.5** before anything else (leak beats being wrong)
- `expect` scalar → substring in normalized answer → 1.0 else 0.0
- `expect` list → fraction of items present (partial credit)
- `retract`/`cascade`/`derive` → any "gone" phrasing in expect list → 1.0
- `budget` → only the first `budget` bytes of the answer are scored
- `partial`/`post_partial` → score computed on the scoped-export document;
  missing doc → 0.0; revoked-purpose doc produced → **−0.5**
- `post_import` → additionally scored on the re-imported snapshot;
  no working import → answer treated as ""
- `ops` → first matching journal entry's slot/purpose/range string
- `expdeny` → scoped export for a revoked purpose produced a document
  → −0.5; refused (empty) → 1.0

## Evaluator-fired ops (between checkpoints)

| day | op | pinned semantics |
|---|---|---|
| 55 | `forget({"slot":s})` | erase slot across every vertex; derived dependents die |
| 62 | `forget({"day_gte":l,"day_lte":h})` | erase write edges in window → slot rolls back to previous live value |
| 72 | export→import | `state()` → JSON → `import_state` on the same asset; stream continues |
| 74 | `forget({"about":X})` | erase every `*\|X\|*` vertex (all claimers); self untouched |
| 78 | `correct(slot,value)` | owner write; lands as a correction edge |
| 80 | scoped export | `state(scope={"slots":[...]})` — self-domain only |
| 84 | `revoke_purpose(p)` | data stays; view refuses; scoped export for p must refuse |

## Probe types (29 + entity variants)

- `state` current live value · `stale` superseded value must not appear
- `as_of` value at `day` (history, not replay-of-latest)
- `subject` latest claim by `person` (aliases merge) — hearsay stays hearsay
- `prov` "did self say `value`" → 本人/非本人
- `prov2` record id citation (`rvid`)
- `unans` never-seen slot → 未知
- `transfer` bundle of live self-values
- `purpose`/`revoked` use-view / refused view
- `budget` byte-capped packing · `partial` scoped-export content
- `derive`/`drvprov` derived fact live-ness / premise citation
- `cascade`/`retract` post-forget/post-retraction deadness
- `duration` days since current run began (ckpt-day endpoint)
- `nchange` count of value transitions (retraction resets)
- `conf` self-claim→高, hearsay-only→低, nothing→无
- `isconf` conflict detection: a non-self claimer asserted a different
  value on the slot by read day → 是; only self claims (or none) → 否.
  Self-domain only; retractions excluded. Upstream of `conf` grading —
  you can't grade certainty you haven't noticed is contested
- `ops` journal audit · `expdeny` revoked-purpose export refusal
- `first` earliest write value of the slot's CURRENT run (post-last-
  retraction run, not the all-time first)
- `order` surviving write-run values of the slot, "→"-joined in day
  order (consecutive dups collapse)
- `before` cross-slot ordering — the day each slot's live value began
  (last transition day of the surviving run), compared pairwise;
  emission requires a ≥2-day margin to clear near-ties
- `join` cross-slot: the day `slot` changed to its live value (probe
  carries `day`), what was slot2's value then
- `absent` stability: no surviving write on the slot with day > 40
  → 是; any → 否 (threshold 40 — self-writes stop ~day 55)
- `window` transitions of the slot's live value inside [30,60];
  prev carried from before the window
- `xcmp` entity-vs-self same-slot compare: `about`'s live value ==
  own live value → 是 else 否 (entity None → 未知 on the entity side)
- entity variants: `state`/`subject`/`conf` + `about` field;
  erased-after-@74 probes expect 未知

## Cost

`asset_bytes`/`probe_bytes` measured from `state()`/`probe_bytes()`
when exposed (`cost_how=measured`), else `stats()` self-report
(`reported`); answered-something-with-zero-probe-cost → `suspicious`.
score = quality + cost-curve terms (see evaluate.py weights).

## Semantics pinned by the bench (contract clauses)

1. expiry = slot-scoped lease at read day
2. truth resolves by record `day`, not arrival order
3. derived `supports=[rec_id]`; dangling → dead at birth; premise
   divergence kills, chains cascade (TMS fixpoint)
4. retraction deletes the live value
5. hearsay never writes self state; `subject` preserves claimer
6. same-day-tie hearsay keys are never probed (no canonical answer)
7. drv premises keyed `{premise_slot: premised_value}`; every derived
   dies young EXCEPT creed@5-premised (creed never changes)
8. `revoke_purpose`: data stays, view refuses incl. scoped export
9. journal is part of the asset — survives export→import
10. multi-entity: `claimer|about|slot` vertexes; self-domain registries
    engage only `not about`; AUTH filter applies to self-claimer;
    scoped exports carry 2-part (self-domain) keys only; entity claims
    live at `claimer|about|slot`, never merging with `claimer|slot`
11. `forget(about)`: all-claimer entity erasure
12. aliases drop from scoped exports (they leak corrected values and
    person identities)
13. an erasure REWRITES the record log — derived state is derived from
    the log, so it is rebuilt from surviving derived events in
    (day,arrival) order: a derived pruned by a killer that was itself
    erased comes back alive (truth expectations are read-day relative
    — `derive`/`cascade` expects whatever state_at(ckpt, read_day)
    holds, never a hardcoded death)
14. `must_not` decoys must exclude values live at read day (a stale
    decoy equal to the live value would punish a correct answer)
15. scoped export = in-scope content only, dependencies included or
    dead: `drv_log`/`pending_drv`/`rday`/`journal`/`aliases` are all
    scope-filtered (out-of-scope derived VALUES must not ride in the
    doc); a derived whose premise slot is out-of-scope dies on restore
    (the premise can't justify it inside the scoped doc)
16. a surviving user write outranks a revived derived — explicit
    beats inferred on erase-rewrite (hist edge reads before the drv
    registry)
17. `forget({"about": X})` erases entity claims but keeps name
    forms — entity aliases are resolution metadata, not claims
    about the entity; post-forget mentions under ANY name form
    still canonicalize to X's (now empty) vertex rather than
    fragmenting into fresh canonicals
