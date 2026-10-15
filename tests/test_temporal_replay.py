"""Synthetic contracts for temporal replay and arrival-order persistence.

Run under the audited offline wrapper with repo root in PYTHONPATH.
No generator, candidate, external model, or production state is used.
"""
import json
import copy
import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0, os.environ.get('LIFEMODEL_TEST_ROOT',
                                 str(Path(__file__).resolve().parents[1])))
from lifemodel import LifeModel


def rec(rid, day, slot, value, supports=None, kind='statement'):
    if supports is not None:
        kind = 'derived'
    return dict(id=rid, day=day, source='inference' if kind == 'derived' else 'self',
                kind=kind, slot=slot, value=value, supports=supports)


A = rec('a', 1, 'premise', 'A')
D = rec('d', 2, 'derived', 'D', ['a'])
B = rec('b', 3, 'premise', 'B', kind='correction')
RESTORED = rec('a2', 4, 'premise', 'A')


def feed(*records):
    model = LifeModel()
    for record in records:
        model.ingest(dict(record))
    return model


def answer(model, slot):
    return model.answer(dict(type='state', slot=slot, ckpt=20))


def document(model):
    return json.loads(json.dumps(model.state()))


def legacy(model):
    doc = document(model)
    for field in ('temporal_order_version', 'legacy_order', 'next_arrival_seq'):
        doc.pop(field, None)
    for edges in doc['hist'].values():
        for edge in edges:
            del edge[5:]
    for reg in ('drv_log', 'pending_drv'):
        for dev in doc[reg]:
            dev.pop('arrival_seq', None)
    return doc


def ambiguous_legacy():
    root = rec('root', 1, 'premise', 'A')
    d = rec('d', 5, 'derived', 'D', ['root'])
    b = rec(None, 5, 'premise', 'B', kind='correction')
    a = rec(None, 5, 'premise', 'A')
    c = rec(None, 6, 'premise', 'C', kind='correction')
    first, second = feed(root, d, b, a, c), feed(root, b, a, d, c)
    assert legacy(first) == legacy(second)
    return legacy(first)


