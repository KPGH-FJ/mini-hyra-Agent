"""Offline evaluator API regressions; only fixed, trusted synthetic assets.

Run: python -m unittest discover -s tests -p 'test_evaluation_protocol.py' -v
These checks do not claim to sandbox Python candidates in the evaluator process.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tasks" / "life_model"))

_argv, sys.argv = sys.argv, [sys.argv[0]]
import evaluate as ev  # noqa: E402
sys.argv = _argv


class EmptyAsset:
    def ingest(self, record):
        pass

    def state(self, scope=None):
        return {}

    def probe_bytes(self):
        return 1


class EchoGold(EmptyAsset):
    """No memory: the old API could hand this asset its entire answer."""
    def answer(self, probe):
        expected = probe.get("expect", "")
        return ",".join(expected) if isinstance(expected, list) else expected


class EvaluationProtocolTests(unittest.TestCase):
    def probe(self, ptype="state", **kw):
        p = {"id": "p-test", "ckpt": ev.CHECKPOINTS[0], "type": ptype,
             "slot": "city", "q": "Where does the person live?",
             "expect": "Oslo", "must_not": ["Bergen"]}
        p.update(kw)
        return p

    def test_stateless_gold_echo_cannot_earn_answers(self):
        probes = [self.probe(),
                  self.probe("transfer", expect=["Oslo", "cycling"]),
                  self.probe("cascade", expect=["已删除", "未知"])]
        rows, _, _ = ev.drive(EchoGold(), [], probes)
        self.assertEqual([row["score"] for row in rows], [0.0, 0.0, 0.0])
        self.assertEqual([row["answer"] for row in rows], ["", "", ""])

    def test_query_keeps_all_documented_fields_only(self):
        public = {"id": "p-test", "type": "budget", "slot": "_pack",
                  "q": "Pack the live constraints", "ckpt": 90,
                  "value": "Oslo", "day": 18, "person": "Alex",
                  "about": "Morgan", "slot2": "diet", "op": "forget",
                  "purpose": "weekly_plan", "purpose_slots": ["city"],
                  "budget": 30, "slots": ["city", "diet"],
                  "post_import": True}
        private = {"expect": ["gold"], "must_not": ["stale"],
                   "post_partial": True, "future_grading_field": {"gold": 1}}
        self.assertEqual(ev.candidate_probe(dict(public, **private)), public)

    def test_query_is_deeply_detached_in_both_directions(self):
        slots = ["city", "diet"]
        original = self.probe("budget", slots=slots, purpose_slots=slots,
                              expect=slots)
        before = copy.deepcopy(original)
        query = ev.candidate_probe(original)
        query["slots"].append("injected")
        query["purpose_slots"].clear()
        query["expect"] = "invented"
        self.assertEqual(original, before)
        original["slots"].append("later")
        self.assertNotIn("later", query["slots"])
        self.assertIsNot(query, original)

    def test_candidate_mutation_cannot_rewrite_scoring_or_later_probe(self):
        shared = ["city"]
        probes = [self.probe("budget", expect=shared, slots=shared,
                             budget=30, must_not=["forbidden"]),
                  self.probe("transfer", expect=shared, slots=shared)]
        before = copy.deepcopy(probes)

        class Mutator(EmptyAsset):
            seen = []

            def answer(self, query):
                self.seen.append(copy.deepcopy(query))
                query["slots"].clear()
                query["slots"].append("forbidden")
                query["expect"] = "forbidden"
                query["must_not"] = []
                query["type"] = "state"
                query["budget"] = 0
                return "forbidden"

        asset = Mutator()
        rows, _, _ = ev.drive(asset, [], probes)
        self.assertEqual(probes, before)
        self.assertEqual(asset.seen[1]["slots"], ["city"])
        self.assertEqual([row["score"] for row in rows], [-0.5, 0.0])
        self.assertEqual([row["probe"] for row in rows], before)

    def test_raising_answer_cannot_mutate_trusted_probe(self):
        class RaisingAsset(EmptyAsset):
            def answer(self, query):
                query["expect"] = ""
                query["must_not"] = []
                query["type"] = "expdeny"
                raise RuntimeError("synthetic failure")

        probe = self.probe()
        before = copy.deepcopy(probe)
        rows, _, _ = ev.drive(RaisingAsset(), [], [probe])
        self.assertEqual(probe, before)
        self.assertEqual(rows[0]["score"], 0.0)

    def test_budget_and_leak_scoring_still_use_trusted_fields(self):
        class FixedAsset(EmptyAsset):
            def answer(self, query):
                query["budget"] = 1000
                query["must_not"] = []
                return "Oslo,Bergen"

        probes = [self.probe("budget", budget=4, must_not=[]),
                  self.probe("budget", budget=4, expect="Bergen", must_not=[]),
                  self.probe("budget", budget=4)]
        rows, _, _ = ev.drive(FixedAsset(), [], probes)
        self.assertEqual([row["score"] for row in rows], [1.0, 0.0, -0.5])

    def test_generated_schema_and_reference_asset_remain_compatible(self):
        class CheckedAsset:
            def __init__(self):
                self.asset = ev.load_asset(
                    ROOT / "tasks" / "life_model" / "lifemodel_v1")
                self.seen = []

            def __getattr__(self, name):
                return getattr(self.asset, name)

            def answer(self, query):
                self.seen.append(copy.deepcopy(query))
                return self.asset.answer(query)

        seen_types = set()
        for seed in (7, 301, 330):
            with self.subTest(seed=seed):
                records, probes, _, meta = ev.generate(seed)
                asset = CheckedAsset()
                rows, _, _ = ev.drive(asset, records, probes, meta)
                self.assertTrue(all(row["score"] == 1.0 for row in rows))
                public_probes = sorted(
                    [p for p in probes if not p.get("post_partial")],
                    key=lambda p: p["ckpt"])
                self.assertEqual(len(asset.seen), len(public_probes))
                for original, query in zip(public_probes, asset.seen):
                    self.assertEqual(set(original) - set(query),
                                     {"expect", "must_not"})
                    self.assertNotIn("expect", query)
                    self.assertNotIn("must_not", query)
                    self.assertEqual(query, ev.candidate_probe(original))
                    seen_types.add(query["type"])
        self.assertEqual(seen_types,
                         {"state", "stale", "prov", "subject", "as_of",
                          "ops", "drvprov", "duration", "nchange", "retract",
                          "cascade", "derive", "conf", "isconf", "first",
                          "order", "join", "absent", "window", "before",
                          "unans", "purpose", "revoked", "expdeny", "prov2",
                          "xcmp", "budget", "transfer"})

    def test_partial_export_and_import_failure_remain_evaluator_owned(self):
        class LifecycleAsset(EmptyAsset):
            calls = []

            def state(self, scope=None):
                return {"city": "Oslo"} if scope else {}

            def answer(self, query):
                self.calls.append(query)
                return "Oslo"

        asset = LifecycleAsset()
        ckpt = ev.CHECKPOINTS[1]
        probes = [self.probe(ckpt=ckpt, post_import=True),
                  self.probe("partial", ckpt=ckpt, post_partial=True)]
        meta = {"export_day": ev.CHECKPOINTS[0],
                "export_partial": {"day": ev.CHECKPOINTS[0] + 1,
                                   "slots": ["city"]}}
        rows, _, _ = ev.drive(asset, [], probes, meta)
        self.assertEqual(asset.calls, [])
        self.assertEqual([row["score"] for row in rows], [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
