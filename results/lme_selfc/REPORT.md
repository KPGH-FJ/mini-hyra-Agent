# Self-Containment Fix: EXTRACT_SYS bullet repairs the ms collapse

Round (k): the record-diff lesions (L1 property stripping / L2 subject
stripping / L3 whole-fact dropping / L4 vertex collapse) traced to one root
cause — decompose emits non-self-contained records. Fix tested here: append
a self-containment bullet to the ingest extract prompt.

**Bullet (LME_SELFCONTAIN=1 override in lme_variants.py, verbatim):**

```
- SELF-CONTAINED RECORDS: every record must stand alone — named
  subject + complete fact + temporal anchor inline. Never emit bare
  values ("5 days", "peace lily", "last month") without their
  referent; keep dates and durations inside the fact record, never
  split them into a separate vertex; acquisition/state-change facts
  keep {item + action + source + date} in one record.
```

## Phase 1 — lesion validation on the 3 dissected questions

Re-ingested b5ef892d / e831120c / 3a704032 sessions with the bullet.
**L1–L4 all cleared:**

- b5ef892d: `yellowstone_camping_trip` = "5-day camping trip to
  Yellowstone ... (on last month)" — duration+referent+anchor inline;
  `*_date`/orphan vertices gone; **Utah 7-day trip + "no camping"
  exclusion back** (`family_road_trip_utah`, `road_trip_activities`).
- e831120c: `star_wars_marathon` = "marathon that took a week and a
  half" — the dropped duration restored inline.
- 3a704032: acquisitions carry item+action+source+date
  ("bought a peace lily from a nursery ... (on 2023-05-07)");
  vertices restored 7 → 61.

## Phase 2 — ms-25 full re-ingest + v_base + Atria judge

| arm | accuracy | notes |
|---|---|---|
| v_base (broken new ingest) | 28% (7/25) | lme_srcfix metrics_base |
| **v_selfc (self-contain ingest)** | **60% (15/25)** | this round |

Same reader (v_base), same judge (Atria-Dawn-Preview), same sessions —
only the extract prompt differs. **+32pp; recovers 32 of the 44pp gap
to old-stack parity (72%).**

Flips: +10 (incl. all 3 dissected questions — the anatomy predicted the
fix) / −2 (6d550036, dd2973ad). Median records 93 vs broken-new 102 vs
old ~55 — count similar, but records now self-contained; notably
2e6d26dc natively ingests at 60 recs (the density the offline deep-merge
needed last round).

Ingest cost: heavier prompts (median ~120k completion tokens/question
across retries+escalations); 22 fresh ingests ≈ 6.4h on 2 lanes.

## Verdict

**Mechanism confirmed and repaired.** The ms 72→28 collapse's dominant
lesion was decompose's non-self-contained records; the fix is a
one-bullet prompt change at extract time — no reader/retrieval change
needed (consistent with rounds g–h exonerating that layer).

**Proposal**: land the bullet as a default in `lifemodel/ingest_llm.py`
EXTRACT_SYS (user-side merge; lme_variants override already proves it).

## Artifacts

- `models/` `../lme_selfcA/models/` `../lme_selfcB/models/` — 25
  self-contain-ingested models
- `hyp_base.jsonl` (+A/B) — per-question answers
- `../lme_selfc_all_hyp.jsonl` — merged 25-row hyp for judging
- `../metrics_selfc.json` — Atria judge output (60%)
- `../data_selfc3.json`, `../data_ms25_scA.json`, `../data_ms25_scB.json`
- `run*.log` — ingest/answer logs with token usage per question