class TemporalDesignContract(unittest.TestCase):
    def test_late_historical_killer_invalidates_existing_derived(self):
        model = feed(A, D, RESTORED, B)
        self.assertEqual(answer(model, 'premise'), 'A')
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_chronological_return_to_value_is_not_new_derivation(self):
        model = feed(A, D, B, RESTORED)
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_new_derivation_after_return_is_not_killed_by_old_divergence(self):
        fresh = rec('fresh', 5, 'derived', 'FRESH', ['a2'])
        model = feed(A, RESTORED, fresh, B)
        self.assertEqual(answer(model, 'derived'), 'FRESH')

    def test_child_born_after_killer_cannot_use_unreborn_parent(self):
        child = rec('child', 5, 'child', 'CHILD', ['d'])
        model = feed(A, D, RESTORED, child, B)
        self.assertEqual(answer(model, 'child'), '未知')

    def test_late_support_id_invalid_at_birth_is_not_resolved_at_final_value(self):
        late = rec('late', 2, 'premise', 'A')
        killer = rec('killer', 3, 'premise', 'B')
        d = rec('d', 4, 'derived', 'D', ['late'])
        restored = rec('restore', 5, 'premise', 'A')
        model = feed(killer, d, restored, late)
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_new_parent_after_return_can_support_new_child(self):
        fresh = rec('fresh', 5, 'derived', 'FRESH', ['a2'])
        child = rec('child', 6, 'child', 'CHILD', ['fresh'])
        model = feed(A, D, RESTORED, fresh, child, B)
        self.assertEqual(answer(model, 'derived'), 'FRESH')
        self.assertEqual(answer(model, 'child'), 'CHILD')

    def test_import_before_late_killer_retains_temporal_meaning(self):
        model = feed(A, D, RESTORED)
        restored = LifeModel()
        restored.import_state(json.loads(json.dumps(model.state())))
        restored.ingest(B)
        self.assertEqual(answer(restored, 'derived'), '未知')

    def test_noop_range_erase_does_not_resurrect_remaining_killer(self):
        model = feed(A, D, B, RESTORED)
        self.assertEqual(answer(model, 'derived'), '未知')
        model.forget(dict(day_gte=100, day_lte=101))
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_erasing_actual_killer_can_revive_surviving_derivation(self):
        model = feed(A, D, B, RESTORED)
        model.forget(dict(day_gte=3, day_lte=3))
        self.assertEqual(answer(model, 'derived'), 'D')

    def test_erasing_derivation_itself_cannot_revive_it(self):
        model = feed(A, D, B, RESTORED)
        model.forget(dict(day_gte=2, day_lte=3))
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_same_day_birth_order_survives_import_and_erasure(self):
        root = rec('root', 1, 'premise', 'A')
        d = rec('d', 5, 'derived', 'D', ['root'])
        b = rec(None, 5, 'premise', 'B', kind='correction')
        a = rec(None, 5, 'premise', 'A')
        c = rec(None, 6, 'premise', 'C', kind='correction')
        for records, expected in [((root, d, b, a, c), '未知'),
                                  ((root, b, a, d, c), 'D')]:
            with self.subTest(expected=expected):
                model = feed(*records)
                restored = LifeModel()
                restored.import_state(document(model))
                restored.forget(dict(day_gte=6, day_lte=6))
                self.assertEqual(answer(restored, 'derived'), expected)

    def test_same_day_non_authoritative_support_resolution_is_preserved(self):
        root = rec('root', 1, 'premise', 'A')
        support = dict(rec('doc', 5, 'premise', 'A'), source='doc')
        d = rec('d', 5, 'derived', 'D', ['doc'])
        b = rec('b', 5, 'premise', 'B', kind='correction')
        a = rec('a', 5, 'premise', 'A')
        c = rec('c', 6, 'premise', 'C', kind='correction')
        for records, expected in [((root, support, d, b, a, c), '未知'),
                                  ((root, d, b, a, support, c), 'D')]:
            with self.subTest(expected=expected):
                model = feed(*records)
                model.forget(dict(day_gte=6, day_lte=6))
                self.assertEqual(answer(model, 'derived'), expected)

    def test_legacy_distinct_days_replay_without_inventing_order(self):
        model = LifeModel()
        model.import_state(legacy(feed(A, D, RESTORED)))
        model.ingest(B)
        self.assertEqual(answer(model, 'derived'), '未知')
        self.assertEqual(len(model.store.hist['self|premise'][0]), 5)
        self.assertTrue(model.state()['legacy_order'])

    def test_legacy_unique_record_dates_restore_future_support_gate(self):
        doc = legacy(feed(rec('future', 40, 'premise', 'A')))
        doc.pop('rday')
        model = LifeModel()
        model.import_state(doc)
        model.ingest(rec('invalid', 10, 'derived', 'INVALID', ['future']))
        self.assertEqual(answer(model, 'derived'), '未知')
        self.assertEqual(model.store._rday['future'], 40)

    def test_legacy_missing_log_rejects_affected_mutation_atomically(self):
        doc = legacy(feed(A, D, RESTORED))
        doc['drv_log'] = []
        for operation in (lambda m: m.ingest(B),
                          lambda m: m.forget({'slot': 'premise'})):
            model = LifeModel()
            model.import_state(copy.deepcopy(doc))
            before, clock = document(model), model.control._day
            with self.assertRaisesRegex(ValueError, 'missing derived birth'):
                operation(model)
            self.assertEqual(document(model), before)
            self.assertEqual(model.control._day, clock)

    def test_legacy_missing_log_can_delete_all_relevant_history(self):
        doc = legacy(feed(A, D, RESTORED))
        doc['drv_log'] = []
        model = LifeModel()
        model.import_state(doc)
        model.forget({'day_gte': 0, 'day_lte': 100})
        self.assertEqual(model.store.hist, {})
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_unreferenced_entity_and_doc_slot_deletions_are_not_owner_updates(self):
        root = rec('root', 1, 'premise', 'A')
        b = rec(None, 5, 'premise', 'B', kind='correction')
        a = rec(None, 5, 'premise', 'A')
        d = rec('d', 5, 'derived', 'D', ['root'])
        for fields, scope in [({'about': 'Alice'}, {'about': 'Alice'}),
                              ({'source': 'doc'}, {'day_gte': 7, 'day_lte': 7})]:
            source = feed(root, b, a, d, dict(rec('other', 7, 'premise', 'OTHER'), **fields))
            model = LifeModel()
            model.import_state(legacy(source))
            model.forget(scope)
            self.assertEqual(answer(model, 'derived'), 'D')

    def test_legacy_ambiguous_erasure_is_atomic(self):
        model = LifeModel()
        model.import_state(ambiguous_legacy())
        before, clock, drv_seq = document(model), model.control._day, model.store._drv_seq
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            model.forget(dict(day_gte=6, day_lte=6))
        self.assertEqual(document(model), before)
        self.assertEqual(model.control._day, clock)
        self.assertEqual(model.store._drv_seq, drv_seq)

    def test_erasing_all_ambiguous_events_is_allowed(self):
        model = LifeModel()
        model.import_state(ambiguous_legacy())
        model.forget(dict(day_gte=5, day_lte=6))
        self.assertEqual(answer(model, 'derived'), '未知')
        self.assertEqual(answer(model, 'premise'), 'A')

    def test_slot_erasure_removes_ambiguous_dependency_closure(self):
        model = LifeModel()
        model.import_state(ambiguous_legacy())
        model.forget(dict(slot='premise'))
        self.assertEqual(answer(model, 'derived'), '未知')
        self.assertEqual(model.store._drv_log, [])

    def test_unrelated_legacy_ambiguity_does_not_block_mutation(self):
        model = LifeModel()
        model.import_state(ambiguous_legacy())
        model.ingest(rec('unrelated', 2, 'other', 'KEEP'))
        model.forget(dict(slot='other'))
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_confluent_legacy_ties_are_allowed(self):
        model = LifeModel()
        model.import_state(ambiguous_legacy())
        # Replaying still includes the common final killer: all legal
        # old orders agree, so missing metadata alone is not a rejection.
        model.ingest(rec('repeat', 2, 'premise', 'A'))
        self.assertEqual(answer(model, 'derived'), '未知')

    def test_explicit_output_and_unrelated_facts_survive(self):
        model = feed(A, D, rec('own', 4, 'derived', 'OWNER'), RESTORED,
                     rec('safe', 5, 'other', 'SAFE'), B)
        self.assertEqual(answer(model, 'derived'), 'OWNER')
        self.assertEqual(answer(model, 'other'), 'SAFE')

    def test_late_non_authoritative_and_entity_records_do_not_kill(self):
        for fields in ({'source': 'doc'}, {'source': 'self', 'about': 'Alice'}):
            model = feed(A, D, RESTORED)
            model.ingest(dict(B, **fields))
            self.assertEqual(answer(model, 'derived'), 'D')

    def test_late_same_value_is_not_divergence(self):
        model = feed(A, D, RESTORED, dict(B, value='A'))
        self.assertEqual(answer(model, 'derived'), 'D')

    def test_repeated_no_id_same_value_births_have_exact_erasure_identity(self):
        model = feed(rec('p', 1, 'private', 'P'), rec('q', 1, 'public', 'Q'),
                     rec(None, 2, 'plan', 'SAME', ['p']),
                     rec(None, 2, 'plan', 'SAME', ['q']))
        survivor_seq = model.store._drv_log[-1]['arrival_seq']
        model.forget(dict(slot='private'))
        self.assertEqual(answer(model, 'plan'), 'SAME')
        self.assertEqual(model.store.hist['inference|plan'][0][5], survivor_seq)
        self.assertEqual(model.store._drv_log[0]['supports'], ['q'])

    def test_sequence_high_water_survives_erasing_every_edge_and_import(self):
        model = feed(A, D)
        next_seq = model.state()['next_arrival_seq']
        model.forget(dict(day_gte=0, day_lte=100))
        restored = LifeModel()
        restored.import_state(document(model))
        restored.ingest(rec('new', 10, 'new', 'VALUE'))
        self.assertEqual(restored.store.hist['self|new'][0][5], next_seq)

    def test_duplicate_id_range_erasure_restores_surviving_cache(self):
        model = feed(rec('same', 1, 'premise', 'A'),
                     rec('same', 2, 'premise', 'B'))
        model.forget({'day_gte': 2, 'day_lte': 2})
        restored = LifeModel()
        restored.import_state(document(model))
        self.assertEqual(answer(restored, 'premise'), 'A')
        self.assertEqual(restored.store.rsv['same'], ('premise', 'A'))
        self.assertEqual(restored.store._rday['same'], 1)

    def test_erased_noise_clock_can_revive_a_leased_derivation(self):
        root = dict(A, expires_day=4)
        noise = dict(rec('noise', 5, 'noise', 'CLOCK'), source='doc')
        renew = dict(rec('renew', 5, 'premise', 'A'), expires_day=10)
        model = feed(root, D, noise, renew)
        self.assertEqual(model.store.drv, {})
        model.forget({'slot': 'noise'})
        self.assertEqual(model.answer({'type': 'state', 'slot': 'derived', 'ckpt': 6}), 'D')

    def test_legacy_clock_compression_preserves_legal_first_events(self):
        root = dict(rec('p', 1, 'p', 'A'), expires_day=4)
        q = rec('q', 1, 'q', 'X')
        d = rec('d', 2, 'd', 'D', ['p', 'q'])
        clock = rec('clock', 5, 'p', 'noise', kind='suggestion')
        renew = dict(rec('renew', 5, 'p', 'A'), expires_day=10)
        other = rec('other', 5, 'q', 'X')
        model = LifeModel()
        model.import_state(legacy(feed(root, q, d, clock, renew, other)))
        model.ingest(rec('late', 3, 'p', 'A'))
        self.assertEqual(answer(model, 'd'), '未知')

    def test_scoped_sequence_rebasing_is_private_and_non_mutating(self):
        model = feed(rec('hidden', 1, 'private', 'SECRET'), A, D,
                     rec('tail', 5, 'private', 'LATER'))
        before = document(model)
        scoped = json.loads(json.dumps(model.state(scope={'slots': ['premise', 'derived']})))
        self.assertEqual(document(model), before)
        self.assertEqual(scoped['next_arrival_seq'], 2)
        self.assertEqual(sorted(e[5] for edges in scoped['hist'].values()
                                for e in edges), [0, 1])
        restored = LifeModel()
        restored.import_state(scoped)
        restored.ingest(RESTORED)
        restored.ingest(B)
        self.assertEqual(answer(restored, 'derived'), '未知')
        self.assertEqual(model.state(scope={'slots': []}), model.state())
        model.revoke_purpose('blocked')
        self.assertEqual(model.state(scope={'purpose': 'blocked'}), {})

    def test_scoped_duplicate_id_caches_are_rebuilt_from_exported_history(self):
        model = feed(rec('same', 1, 'public', 'SAFE'),
                     rec('same', 2, 'private', 'OUT_OF_SCOPE'))
        before = document(model)
        scoped = model.state(scope={'slots': ['public']})
        self.assertNotIn('OUT_OF_SCOPE', json.dumps(scoped))
        self.assertEqual(scoped['rsv']['same'], ('public', 'SAFE'))
        self.assertEqual(scoped['rday']['same'], 1)
        restored = LifeModel()
        restored.import_state(json.loads(json.dumps(scoped)))
        self.assertEqual(answer(restored, 'public'), 'SAFE')
        self.assertEqual(document(model), before)

    def test_corrupt_new_schema_rejects_import_atomically(self):
        source = feed(A, D)
        doc = document(source)
        mutations = {
            'unknown_version': lambda d: d.update(temporal_order_version=99),
            'bool_version': lambda d: d.update(temporal_order_version=True),
            'bool_sequence': lambda d: d['hist']['self|premise'][0].__setitem__(5, True),
            'duplicate_sequence': lambda d: d['hist']['inference|derived'][0].__setitem__(5, 0),
            'missing_sequence': lambda d: d['hist']['self|premise'][0].pop(),
            'bad_high_water': lambda d: d.update(next_arrival_seq=1),
            'missing_high_water': lambda d: d.pop('next_arrival_seq'),
            'missing_log_sequence': lambda d: d['drv_log'][0].pop('arrival_seq'),
            'missing_entire_log': lambda d: d.update(drv_log=[]),
            'duplicate_birth': lambda d: d['drv_log'].append(dict(d['drv_log'][0])),
            'wrong_birth_slot': lambda d: d['drv_log'][0].update(slot='wrong'),
            'wrong_birth_source': lambda d: d['drv_log'][0].update(src='wrong'),
            'mismatched_log_sequence': lambda d: d['drv_log'][0].update(arrival_seq=0),
            'false_pending': lambda d: d['pending_drv'].append(dict(d['drv_log'][0], value='WRONG')),
            'missing_record_dates': lambda d: d.pop('rday'),
            'false_record_date': lambda d: d['rday'].update(a=0),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                bad = copy.deepcopy(doc)
                mutate(bad)
                target = feed(rec('keep', 30, 'kept', 'KEEP'))
                before, clock = document(target), target.control._day
                with self.assertRaises(ValueError):
                    target.import_state(bad)
                self.assertEqual(document(target), before)
                self.assertEqual(target.control._day, clock)

    def test_facade_clock_advances_only_after_successful_append(self):
        model = feed(A)
        before, clock = document(model), model.control._day
        original = model.store.append
        def reject(_event):
            raise ValueError('synthetic rejection')
        model.store.append = reject
        with self.assertRaises(ValueError):
            model.ingest(rec('bad', 100, 'bad', 'BAD'))
        model.store.append = original
        self.assertEqual(document(model), before)
        self.assertEqual(model.control._day, clock)
        model.correct('premise', 'CORRECT')
        self.assertEqual(model.store.hist['self|premise'][-1][1], clock)


if __name__ == '__main__':
    unittest.main(verbosity=2)
