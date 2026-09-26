# task: life_model — evolve an "understanding asset" over a synthetic life stream

You are evolving an implementation of a **Life Model asset**: a store that
ingests a stream of records about one person and answers probes about that
person — honestly, updatably, and cheaply.

> ⚠ CONTRACT-FIRST: a submission with no `asset.py` exposing `ingest()` and
> `answer()` scores **−1e9 outright** — 6 of 24 scored submissions in the last
> window died this way. Ship the contract file FIRST, then optimize.

## Deliverable contract (HARD REQUIREMENTS)

Your solution dir MUST contain `asset.py` exposing module-level:

```python
def ingest(rec: dict) -> None: ...
def answer(probe: dict) -> str: ...
def forget(scope: dict) -> None: ...  # optional user-control op; evaluator
                                     # calls forget({"slot": s}) once at a
                                     # checkpoint boundary — absence loses
                                     # cascade-probe points
def state() -> dict: ...        # recommended: serializable asset — cost is
                                # MEASURED by serializing this; also the
                                # export half of the export-import probes
def import_state(d: dict) -> None: ...  # recommended: reload a state()
                                # snapshot. After checkpoint-72 probes the
                                # evaluator round-trips state()->json->
                                # import_state(); probes flagged post_import
                                # score 0 if this is missing/throws
def probe_bytes() -> int: ...  # recommended: cumulative bytes consulted
def stats() -> dict: ...   # legacy fallback; DO NOT hardcode small numbers —
                            # fabricated cost is a reward-hack and is flagged
```

`solve.sh` may be a no-op (`exit 0`) — the evaluator imports `asset.py` and
drives the lifecycle itself. Do NOT write files, network-call, or time-depend.

User-control ops the evaluator may call mid-stream (all optional —
missing ones lose the affected probes honestly): `forget(scope)` at
day ~55, `correct(slot, value)` at day ~78, `revoke_purpose(purpose)`
at day ~84, and `state()`/`import_state(d)` export-import at day ~72.

## The stream

~90 days of records: `{id, day, source, kind, slot, value, text, expires_day?}`

- source ∈ `self | other | assistant | device | doc | inference | system`
- kind ∈ `statement | update | correction | retraction | suggestion |
  hearsay | derived | alias`
- v5 (M1 pressure): records may arrive OUT OF ORDER within a checkpoint
  window — `day` is authoritative, not arrival order. A day-5 record fed
  after a day-20 record is still a day-5 fact.
- `alias` records (source `system`, slot=alias, value=canonical name)
  declare that two person names refer to the same individual (e.g.
  小李 = 同事小李). Hearsay may arrive under either form; subject probes
  may ask by either.
- Only `self` + {statement, update, correction} set true state. `hearsay` is
  about OTHER people; `suggestion` is assistant-made — never state.
- `derived` (source `inference`) IS part of the person's model state — but
  only while its premises hold. `supports` = list of premise record ids:
  a derived fact must die (state AND history) when any supporting record
  is retracted/forgotten OR when a supporting slot's live value diverges
  from what it was when the derivation was asserted (correction kills the
  premise). Death is transitive: derived facts may support other derived
  facts (chains).
- `retraction` = user demanded deletion of that slot: stop asserting it.
- `expires_day` = constraint lapses after that day (later probes must not
  use it).
- Multiple slots change mid-stream (update/correction); stale values must be
  superseded, not both kept.

## Probes (answered by `answer()`)

Each probe dict: `{q, type, slot, ckpt, value?, day?, person?,
post_import?, budget?, slots?, purpose?, purpose_slots?}` — `ckpt` is
the day the probe is asked (use for expiry), `value` is the claimed
value (prov only), `day`/`person` are the v2 temporal/attribution
fields, `post_import` marks continuity probes answered after the
export->import round-trip. v4 serve fields: `budget` is a byte cap on
the scored part of your answer, `slots` lists the slots to pack,
`purpose`/`purpose_slots` name a use-case view and its slot set.

- `state`   — current value of a slot; "未知" if unknown/retracted/expired.
- `stale`   — same but the answer must NOT contain the superseded old value.
- `prov`    — "本人" or "非本人": was the claimed slot=value actually said by
              the person (not hearsay/suggestion)?
