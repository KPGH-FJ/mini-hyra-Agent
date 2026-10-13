"""Synthetic regressions for the pinned memory-control contracts.

Run directly: python tests/test_memory_controls_regressions.py
No external data, model calls, network, or candidate imports are used.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.environ.get("LIFEMODEL_TEST_ROOT",
                                 str(Path(__file__).resolve().parents[1])))
from lifemodel import LifeModel


def record(day, slot, value, **fields):
    return dict(day=day, slot=slot, value=value,
                source=fields.pop("source", "self"),
                kind=fields.pop("kind", "statement"), **fields)


def state_answer(model, slot, **fields):
    return model.answer(dict(type="state", slot=slot, ckpt=100, **fields))


def serialized(model):
    return json.dumps(model.state(), ensure_ascii=False, sort_keys=True)


class MemoryControlRegressions(unittest.TestCase):
    def test_forget_slot_erases_all_vertices_and_record_registries(self):
        m = LifeModel()
        for i, (source, about) in enumerate([
                ("self", None), ("friend", None),
                ("self", "Alice"), ("friend", "Alice")]):
            m.ingest(record(i + 1, "city", f"PRIVATE_CITY_{i}",
                            source=source, about=about, id=f"city-{i}"))
        m.ingest(record(5, "job", "preserved", id="keep"))
        m.forget({"slot": "city"})
        doc = serialized(m)
        for i in range(4):
            self.assertNotIn(f"PRIVATE_CITY_{i}", doc)
            self.assertNotIn(f"city-{i}", m.store.rsv)
            self.assertNotIn(f"city-{i}", m.store._rday)
        self.assertEqual(state_answer(m, "city", about="Alice"), "未知")
        self.assertEqual(state_answer(m, "job"), "preserved")

    def test_forget_slot_cascades_erased_record_dependencies(self):
        m = LifeModel()
        m.ingest(record(1, "creed", "PRIVATE_ROOT", id="root"))
        m.ingest(record(2, "habit", "PRIVATE_DERIVED", source="inference",
                        kind="derived", id="child", supports=["root"]))
        m.ingest(record(3, "plan", "PRIVATE_CHAIN", source="inference",
                        kind="derived", supports=["child"]))
        m.ingest(record(4, "habit", "explicit_survivor", kind="correction",
                        id="explicit"))
        m.forget({"slot": "creed"})
        doc = serialized(m)
        for value in ("PRIVATE_ROOT", "PRIVATE_DERIVED", "PRIVATE_CHAIN"):
            self.assertNotIn(value, doc)
        self.assertEqual(state_answer(m, "habit"), "explicit_survivor")
        self.assertEqual(state_answer(m, "plan"), "未知")
        m.ingest(record(5, "creed", "PRIVATE_ROOT", id="new-root"))
        self.assertEqual(state_answer(m, "plan"), "未知")

    def test_forget_slot_retains_audit_operation_but_not_corrected_value(self):
        m = LifeModel()
        m.ingest(record(1, "city", "old"))
        m.correct("city", "PRIVATE_CORRECTION")
        m.forget({"slot": "city"})
        self.assertNotIn("PRIVATE_CORRECTION", serialized(m))
        self.assertEqual(m.answer(dict(type="ops", slot="_audit",
                                      op="correct")), "city")

    def test_forget_slot_preserves_independent_same_slot_derivation(self):
        m = LifeModel()
        m.ingest(record(1, "private", "erase", id="private"))
        m.ingest(record(1, "public", "keep", id="public"))
        m.ingest(record(2, "plan", "PRIVATE_PLAN", source="inference",
                        kind="derived", id="d1", supports=["private"]))
        m.ingest(record(3, "plan", "SAFE_PLAN", source="inference",
                        kind="derived", id="d2", supports=["public"]))
        m.forget({"slot": "private"})
        self.assertEqual(state_answer(m, "plan"), "SAFE_PLAN")
        self.assertNotIn("PRIVATE_PLAN", serialized(m))
        self.assertIn("d2", m.store.rsv)

    def test_forget_slot_erases_pending_dependent(self):
        m = LifeModel()
        m.ingest(record(1, "private", "PRIVATE_ROOT", id="private"))
        m.ingest(record(2, "plan", "PRIVATE_PENDING", source="inference",
                        kind="derived", id="pending",
                        supports=["private", "not-arrived"]))
        m.forget({"slot": "private"})
        self.assertNotIn("PRIVATE_PENDING", serialized(m))
        self.assertEqual(m.store._pending_drv, [])

    def test_forget_slot_erases_identified_entity_derived_descendant(self):
        m = LifeModel()
        m.ingest(record(1, "private", "PRIVATE_ROOT", id="private"))
        m.ingest(record(2, "plan", "PRIVATE_ENTITY_DERIVED", source="inference",
                        kind="derived", id="entity-derived", about="Alice",
                        supports=["private"]))
        m.ingest(record(3, "plan", "UNRELATED_ENTITY", about="Bob", id="bob"))
        m.forget({"slot": "private"})
        self.assertNotIn("PRIVATE_ENTITY_DERIVED", serialized(m))
        self.assertEqual(state_answer(m, "plan", about="Bob"),
                         "UNRELATED_ENTITY")

    def test_unique_no_id_entity_dependency_is_not_assumed_self_domain(self):
        m = LifeModel()
        m.ingest(record(1, "private", "PRIVATE_ROOT", id="private"))
        m.ingest(record(2, "plan", "PRIVATE_ENTITY_DERIVED", source="inference",
                        kind="derived", about="Alice", supports=["private"]))
        m.forget({"slot": "private"})
        self.assertNotIn("PRIVATE_ENTITY_DERIVED", serialized(m))

    def test_legacy_no_id_entity_dependency_refuses_without_partial_mutation(self):
        m = LifeModel()
        m.ingest(record(1, "private", "private", id="p"))
        m.ingest(record(1, "public", "public", id="q"))
        m.ingest(record(2, "plan", "SAFE", source="inference", kind="derived",
                        about="Alice", supports=["p"]))
        m.ingest(record(2, "plan", "SAFE", source="inference", kind="derived",
                        supports=["q"]))
        for event in m.store._drv_log:
            event.pop("vertex", None)  # simulate the previous snapshot schema
        before = serialized(m)
        with self.assertRaisesRegex(ValueError, "ambiguous derived event"):
            m.forget({"slot": "private"})
        self.assertEqual(serialized(m), before)
        self.assertEqual(state_answer(m, "plan"), "SAFE")

    def test_no_id_entity_forget_cannot_erase_a_later_independent_edge(self):
        m = LifeModel()
        m.ingest(record(1, "private", "private", id="p"))
        m.ingest(record(1, "public", "public", id="q"))
        m.ingest(record(2, "plan", "SAFE", source="inference", kind="derived",
                        about="Alice", supports=["p"]))
        m.forget({"about": "Alice"})
        m.ingest(record(2, "plan", "SAFE", source="inference", kind="derived",
                        supports=["q"]))
        m.forget({"slot": "private"})
        self.assertEqual(state_answer(m, "plan"), "SAFE")
        self.assertNotIn("inference|Alice|plan", m.store.hist)

    def test_scoped_logs_do_not_export_new_entity_vertex_metadata(self):
        m = LifeModel()
        m.ingest(record(1, "plan", "ordinary", id="owner"))
        m.ingest(record(2, "plan", "ENTITY_PRIVATE", source="inference",
                        kind="derived", about="PRIVATE_PERSON", supports=["missing"]))
        text = json.dumps(m.state({"slots": ["plan"]}))
        self.assertNotIn("PRIVATE_PERSON", text)
        self.assertNotIn("ENTITY_PRIVATE", text)

    def test_forget_about_cleans_registries_and_keeps_alias_resolution(self):
        m = LifeModel()
        m.ingest(record(1, "Al", "Alice", source="system", kind="alias"))
        m.ingest(record(2, "city", "OWNER_CITY", id="owner"))
        m.ingest(record(3, "city", "PRIVATE_ALICE", about="Alice", id="a1"))
        m.ingest(record(4, "city", "PRIVATE_HEARSAY", about="Al",
                        source="friend", kind="hearsay", id="a2"))
        m.ingest(record(4, "city", "OTHER_ENTITY", about="Bob", id="bob"))
        m.forget({"about": "Al"})
        doc = serialized(m)
        self.assertNotIn("PRIVATE_ALICE", doc)
        self.assertNotIn("PRIVATE_HEARSAY", doc)
        self.assertNotIn("a1", m.store.rsv)
        self.assertNotIn("a2", m.store._rday)
        self.assertEqual(state_answer(m, "city"), "OWNER_CITY")
        self.assertEqual(state_answer(m, "city", about="Bob"), "OTHER_ENTITY")
        self.assertEqual(m.store.aliases, {"Al": "Alice"})
        m.ingest(record(5, "city", "new_entity_value", about="Al", id="a3"))
        self.assertEqual(state_answer(m, "city", about="Alice"),
                         "new_entity_value")

    def test_scoped_export_drops_derivation_with_out_of_scope_premise(self):
        m = LifeModel()
        m.ingest(record(1, "city", "PRIVATE_CITY", id="city"))
        m.ingest(record(2, "plan", "take transit", source="inference",
                        kind="derived", id="plan", supports=["city"]))
        scoped = m.state({"slots": ["plan"]})
        self.assertNotIn("PRIVATE_CITY", json.dumps(scoped))
        self.assertNotIn("plan", scoped["drv"])
        restored = LifeModel()
        restored.import_state(json.loads(json.dumps(scoped)))
        self.assertEqual(state_answer(restored, "plan"), "未知")
        self.assertEqual(state_answer(m, "plan"), "take transit")

    def test_scoped_export_preserves_in_scope_derivation(self):
        m = LifeModel()
        m.ingest(record(1, "city", "public city", id="city"))
        m.ingest(record(2, "plan", "take transit", source="inference",
                        kind="derived", id="plan", supports=["city"]))
        restored = LifeModel()
        restored.import_state(json.loads(json.dumps(
            m.state({"slots": ["city", "plan"]}))))
        self.assertEqual(state_answer(restored, "plan"), "take transit")

    def test_correct_after_fresh_import_uses_restored_clock(self):
        m = LifeModel()
        m.ingest(record(40, "city", "old", id="old"))
        restored = LifeModel()
        restored.import_state(json.loads(serialized(m)))
        restored.correct("city", "new")
        self.assertEqual(state_answer(restored, "city"), "new")
        self.assertEqual(restored.store.hist["self|city"][-1][1], 40)

    def test_import_replaces_previous_control_clock(self):
        snapshot = LifeModel()
        snapshot.ingest(record(40, "city", "saved"))
        m = LifeModel()
        m.ingest(record(90, "city", "discarded"))
        m.import_state(json.loads(serialized(snapshot)))
        m.correct("city", "new")
        self.assertEqual(m.store.hist["self|city"][-1][1], 40)

    def test_future_premise_rejected_in_both_arrival_orders(self):
        premise = record(40, "city", "future", id="premise")
        derived = record(10, "plan", "INVALID", source="inference",
                         kind="derived", id="derived", supports=["premise"])
        for ordering in ((premise, derived), (derived, premise)):
            with self.subTest(ordering=ordering):
                m = LifeModel()
                for event in ordering:
                    m.ingest(event)
                self.assertEqual(state_answer(m, "plan"), "未知")

    def test_earlier_premise_resolves_when_delivered_late(self):
        m = LifeModel()
        m.ingest(record(10, "plan", "VALID", source="inference",
                        kind="derived", supports=["premise"]))
        m.ingest(record(5, "city", "existing", id="premise"))
        self.assertEqual(state_answer(m, "plan"), "VALID")

    def test_same_slot_supports_cannot_hide_future_record_day(self):
        m = LifeModel()
        m.ingest(record(40, "city", "same", id="future"))
        m.ingest(record(5, "city", "same", id="past"))
        m.ingest(record(10, "plan", "INVALID", source="inference",
                        kind="derived", supports=["future", "past"]))
        self.assertEqual(state_answer(m, "plan"), "未知")

    def test_same_day_and_no_supports_do_not_crash(self):
        m = LifeModel()
        m.ingest(record(5, "city", "same", id="same-day"))
        m.ingest(record(5, "plan", "VALID", source="inference",
                        kind="derived", supports=["same-day"]))
        m.ingest(record(5, "unconditional", "UNCHANGED", source="inference",
                        kind="derived"))
        self.assertEqual(state_answer(m, "plan"), "VALID")
        self.assertEqual(state_answer(m, "unconditional"), "UNCHANGED")

    def test_deletion_preserves_arrival_order_for_later_same_day_events(self):
        m = LifeModel()
        m.ingest(record(1, "private", "erase", id="private"))
        m.ingest(record(1, "public", "keep", id="public"))
        for i in range(3):
            m.ingest(record(2, f"discard-{i}", f"discard-{i}",
                            source="inference", kind="derived", id=f"d{i}",
                            supports=["private"]))
        m.ingest(record(5, "plan", "EARLIER", source="inference",
                        kind="derived", id="old-plan", supports=["public"]))
        m.forget({"slot": "private"})
        m.ingest(record(5, "plan", "LATER", source="inference",
                        kind="derived", id="new-plan", supports=["public"]))
        m.forget({"day_gte": 999, "day_lte": 999})  # rebuild surviving log
        self.assertEqual(state_answer(m, "plan"), "LATER")

    def test_derived_append_does_not_rescan_the_event_log_for_sequence(self):
        class CountIterations(list):
            iterations = 0
            def __iter__(self):
                self.iterations += 1
                return super().__iter__()
        m = LifeModel()
        m.store._drv_log = CountIterations()
        for i in range(10):
            m.ingest(record(1, "plan", str(i), source="inference",
                            kind="derived"))
        self.assertEqual(m.store._drv_log.iterations, 0)

    def test_range_erasure_still_revives_derived_after_killer_removed(self):
        m = LifeModel()
        m.ingest(record(1, "creed", "daily", id="root"))
        m.ingest(record(2, "habit", "VALID", source="inference",
                        kind="derived", id="child", supports=["root"]))
        m.ingest(record(5, "creed", "rarely", id="killer"))
        self.assertEqual(state_answer(m, "habit"), "未知")
        m.forget({"day_gte": 5, "day_lte": 5})
        self.assertEqual(state_answer(m, "habit"), "VALID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
