# Record-Diff Dissection: what the new ingest's decompose actually loses

Round (j): side-by-side old-stack vs new-stack records on the same sessions
for 3 ms-25 questions that old stack answers and new stack misses
(b5ef892d camping days, e831120c movie weeks, 3a704032 plant count).
Full per-vertex dumps: `models_side_by_side.json`.

## The lesion taxonomy — four failure shapes, one root cause

### L1. Property stripping → orphaned attributes (b5ef892d)

Old: `"Went on a 3-day solo camping trip to Big Sur in early April 2023"`
— one self-contained record.
New: decomposed into **sibling vertices**:

```
self|camping_experience        "3-day solo camping trip to Big Sur"
self|camping_experience_date   "Big Sur camping trip (on 2023-04-01)"
self|recent_trip_duration      "5 days"          <- no subject at all
self|recent_trip_timeframe     "last month"      <- no subject at all
```

Duration/timeframe/destination were extracted into `*_date`/`*_duration`/
`*_timeframe` vertices carrying bare values. "5 days" and "last month" have
no referent — the aggregation join (which trip was 5 days?) is impossible.

### L2. Subject stripping → bare-value records (3a704032, catastrophic)

`self|plant_acquisition`:
```
"got from the nursery two weeks ago"   <- WHAT was got?
"nursery purchase"
"got from sister"                      <- WHAT, from the sister?
```
`self|plant_ownership`: `"peace lily", "succulent", "fern", "rose bush"`
— bare names, no acquisition context.

Answer needs item↔event↔date joins; the new model holds each leg of the
join in a *different* vertex, each missing the others' context. Old stack:
`"User got the snake plant from their sister last month"` — self-contained.

### L3. Whole-fact dropping (b5ef892d)

The entire 7-day Utah family road trip — including the decisive exclusion
"did a lot of driving and hiking but **no camping**" — is absent from the
new model's 25 self vertices. Old stack kept it as
`utah_family_road_trip` + `utah_trip_activities`. Without the exclusion,
"8 days" can't be computed even when durations survive.

### L4. Vertex collapse (3a704032: 48 → 7 keys)

Slot naming collapsed to a few mega-vertices (`plant_care`,
`plant_health`, `plant_ownership`) holding bare fragments — the inverse
of fragmentation: granularity lost at the vertex level while edges
fragment inside them.

## Root cause

The decompose step emits **atomic property/value records without
self-containment**: it splits {subject, event, property, temporal anchor}
across vertices and drops facts that don't fit the slot naming. The ms-25
failures are exactly the questions needing event-join aggregation —
the join keys are gone, not merely unrendered (consistent with rounds g–h
exonerating the pick/render layer).

## Mechanism proposals (for ingest-side fix)

1. **Self-containment invariant**: every emitted record must carry
   subject + event + temporal anchor inline; bare-value records
   ("5 days", "peace lily") are rejected or must inline their referent
   ("5-day camping trip to Big Sur", "snake plant from sister, last month").
2. **No property orphaning**: date/duration/timeframe stay inside the
   fact record; `*_date` siblings may exist for indexing but the parent
   record must still carry the property.
3. **Acquisition/event integrity**: {item, action, source, date} stay in
   ONE record for acquisition/state-change facts — these are precisely
   the join-bearing facts ms questions ask about.
4. **Coverage guard**: per-session count of self-facts before vs after
   decompose; alarm on dropped facts (Utah trip class).

## Artifacts

- `models_side_by_side.json` — all vertices/edges for the 3 questions,
  both stacks (191 vertex sets).
- Question metadata: oracle `longmemeval_oracle.json` (qids above).
