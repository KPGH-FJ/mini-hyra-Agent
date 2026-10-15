# Temporal order, replay, and snapshot compatibility

LifeModel treats authored day as authoritative; actual arrival breaks
same-day ties. A derivation killed by a premise divergence does not revive
merely because the latest value later returns. A new derivation can establish
it again. Erasure rewrites the retained history and can revive a derivation
when its actual killer was erased.

## New snapshot format

`temporal_order_version: 1` adds three snapshot fields:

- `next_arrival_seq`: monotonic high-water mark for retained-history event
  arrivals. Deleting even every event does not rewind this counter.
- `legacy_order`: true when some imported events lack complete arrival
  metadata. It does not claim that missing order was recovered.
- The version marker itself. Unknown versions are rejected.

History edges now have six fields:

`[value, authored_day, kind, expires_day, record_id, arrival_seq]`

The first five positions are unchanged. The corresponding derived log birth
uses the same `arrival_seq`; the older derived-only `seq` remains a separate
compatibility field. A derivation is correlated with its exact event, including
repeated no-ID, same-day, same-value births with different supports.

Every retained event receives an arrival number, not just authoritative writes.
Non-authoritative records can supply a support ID or advance the expiry clock.
History lists remain in arrival order; replay never sorts them in place.

Import validates sequence types/uniqueness, per-vertex arrival order,
edge/birth correspondence, pending-log membership, high-water marks and
recoverable record-date/value caches before publishing any state. Metadata is
not authentication or proof that an untrusted snapshot is truthful.

## Exceptional replay and atomic failure

Ordinary ordered append/prune remains the fast path. A late self-domain
authoritative write, including a newly available support ID, replays affected
derivations in authored-day/arrival order. Erasure uses the same reference
semantics over the proposed survivors. Cached final values are never used as
the premise state at every historical birth.

The replay maintains historical owner values, leases, support availability,
active derivations and pending births, and applies transitive pruning after
each event. Earlier-authored late support can resolve; genuinely future
support cannot. For same-day support arrivals, the existing deferred-resolution
behavior is preserved: registration occurs when the support becomes available,
not by pretending every final registry entry was present at birth.

Late writes and erasures run in staged state. An unsuccessful operation leaves
history, registries, clocks, counters and control journal unchanged. Import is
also staged. The facade advances its control clock only after successful ingest.
Callers must report `TemporalReplayUnavailable` (a `ValueError`) as an incomplete
operation, never as successful deletion or correction.

## Legacy compatibility

Unmarked four-/five-field store snapshots remain importable. A missing unique
record date is recovered from retained history where possible; no date is
invented as zero to authorize a future premise. Old cached derived state can
be retained at import, but missing birth/support history cannot justify an
affected historical mutation. Deleting all relevant incomplete history is
still allowed.

Distinct-day order, per-vertex list order and derived-log order provide an
actual partial order for old events. For uncertain same-day interleavings,
the reference replay explores the legal orders and merges equivalent states.
It accepts only when all outcomes agree on the affected derived/pending result;
otherwise it raises `TemporalReplayUnavailable` atomically. It does not choose
dictionary order, slot names, record-ID spelling, or an arbitrary owner-first
rule as a substitute for missing metadata. Unrelated ambiguity does not block
a mutation. Newly recorded arrivals follow all imported unknown arrivals on
the same day.

Some legacy order is irrecoverable: histories `D,B,A` and `B,A,D` on one day,
followed by a common killer on the next day, can produce identical old
snapshots. Erasing the final killer should produce different results. No
deterministic migration can reconstruct both from identical input.

Experimental three-field reader caches, such as the historical output of
`results/lme_consol/consolidate.py`, are not complete store snapshots and are
not accepted for this mutation/replay contract. The archival tool is not
rewritten, and no real data is migrated by this change. A separately verified
conversion/source stream would be needed for exact historical mutation.

Legacy replay with many genuinely interacting unknown-order events can still
have exponential worst-case cost. Clock-only duplicates are collapsed with
their legal first-event constraints preserved. There is no correctness-skipping
budget cutoff; large legacy datasets require their own performance qualification.
Modern fully ordered snapshots use a deterministic path without that branching.

## Scoped export and record IDs

Scoped exports densely rank-rebase exported arrival and derived-only sequences
on independent copies. The exported high-water is local; excluded trailing
events and sequence gaps are not exposed. Source state is unchanged. Record
ID/value/date caches are rebuilt from exported history, so a reused ID cannot
pull a later excluded slot's value into the document. Revoked export remains
the empty document, without extra metadata. Existing empty-slot-list behavior
is unchanged.

IDs are best kept unique. Where the existing API admits reused IDs, caches
follow the last actual arrival. Range erasure rewinds them to surviving events.
Ambiguous legacy cross-vertex duplicate IDs are rejected rather than guessed.

The sixth field and snapshot metadata increase measured asset/access bytes.
Those measurements include the added data; no adjustment hides the overhead.
This work does not establish a sandbox, reader authorization policy, or full
entity/privacy isolation beyond the scoped metadata rules described here.

## Offline regression entry points

- `python -m unittest discover -s tests -v`
- `python tests/test_lifemodel_contract.py --strict lm`
- `python tests/test_bench_sweep.py --range 0 400`

`tests/test_temporal_replay.py` covers delayed invalidation, chains, fresh
post-restoration births, same-day support resolution, snapshot corruption,
legacy confluence/refusal, atomicity, scope projection, clocks, and erasure.
