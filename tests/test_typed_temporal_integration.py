"""Offline cross-feature contracts for typed registries and temporal replay."""
import copy
import unittest

from lifemodel import LifeModel


def rec(rid, day, slot, value, supports=None, **extra):
    out = dict(id=rid, day=day, slot=slot, value=value,
               source='inference' if supports is not None else 'self',
               kind='derived' if supports is not None else 'statement',
               supports=supports, typed={'verb': 'record', 'object': value})
    out.update(extra)
    return out


def feed(*records):
    model = LifeModel()
    for record in records:
        model.ingest(record)
    return model


class TypedTemporalIntegrationTests(unittest.TestCase):
    def test_permanent_slot_purge_cleans_transitive_frames_only(self):
        model = feed(rec('a', 1, 'p', 'A'),
                     rec('d', 2, 'q', 'D', ['a']),
                     rec('child', 3, 'child', 'C', ['d']),
                     rec('independent', 4, 'q', 'USER'))
        model.store.forget_slot('p')
        self.assertEqual(set(model.store.typed), {'independent'})
        self.assertEqual(set(model.store.rsv), {'independent'})
        self.assertEqual(model.store.live('q'), 'USER')
        restored = LifeModel()
        restored.import_state(model.state())
        self.assertEqual(restored.store.typed, model.store.typed)

    def test_person_purge_cleans_dependent_frames(self):
        model = feed(rec('a', 1, 'p', 'A', about='Alice'),
                     rec('d', 2, 'q', 'D', ['a']),
                     rec('keep', 3, 'keep', 'KEEP'))
        model.store.forget_about('Alice')
        self.assertEqual(set(model.store.typed), {'keep'})
        self.assertNotIn('d', model.store.rsv)

    def test_late_replay_and_range_revival_preserve_survivor_frames(self):
        model = feed(rec('a', 1, 'p', 'A'), rec('d', 2, 'q', 'D', ['a']),
                     rec('return', 4, 'p', 'A'), rec('killer', 3, 'p', 'B'))
        self.assertNotIn('q', model.store.drv)
        self.assertIn('d', model.store.typed)
        model.store.forget_range(3, 3)
        self.assertEqual(model.store.drv['q']['value'], 'D')
        self.assertEqual(set(model.store.typed), {'a', 'd', 'return'})
        scoped = model.state({'slots': ['p', 'q']})
        restored = LifeModel()
        restored.import_state(scoped)
        self.assertEqual(restored.store.typed, model.store.typed)
        self.assertEqual(restored.store.drv, model.store.drv)

    def test_scoped_reused_id_does_not_export_excluded_frame(self):
        model = feed(rec('same', 1, 'public', 'PUBLIC'),
                     rec('same', 2, 'secret', 'SECRET'))
        before = copy.deepcopy(model.state())
        scoped = model.state({'slots': ['public']})
        self.assertNotIn('same', scoped['typed'])
        self.assertNotIn('SECRET', str(scoped))
        self.assertEqual(model.state(), before)
        restored = LifeModel()
        restored.import_state(scoped)
        self.assertEqual(restored.store.rsv['same'], ('public', 'PUBLIC'))
        self.assertEqual(restored.store.typed, {})

    def test_reused_untyped_id_drops_old_frame(self):
        model = feed(rec('same', 1, 'p', 'OLD'),
                     rec('same', 2, 'q', 'NEW', typed=None))
        self.assertNotIn('same', model.store.typed)

    def test_reused_id_and_erasure_do_not_invent_old_frame(self):
        model = feed(rec('same', 1, 'public', 'PUBLIC'),
                     rec('same', 2, 'secret', 'SECRET'))
        self.assertNotIn('same', model.store.typed)
        model.store.forget_range(2, 2)
        self.assertEqual(model.store.rsv['same'], ('public', 'PUBLIC'))
        self.assertNotIn('same', model.store.typed)

    def test_restore_discards_ambiguous_and_orphan_typed_caches(self):
        model = feed(rec('same', 1, 'public', 'PUBLIC'),
                     rec('same', 2, 'secret', 'SECRET'),
                     rec('unique', 3, 'unique', 'KEEP'))
        state = copy.deepcopy(model.state())
        state['typed']['same'] = {'object': 'SECRET'}
        state['typed']['orphan'] = {'object': 'ORPHAN'}
        restored = LifeModel()
        restored.import_state(state)
        self.assertEqual(set(restored.store.typed), {'unique'})

    def test_failed_restore_keeps_frames_atomic(self):
        model = feed(rec('a', 1, 'p', 'A'))
        before = copy.deepcopy(model.state())
        bad = copy.deepcopy(before)
        bad['temporal_order_version'] = 99
        bad['typed'] = {'secret': {'object': 'INVALID'}}
        with self.assertRaises(ValueError):
            model.import_state(bad)
        self.assertEqual(model.state(), before)


if __name__ == '__main__':
    unittest.main()
