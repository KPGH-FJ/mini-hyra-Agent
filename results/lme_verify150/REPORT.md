# verify-ingest × ruleB routing — 150q full retest (Atria)

Stack: LLMIngestor verify=True (completeness audit, +1 call/session)
+ yield_guard=True (conditional topup). Answer = ruleB routing
(temporal/ms/pref → profile; else assist; enum v≥90 → assist).

## Headline

**routeB×verify = 129/150 = 86.0% — NET LOSS vs ruleB baseline 88.0 (132/150).**

per-type: temporal .96 / ku 1.0 / pref .84 / **ss-assist .96** /
ss-user .92 / **ms .48**
(baseline ruleB: temporal 1.0 / ku 1.0 / pref .84 / ss-assist .80 /
ss-user .96 / ms .68)

Flips +9/−11. verify's lesion-class win is real and exactly offset by
a routing-threshold side effect on multi-session.

## Flip ledger

- **+9 up**: all 5 ss-assist lesions rescued — 6ae235be (refinery),
  89527b6b (plesiosaur "blue scaly body"), 1d4da289 (biometric 2FA),
  58470ed2 (Borges "sphere" quote), **8752c811 (Sound effects — the
  stubborn answer-side miss, now correct via density)** + 3 pref
  reroute wins (nv≥90 flood reshuffled them onto profile) + c4a1ceb8.
- **−11 down**: **8 ms on nv≥90 assist-routed** (nv 95-245 —
  gpt4_59c863d7/159, f2262a51/117, 6d550036/148, aae3761f/195,
  a56e767c/95, 28dc39ac/245, dd2973ad/123, 88432d0a/157,
  gpt4_2f8be40d/193, 7fce9456/144, d23cf73b/203, 7024f17c/196 —
  mostly enumeration/count questions lost inside giant digests) +
  2 pref profile misses (35a27287/57, 38146c39/43) + 1 ss-user + 1
  temporal + 8aef76bc (Mod Podge — verify still dropped it on assist;
  this was the profile-only rescue last round).

## Three comparison points

1. **Total: 86.0 vs 88.0 → −2pp net loss.** verify default-on does NOT
   pay for itself on the full paper under current routing.
2. **Per-channel**: assist 99/115=.86, profile 30/35=.86. nv bins:
   0-59 .90 / **60-99 .94 (profile sub-bin 16/17 .94 — mid-bin
   haystack did NOT degrade)** / **100+ .74 (the bleed)**.
   Record density: median 44→63.5 records/model (+44%), p90=148,
   max=245; verify added 2868 records across all sessions
   (~19/session), guard topup added 177 (fired ~10 sessions).
3. **pick=50 under-pick**: only 6/115 assist-routed questions hit the
   cap (median selected 20) — catalog inflation did NOT revive the
   under-pick lesion.

## Mechanism — why ms bled

verify shifted every model ~+20 records → questions with nv≥90 went
from ~20 to **52**; the enum-fallback threshold (calibrated on old
ingest sizes) now dumps most ms questions onto the assist channel
where enumeration inside a 100-200-vertex digest still fails
(profile had won several of these on smaller models). This is a
**routing-calibration artifact, not proof denser ingest hurts**:
same ingest + profile on mid bins scored .94. The threshold needs
re-tuning on the new density distribution (or ms needs an
aggregation-aware channel, not raw assist).

## Verdict

- verify lesions: FIXED (5/5 incl. the previously "answer-side" 8752c811).
- verify as default-on: −2pp under current ruleB — NOT free.
- Next lever candidates: recalibrate v≥90 upward on dense models,
  or let profile answer ms regardless of size (ms profile bin at
  100+ was untested this round — all big ms were assist-routed).

Data: results/lme_verify150/{questions,models,profiles,answers_routeB,
metrics_routeB,arm_log_*}; driver verify_ingest.py/route_answer.py.
