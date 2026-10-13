"""Generator-only oracle invariants, independent of LifeModel answers.

No model, asset, network, or external dataset is used. The 400-seed scan
checks every public derivation and every emitted citation, not selected
failing seed/probe IDs. Private events are observed read-only for the audit.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tasks" / "life_model" / "bench"))
sys.path.insert(0, str(ROOT / "tasks" / "life_model"))
import generator as gen  # noqa: E402
_argv, sys.argv = sys.argv, [sys.argv[0]]
import evaluate as ev  # noqa: E402
sys.argv = _argv


def record(rid, day, slot, value, source="self", kind="statement", **kw):
    return dict(id=rid, day=day, slot=slot, value=value,
                source=source, kind=kind, **kw)


def derived(rid, day, slot, value, supports):
    return record(rid, day, slot, value, source="inference", kind="derived",
                  supports=supports)


def events_for(records):
    by_id = {r["id"]: r for r in records}
    events = [gen._record_truth_event(r, by_id) for r in records]
    return sorted((e for e in events if e is not None), key=lambda e: e["day"])


def generate_with_events(seed, **kwargs):
    captured = []

    def observe(frame, event, arg):
        if event == "return" and frame.f_code is gen.generate.__code__:
            captured.extend(frame.f_locals["truth_events"])

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        result = gen.generate(seed, **kwargs)
    finally:
        sys.setprofile(previous)
    return (*result, captured)


class GeneratorTruthFixtures(unittest.TestCase):
    def test_superseded_cited_value_and_chain_are_not_live(self):
        records = [record("old", 1, "signal", "OLD"),
                   record("new", 2, "signal", "CURRENT"),
                   derived("plan", 3, "plan", "PLAN", ["old"]),
                   derived("chain", 4, "routine", "ROUTINE", ["plan"])]
        events = events_for(records)
        self.assertEqual(events[2]["premises"], {"signal": "OLD"})
        cur, _ = gen._replay_truth(events, 4)
        self.assertEqual(cur, {"signal": "CURRENT"})

    def test_valid_cited_value_and_chain_stay_live(self):
        records = [record("old", 1, "signal", "OLD"),
                   record("new", 2, "signal", "CURRENT"),
                   derived("plan", 3, "plan", "PLAN", ["new"]),
                   derived("chain", 4, "routine", "ROUTINE", ["plan"])]
        cur, _ = gen._replay_truth(events_for(records), 4)
        self.assertEqual(cur, {"signal": "CURRENT", "plan": "PLAN",
                               "routine": "ROUTINE"})

    def test_later_authored_initial_record_can_supersede_update(self):
        records = [record("initial", 8, "signal", "INITIAL"),
                   record("update", 5, "signal", "UPDATE", kind="update"),
                   derived("plan", 10, "plan", "PLAN", ["update"])]
        cur, _ = gen._replay_truth(events_for(records), 10)
        self.assertEqual(cur, {"signal": "INITIAL"})

    def test_third_write_cannot_replace_a_cited_premise(self):
        records = [record("initial", 1, "family", "INITIAL"),
                   record("change", 5, "family", "CHANGE", kind="update"),
                   record("lease", 8, "family", "LEASE", expires_day=20),
                   derived("plan", 10, "plan", "PLAN", ["change"])]
        cur, _ = gen._replay_truth(events_for(records), 10)
        self.assertEqual(cur, {"family": "LEASE"})

    def test_missing_or_future_support_is_not_unconditional(self):
        for supports in (["missing"], ["future"], ["future", "past"]):
            with self.subTest(supports=supports):
                records = [record("past", 1, "signal", "SAME"),
                           record("future", 20, "signal", "SAME"),
                           derived("plan", 5, "plan", "PLAN", supports)]
                event = events_for(records)[1]
                self.assertIsNone(event["premises"])
                cur, _ = gen._replay_truth(events_for(records), 30)
                self.assertNotIn("plan", cur)

    def test_same_day_support_is_valid(self):
        records = [record("support", 5, "signal", "VALUE"),
                   derived("plan", 5, "plan", "PLAN", ["support"])]
        cur, _ = gen._replay_truth(events_for(records), 5)
        self.assertEqual(cur["plan"], "PLAN")

    def test_unconditional_derivation_remains_distinct_from_missing_support(self):
        records = [derived("plan", 5, "plan", "PLAN", [])]
        self.assertEqual(events_for(records)[0]["premises"], {})
        cur, _ = gen._replay_truth(events_for(records), 5)
        self.assertEqual(cur, {"plan": "PLAN"})

    def test_same_day_citation_uses_last_arrival(self):
        first = record("z-first", 10, "signal", "FIRST")
        last = record("a-last", 10, "signal", "LAST", kind="correction")
        self.assertEqual(gen._latest_self_record_id([first, last], "signal", 10),
                         "a-last")
        self.assertEqual(gen._latest_self_record_id([last, first], "signal", 10),
                         "z-first")

    def test_older_late_arrival_cannot_win_citation(self):
        records = [record("latest", 10, "signal", "NEW"),
                   record("late-old", 2, "signal", "OLD"),
                   record("future", 20, "signal", "FUTURE")]
        self.assertEqual(gen._latest_self_record_id(records, "signal", 10),
                         "latest")

    def test_citation_respects_authority_entity_and_erasure(self):
        records = [record("keep", 5, "signal", "KEEP"),
                   record("erased", 6, "signal", "ERASED"),
                   record("other", 7, "signal", "NOISE", source="friend"),
                   record("entity", 8, "signal", "ENTITY", about="someone")]
        live = lambda r, day: r["id"] != "erased"
        self.assertEqual(gen._latest_self_record_id(records, "signal", 9, live),
                         "keep")

    def test_purpose_keeps_invalid_and_out_of_scope_derived_values_forbidden(self):
        records = [derived("plan", 5, "plan", "PLAN", ["old"])]
        self.assertEqual(gen._derived_leak_values(
            records, 10, {"city": "SAFE"}, ["city"], ["SAFE"]), ["PLAN"])
        self.assertEqual(gen._derived_leak_values(
            records, 10, {"city": "SAFE"}, ["city", "plan"], ["SAFE"]), ["PLAN"])
        self.assertEqual(gen._derived_leak_values(
            records, 10, {"plan": "PLAN"}, ["plan"], ["PLAN"]), [])

    def test_purpose_leak_checks_respect_read_day_and_normalized_overlap(self):
        records = [derived("old", 5, "plan", "Ａ Ｂ", []),
                   derived("future", 20, "other", "FUTURE", [])]
        self.assertEqual(gen._derived_leak_values(
            records, 10, {"city": "prefix-ab"}, ["city"], ["prefix-ab"]), [])

    def test_purpose_scorer_rejects_correct_values_plus_invalid_derivation(self):
        records = [derived("plan", 5, "plan", "PLAN", ["old"])]
        for allowed in (["city"], ["city", "plan"]):
            with self.subTest(allowed=allowed):
                forbidden = gen._derived_leak_values(
                    records, 10, {"city": "SAFE"}, allowed, ["SAFE"])
                probe = {"type": "purpose", "expect": ["SAFE"],
                         "must_not": forbidden}
                self.assertEqual(ev.score_probe(probe, "SAFE"), 1.0)
                self.assertEqual(ev.score_probe(probe, "SAFE,PLAN"), -0.5)


class GeneratorTruthScan(unittest.TestCase):
    def check_generated_truth(self, seed, **kwargs):
        records, probes, truth, meta, events = generate_with_events(seed, **kwargs)
        by_id = {r["id"]: r for r in records}
        oracle_derived = {e["id"]: e for e in events if e["op"] == "set_derived"}
        derived_records = [r for r in records if r["kind"] == "derived"]
        self.assertEqual(set(oracle_derived), {r["id"] for r in derived_records})
        for r in derived_records:
            expected = {}
            for rid in r.get("supports", []):
                support = by_id.get(rid)
                if support is None or support["day"] > r["day"]:
                    expected = None
                    break
                expected[support["slot"]] = support["value"]
            self.assertEqual(oracle_derived[r["id"]]["premises"], expected)
        self.assertEqual(meta["truth_version"], gen.TRUTH_VERSION)

        # A correction to live truth must not erase negative coverage for
        # already-authored invalid or out-of-purpose derived claims.
        for p in (p for p in probes if p["type"] == "purpose"):
            current = truth[p["ckpt"]]["slots"]
            for r in derived_records:
                if r["day"] > p["ckpt"]:
                    continue
                if (r["slot"] in p["purpose_slots"]
                        and current.get(r["slot"]) == r["value"]):
                    continue
                token = ev.norm(r["value"])
                if token and not any(token in ev.norm(v) for v in p["expect"]):
                    self.assertIn(r["value"], p["must_not"], (seed, p))

        # An authored derivation is queried before its planned kill even
        # when it is unsupported. Compare its gold to the corrected replay;
        # the invariant is about question coverage, not asset performance.
        death = {"plan_hint": meta["forget"]["day"],
                 "routine_fit": meta["forget"]["day"]}
        correction = next(r for r in records
                          if r["source"] == "self" and r["kind"] == "correction"
                          and r["slot"] == meta["corr_slot"])
        death["elder_plan"] = correction["day"]
        for r in derived_records:
            for ckpt in gen.CHECKPOINTS:
                if not r["day"] <= ckpt < death.get(r["slot"], 10**9):
                    continue
                hits = [p for p in probes if p["type"] == "state"
                        and p["slot"] == r["slot"] and p["ckpt"] == ckpt
                        and not p.get("about")]
                self.assertTrue(hits, (seed, r["slot"], ckpt))
                value = truth[ckpt]["slots"].get(r["slot"], "未知")
                for p in hits:
                    self.assertEqual(p["expect"], value)
                    if value == "未知":
                        self.assertIn(r["value"], p["must_not"])

        # Independent selection: max(day, feed-index), never lexicographic
        # record ID. Include entity citations and erase-window filtering.
        for p in (p for p in probes if p["type"] == "prov2"):
            candidates = []
            for position, r in enumerate(records):
                if not (r["source"] == "self" and r["slot"] == p["slot"]
                        and r["kind"] in ("statement", "update", "correction")
                        and r.get("about") == p.get("about")
                        and r["day"] <= p["ckpt"]):
                    continue
                erase = meta.get("forget_range")
                if (erase and p["ckpt"] > erase["day"]
                        and erase["lo"] <= r["day"] <= erase["hi"]):
                    continue
                candidates.append((r["day"], position, r["id"]))
            self.assertTrue(candidates)
            self.assertEqual(p["expect"], max(candidates)[2], (seed, p))

    def test_full_400_seed_truth_invariants(self):
        for seed in range(400):
            with self.subTest(seed=seed):
                self.check_generated_truth(seed)

    def test_density_and_storm_truth_invariants(self):
        for density, storm in ((1, True), (5, False), (5, True)):
            for seed in range(20):
                with self.subTest(seed=seed, density=density, storm=storm):
                    self.check_generated_truth(seed, density=density, storm=storm)


if __name__ == "__main__":
    unittest.main(verbosity=2)
