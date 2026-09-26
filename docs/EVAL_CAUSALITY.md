# Evaluator Causality — four deep bugs found while hardening LifeStream v8e

Methodology note, not a changelog: these bugs lived in the *harness*, not
any asset — each one silently corrupted ground truth or the operation
causality chain, and each was found only because the divergence between
model answers and bench expectations was traced to the bottom instead of
being patched over. Same lesson as the stats() cheat from r1: the
evaluator is part of the system under test.

## 1. Control ops fired in code order, not op-day order

Control operations (`forget@55`, `forget_range@62`, `forget_entity@74`,
`correct@78`, `export@80`, `revoke_purpose@84`) fired between checkpoints
in the order their branches appeared in `drive()`, while each op also
pre-feeds the records authored up to its own day (`_feed_upto`). Firing
`correct@78` before `forget_entity@74` fed the day-76 re-assertion
*before* the day-74 erase ran — the entity came back to life erased,
and the post-forget claim (semantically live: erase is not brick) died.

Fix: pending ops per window are collected, sorted by op-day, then each
fires preceded by `_feed_upto(op_day)`. Invariant: **an op never sees a
record authored after its own day, and a record never reaches the asset
before an earlier-dated op**.

## 2. "Asked at day 90, what was live at 54" used the pre-erasure log

`state_at(D)` gated the range-forget window on the *replay* day D: an
`as_of` probe targeting day 54 (before `forget_range@62`) replayed the
records the erase had already unwritten. The asset — which erases write
edges — honestly answered "unknown"; truth expected the pre-erase value.

Fix: `state_at(day, read_day)` — the window applies iff the **question's
day** is after the erase, not iff the replayed day is. Erasure rewrites
the *log*, not the past: post-erase history questions see the rewritten
log. (This is the bitemporal transaction-time semantics the M2 survey
predicted would matter — valid-time queries evaluated against the
transaction-time tail, not frozen.)

## 3. Same-day-tie ground truth diverged from arrival order

Day is authoritative and same-day writes resolve by *arrival order*
(later wins). The out-of-order shuffle moves ~1/3 of self-writes a few
positions later — so a same-day pair (statement `平板`, update `电脑为主`)
could feed in either order. Truth replayed in construction order; the
model applied feed order → 50/50 divergent expectations on collision
seeds.

Fix: truth events carry their record id and replay sorts by
`(day, position_in_records_list)` — the exact order the asset feeds.
The expectation generator must compute expectations under *the same
semantics the asset is scored on* — not under a more convenient replay.

## 4. Erased-edge expiry residue killed surviving edges (real store bug)

`forget_range` rebuilt `_wday`/`rvid` per touched slot but left
`self.exp[slot]` standing. When the erased write had carried the slot's
lease (`expires_day`), the residue let the surviving *earlier* edge
expire too — values vanished that truth said were live (rollback
expected the pre-window non-expiring value).

Fix: the touched-slot rebuild pops `exp` and re-derives it from the
surviving max-day write's edge metadata.

Found by: seed 24 purpose probes expecting `无照护负担` while the model
honestly reported the rolled-back edge dead. Verified: 78 seeds /
13,946 probes clean; 300 seeds zero crashes.

## Rule of thumb appended to the bench contract

Any expectation replay in the generator must apply *the same semantics
the model is scored on*:

- feed order = records list order (post-shuffle), day authoritative,
  same-day ties by feed position;
- control ops see exactly `records[:day <= op_day]` in list order;
- range erasure removes the write edges — history questions evaluate
  the surviving log;
- a slot's lease lives on its latest *surviving* write;
- dead deriveds, erased records and vacuous bundles are *skipped*, not
  probed — a probe with no meaningful answer is noise, not gradient.
