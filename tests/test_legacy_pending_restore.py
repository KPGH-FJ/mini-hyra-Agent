"""Legacy fixture is actual LifeModel.state() from main 17bd657.

Generated offline by importing that commit's lifemodel package and ingesting:
{id: old-derived, day: 2, source: inference, kind: derived, slot: derived,
 value: D, supports: [late-support]}. No real data or model calls.
"""
import copy
import json
from pathlib import Path
import unittest

from lifemodel import LifeModel


FIXTURE = Path(__file__).parent / 'fixtures' / 'legacy_pending_main_17bd657.json'


class LegacyPendingRestoreTests(unittest.TestCase):
    def snapshot(self):
        return json.loads(FIXTURE.read_text())

    def test_actual_main_snapshot_restores_and_resolves_late_support(self):
        snapshot = self.snapshot()
        unchanged = copy.deepcopy(snapshot)
        model = LifeModel()
        model.import_state(snapshot)
        self.assertEqual(snapshot, unchanged)
        self.assertEqual(model.store._pending_drv, model.store._drv_log)
        roundtrip = LifeModel()
        roundtrip.import_state(model.state())
        for m in (model, roundtrip):
            m.ingest(dict(id='late-support', day=1, source='self',
                          kind='statement', slot='premise', value='A'))
            self.assertEqual(m.store.drv['derived']['value'], 'D')
            self.assertEqual(m.store._pending_drv, [])

    def test_legacy_pending_preserves_proven_entity_vertex(self):
        snapshot = self.snapshot()
        snapshot['hist']['inference|Alice|derived'] = snapshot['hist'].pop('inference|derived')
        snapshot['pending_drv'][0]['about'] = 'Alice'
        model = LifeModel()
        model.import_state(snapshot)
        self.assertEqual(model.store._drv_log[0]['vertex'], 'inference|Alice|derived')

    def test_malformed_or_ambiguous_pending_rejected_atomically(self):
        bad = []
        for key, value in [('kind', 'statement'), ('source', 'other'),
                           ('supports', 'late-support'), ('value', 'FAKE')]:
            snapshot = self.snapshot()
            snapshot['pending_drv'][0][key] = value
            bad.append(snapshot)
        snapshot = self.snapshot()
        snapshot['drv_log'].append(dict(snapshot['drv_log'][0], seq=1))
        bad.append(snapshot)
        snapshot = self.snapshot()
        snapshot['pending_drv'].append(copy.deepcopy(snapshot['pending_drv'][0]))
        bad.append(snapshot)
        snapshot = self.snapshot()
        snapshot['hist']['inference|Alice|derived'] = copy.deepcopy(snapshot['hist']['inference|derived'])
        bad.append(snapshot)
        snapshot = self.snapshot()
        snapshot['hist'].clear()
        bad.append(snapshot)
        for snapshot in bad:
            with self.subTest(snapshot=snapshot):
                model = LifeModel()
                model.ingest(dict(id='keep', day=9, source='self',
                                  kind='statement', slot='keep', value='KEEP'))
                before = copy.deepcopy(model.state())
                with self.assertRaises(ValueError):
                    model.import_state(snapshot)
                self.assertEqual(model.state(), before)

    def test_marked_snapshot_does_not_accept_legacy_queue_shape(self):
        model = LifeModel()
        model.import_state(self.snapshot())
        marked = copy.deepcopy(model.state())
        marked['pending_drv'] = self.snapshot()['pending_drv']
        with self.assertRaises(ValueError):
            LifeModel().import_state(marked)


if __name__ == '__main__':
    unittest.main()
