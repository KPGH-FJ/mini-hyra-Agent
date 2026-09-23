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
                                # MEASURED by serializing this
def probe_bytes() -> int: ...  # recommended: cumulative bytes consulted
def stats() -> dict: ...   # legacy fallback; DO NOT hardcode small numbers —
                            # fabricated cost is a reward-hack and is flagged
```

`solve.sh` may be a no-op (`exit 0`) — the evaluator imports `asset.py` and
drives the lifecycle itself. Do NOT write files, network-call, or time-depend.

## The stream

~90 days of records: `{id, day, source, kind, slot, value, text, expires_day?}`

- source ∈ `self | other | assistant | device | doc` — who produced it
- kind ∈ `statement | update | correction | retraction | suggestion | hearsay`
- Only `self` + {statement, update, correction} set true state. `hearsay` is
  about OTHER people; `suggestion` is assistant-made — never state.
- `retraction` = user demanded deletion of that slot: stop asserting it.
- `expires_day` = constraint lapses after that day (later probes must not
  use it).
- Multiple slots change mid-stream (update/correction); stale values must be
  superseded, not both kept.

## Probes (answered by `answer()`)

Each probe dict: `{q, type, slot, ckpt, value?, day?, person?}` — `ckpt` is
the day the probe is asked (use for expiry), `value` is the claimed value
(prov only), `day`/`person` appear on the new v2 types.

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
              the forgotten slot must be gone — current state AND history.

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

`score = probe_quality − 0.001·KB(asset) − 0.002·KB(probe) − 0.0001·tokens`.

## What to explore (the research space)

- asset structure: flat map / temporal store / graph / tiered summary
- formation: when to compress, what to keep verbatim, how to mark confidence
- update semantics: supersede chains, correction propagation, expiry checks
- provenance: tracking source per assertion cheaply
- retrieval: what to consult per probe (probe_bytes matters)
- control ops: retraction propagation to derived content

Baselines to beat (same stream+probes, run by the evaluator): raw records,
last-write-wins ledger, keyword RAG.
