# task: life_model — evolve an "understanding asset" over a synthetic life stream

You are evolving an implementation of a **Life Model asset**: a store that
ingests a stream of records about one person and answers probes about that
person — honestly, updatably, and cheaply.

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

## The stream

~90 days of records: `{id, day, source, kind, slot, value, text, expires_day?}`

- source ∈ `self | other | assistant | device | doc | inference`
- kind ∈ `statement | update | correction | retraction | suggestion |
  hearsay | derived`
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
post_import?}` — `ckpt` is the day the probe is asked (use for expiry),
`value` is the claimed value (prov only), `day`/`person` are the v2
temporal/attribution fields, `post_import` marks continuity probes
answered after the export->import round-trip.

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
              never folded into the person's own state.
- `cascade` — after the evaluator's forget() call: every asserted value of
              the forgotten slot must be gone — current state AND history,
              INCLUDING derived facts it supported (chains included).
- `derive`  — a derived fact whose premise was superseded (correction): the
              derived value must be gone. Same gone-phrasing scoring.
- `post_import` flag — probes at the last checkpoint answered AFTER the
              evaluator re-loaded your asset via state()->import_state().
              They just verify continuity (state/history/subject/prov/deleted
              facts all survive the move).

Answer with the raw value string — short, no prose. Scoring is substring
match (normalized), with a hard penalty for surfacing a `must_not` value.

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

This round is scoped to **M3 update semantics** — how new records revise
existing state and how invalidation propagates. Representation is pinned
by the probe semantics (temporal history + attribution still needed);
what varies is the UPDATE machinery.

Candidate families (from the literature survey, docs/literature/m3_*.md):
- **TMS / truth-maintenance**: every derived entry carries supports
  (premise rec ids); premise death -> cascade-invalidate dependents,
  transitively. The classical answer to "forgetting must propagate".
- **AGM / Katsuno-Mendelzon operators**: separate revision (belief was
  wrong — history rewritten) from update (world changed — history kept).
- **event-sourced re-derivation**: keep the raw event log; recompute
  derived views after every invalidating event (probe_bytes pays).
- **materialized-view invalidation**: derived entries are cached views
  with dependency indexes — invalidate on writes, like a DBMS view.
- **bitemporal rules**: correction = retroactive truth fix vs update =
  new fact; which semantics is right for premise-matching?

Also in play:
- supports representation: rec ids vs (slot, premised value) pairs
- when to evaluate derivation validity: at write (eager invalidation),
  at read (lazy check), or on a propagation pass
- export-import: state() must round-trip through plain JSON
- control ops: forget() now has to kill dependent derivations too

Baselines to beat (same stream+probes, run by the evaluator): raw records,
last-write-wins ledger, keyword RAG — plus the incumbent reference impl
`lifemodel v1` (~109 on v3) and the seed (~89).