- `retract` — after in-stream deletion, assert nothing: "已删除/未知".
- `transfer`— expect = list of values; hit as many as possible in one
              comma-separated answer (e.g. a week's-planning constraint bundle).
- `as_of`   — probe["day"]=D: the value live at day D. Requires history
              reconstruction, not just latest-wins (bitemporal semantics).
- `subject` — probe["person"]=P: the hearsay value attributed to person P.
              Hearsay IS legitimate memory — attributed to its subject,
              never folded into the person's own state. P may be asked by
              canonical name or alias; the latest-day hearsay across all
              of P's name forms is the expected value.
- `cascade` — after the evaluator's forget() call: every asserted value of
              the forgotten slot must be gone — current state AND history,
              INCLUDING derived facts it supported (chains included).
- `derive`  — a derived fact whose premise was superseded (correction): the
              derived value must be gone. Same gone-phrasing scoring.
- `post_import` flag — probes at the last checkpoint answered AFTER the
              evaluator re-loaded your asset via state()->import_state().
              They just verify continuity (state/history/subject/prov/deleted
              facts all survive the move).
- `unans`  — unanswerable (evidence-absent): the slot was never asserted
              by self — baited by hearsay/suggestion values which are
              must_not. Correct answer: "未知" (NOT "已删除" — nothing
              was deleted; distinguish missing evidence from deletion).
- `purpose`— task-conditioned view: serve ONLY live values of
              probe["purpose_slots"], comma-separated; any other slot's
              value is a leak (must_not).
- `revoked`— after the evaluator's `revoke_purpose(purpose)` call: the
              view must REFUSE — answer "已撤回"; serving the purpose's
              own live values is a leak (must_not). The data stays
              intact — only that use is withdrawn.
- `budget` — pack probe["slots"]' live values comma-separated; ONLY the
              first probe["budget"] BYTES of your answer are scored —
              what you put first is the decision.
- `prov2`  — evidence citation: answer with the record id (e.g. "r0023")
              carrying the slot's current self-assertion.
- `ops`    — audit trail: which control op ran. probe["op"] names the op
              ("forget"/"correct"/"forget_range"/"revoke_purpose");
              answer with the slot it targeted. Requires an operation
              journal that survives export/import. Answer "无" when the
              op never ran.

Multi-entity (v8+): records and probes may carry `about=E` — the claim
is about person E (a family member etc.), asserted BY `source` (which
may be "self" or another person). Entity vertices are scoped per
(claimer, about, slot): `state+about` asks for E's asserted value
(never fold it into self state — and E's claims never enter self
answers); `subject+about` asks what a person said about E.
`forget({"about": E})` erases every vertex about E across all claimers;
`state+about` probes then expect "未知". Self-domain registries
(derived premises, consent) engage only when `about` is absent.
`nchange`+about counts E's transitions; `conf`+about grades 高 (self
said it) / 低 (hearsay only) / 无.
Same-day ties: day is authoritative; arrival order breaks ties between
same-day writes (the later record wins).

Answer with the raw value string — short, no prose. Scoring is substring
match (normalized), with a hard penalty for surfacing a `must_not` value.
Authoritative spec: `docs/PROBE_SEMANTICS.md`; executable gate:
`tests/test_lifemodel_contract.py <asset_dir>` (18 clauses).

## Cost accounting

Cost is MEASURED by the evaluator, not self-reported:
- asset_bytes: `len(json.dumps(asset.state()))` if `state()` exists, else
  `stats()["asset_bytes"]` (fallback, flagged as reported).
- probe_bytes: `asset.probe_bytes()` if it exists (cumulative consulted
  bytes), else `stats()["probe_bytes"]`.
- llm_tokens: `stats()["llm_tokens"]` (0 unless your asset calls an LLM).

Honesty rule: claiming ~zero cost while answering non-trivially is flagged
`cost_how=suspicious`. Hardcoding `stats()` constants to fake cheapness is
reward hacking — implement real metering instead.

`score = probe_quality − 0.002·KB(asset) − 0.0002·KB(probe) − 0.0002·tokens`.

## What to explore (the research space)

This round is scoped to **M5 control semantics** — how the owner
steers the asset: consent, erasure, correction, auditability.
Store/update/serve/ingest machinery is pinned by the frozen semantics
(temporal history, supports, premise fixpoint, measured cost, alias
resolution, day-authoritative ordering); what varies is the CONTROL
machinery.

Candidate families (from the literature survey, docs/literature/m5_control.md):
- **consent-scoped views** (purpose revocation): data stays in the
  asset, but a withdrawn purpose's view must refuse — revocable
  consent, not deletion (`meta["revoke"]`; `revoke_purpose` on the
  asset interface).
- **range-scoped erasure with rollback** (`forget({day_gte, day_lte})`):
  erase the window's write edges, then rebuild materialized state from
  surviving edges — the value rolls back to its previous live value,
  not a tombstone (`meta["forget_range"]`).
- **operation journal** (auditability): every control op — slot
  forget, range forget, correct, revoke_purpose — is journaled; the
  journal is part of the asset and survives export/import (post-import
  `ops` probes ask "what did you forget / correct / revoke?").
- **export continuity**: state()/import_state() round-trips the full
  asset — journals, consent registry, attributed hearsay, alias map.
- **user-driven correction**: `correct(slot, value)` asserts a new
  live value at read time (`meta["correct"]`); provenance must still
  answer, and dependent derived facts must die with the old premise.

Still on the table (cumulative pressure from earlier rounds): M1
ingest (alias + out-of-order), M4 serve (purpose views, budgeted
packing, prov2 citation, unans abstention), M3 premise maintenance.
Everything the bench probes is scored.

Also in play:
- purpose views: same asset, multiple use-cases — the view is
  probe-conditioned, never whole-asset dumps
- clarify as an output value: product-side `answer|clarify|abstain`
  exists; on this bench "clarify" maps to "未知" (no dialog channel)
- llm_tokens: an LLM reader is legal but pays per token

Baselines to beat (same stream+probes, run by the evaluator): raw records,
last-write-wins ledger, keyword RAG, TMS baseline, event-sourced replay —
plus the incumbent `lifemodel v1` (~140 on v7) and the seed.
