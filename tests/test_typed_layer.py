"""Offline regressions for the opt-in typed-record layer. No model/network calls."""
import asyncio
import copy
from datetime import date
import json
import unittest
from unittest.mock import AsyncMock, patch
from lifemodel import LifeModel
from lifemodel.ingest_llm import LLMIngestor
from lifemodel.reader import _spec_aggregate, aanswer
from lifemodel.typed_agg import answer_with_spec, resolve_dups, valid_spec_shape


def frame(**kw):
    out = dict(event_id='event', kind='asserted', verb='visit', object='doctor',
               object_class=None, quantity=None, quantifier=None, when_abs=None,
               granularity=None, duration_value=None, duration_unit=None,
               obligation_status=None, counterparty=None, location=None)
    out.update(kw)
    return out


def ingest(m, rid, **kw):
    r = dict(id=rid, day=date(2026, 1, 10).toordinal(), source='self',
             kind='statement', slot=rid, value=rid, typed=frame())
    r.update(kw)
    m.ingest(r)


class Stub:
    def __init__(self, *values):
        self.values = iter(values)
        self.prompts = []
    async def complete(self, system, prompt):
        self.prompts.append(prompt)
        return json.dumps(next(self.values))


class AggregationTests(unittest.TestCase):
    def answer(self, typed, **kw):
        return answer_with_spec(dict(op='count_events', **kw), typed)['answer']

    def test_selectors_preserved_including_null(self):
        self.assertEqual(self.answer({'a': frame(location='Paris'), 'b': frame()},
                                     location=['Paris']), 1)

    def test_no_spec_mutation(self):
        s = {'op': 'count_events', 'location': ['Paris']}
        before = copy.deepcopy(s)
        answer_with_spec(s, {'a': frame(location='Paris')})
        self.assertEqual(s, before)

    def test_duplicate_filter_before_representative(self):
        self.assertEqual(self.answer({'a': frame(verb='diagnose', dup_links=['b']),
                                      'b': frame(verb='visit')}, verbs=['visit']), 1)

    def test_duplicate_transitive_date_conflict(self):
        rs = [dict(rid='a', when_abs='2026-01-01', dup_links=['b']),
              dict(rid='b', when_abs=None, dup_links=['c']),
              dict(rid='c', when_abs='2026-01-02')]
        self.assertEqual(len(resolve_dups(rs)), 2)

    def test_unknown_distinct_not_counted(self):
        self.assertEqual(answer_with_spec({'op': 'count_distinct'},
                         {'a': frame(), 'b': frame(object=None)})['answer'], 1)

    def test_exact_counterparty(self):
        self.assertEqual(self.answer({'a': frame(counterparty='Ann'),
                                      'b': frame(counterparty='Anna')},
                                     counterparties=['Ann']), 1)

    def test_any_of_common_window(self):
        typed = {'a': frame(when_abs='2025-01-01'),
                 'b': frame(when_abs='2026-01-01')}
        self.assertEqual(self.answer(typed, window={'kind': 'year', 'year': 2025},
                                     any_of=[{'verbs': ['visit']}]), 1)

    def test_missing_quantity_never_becomes_duration_or_zero(self):
        for typed in ({'a': frame(duration_value=3, duration_unit='days')},
                      {'a': frame(quantity=3), 'b': frame()}):
            self.assertIsNone(answer_with_spec({'op':'sum', 'field':'quantity'}, typed)['answer'])

    def test_duration_sum(self):
        self.assertEqual(answer_with_spec({'op':'sum', 'field':'duration_hours'},
                         {'a': frame(duration_value=3, duration_unit='days')})['answer'], 72)

    def test_invalid_spec_is_safe(self):
        for spec in ([], {'op':[]}, {'op':'sum','field':[]}, {'op':'sum', 'field':'object'},
                     {'op':'count_events','window':{'kind':'past_days'}},
                     {'op':'count_events','verbs':[{}]},
                     {'op':'count_events','any_of':[{}], 'unknown':1}):
            self.assertFalse(valid_spec_shape(spec))
            self.assertIsNone(answer_with_spec(spec, {'a':frame()})['answer'])

    def test_relative_anchor_explicit_fallback(self):
        typed={'a':frame(when_abs='last week', granularity='week')}
        for mode, expected in [('strict',0),('mention_day',1),('tolerant',1)]:
            spec=dict(op='count_events', _qdate='2026-01-12',
                      window={'kind':'loose_last_week','null_mode':mode})
            self.assertEqual(answer_with_spec(spec, typed,
                             [{'rid':'a','day':date(2026,1,10).toordinal()}])['answer'], expected)


class StoreTests(unittest.TestCase):
    def test_forget_person_removes_registry(self):
        m=LifeModel(); ingest(m,'a', about='Alice'); ingest(m,'b')
        m.store.forget_about('Alice')
        self.assertNotIn('a',m.store.typed)
        self.assertNotIn('a',m.store.rsv)
        self.assertIn('b',m.store.typed)

    def test_snapshot_restore_and_selective_export(self):
        m=LifeModel(); ingest(m,'a'); ingest(m,'b')
        self.assertEqual(set(m.state({'slots':['a']})['typed']), {'a'})
        state=m.state(); n=LifeModel(); n.import_state(state)
        self.assertEqual(m.store.typed,n.store.typed)
        m.store.forget_slot('a')
        self.assertNotIn('a',m.store.typed)
        n.store.forget_range(date(2026,1,10).toordinal(), date(2026,1,10).toordinal())
        self.assertEqual(n.store.typed,{})


class IngestTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_unique_ids(self):
        ids=[]
        for _ in range(2):
            llm=Stub([{'slot':'visit','value':'doctor'}])
            ing=LLMIngestor(llm, verify=False, yield_guard=False)
            records=await ing.aextract(10,[{'role':'user','content':'I visited a doctor'}])
            ids.append(records[0]['id'])
        self.assertNotEqual(*ids)

    async def test_incomplete_frames_retry(self):
        for malformed in ({'rid':'a'}, {'rid':'a','kind':'asserted'},
                          {'rid':'a',**frame(quantity='three')}):
            llm=Stub([malformed],[{'rid':'a',**frame()}])
            ing=LLMIngestor(llm)
            rec=[dict(id='a',slot='visit',kind='statement',day=1,value='doctor')]
            await ing._atype_fields(rec)
            self.assertEqual(len(llm.prompts),2)
            self.assertEqual(rec[0]['typed']['verb'],'visit')

    async def test_unknown_rids_ignored_and_missing_not_persisted(self):
        llm=Stub([{'rid':'wrong',**frame()}],[{'rid':'a'}])
        rec=[dict(id='a',slot='visit',kind='statement',day=1,value='doctor')]
        await LLMIngestor(llm)._atype_fields(rec)
        self.assertNotIn('typed',rec[0])


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_attribution_and_verify_rejected_context(self):
        m=LifeModel(); ingest(m,'a'); ingest(m,'b',typed=frame(verb='see'))
        ingest(m,'alice',about='Alice'); ingest(m,'assistant',source='assistant')
        spec={'op':'count_events','verbs':['visit']}
        llm=Stub(spec,spec)
        out=await _spec_aggregate(m,llm,'How many doctors did I visit?','2026-01-12')
        self.assertEqual(out['response'],'1')
        self.assertIn('REJECTED VALUES: {"b": "b"}',llm.prompts[1])
        self.assertIn('VOCABULARY:',llm.prompts[1])
        self.assertNotIn('alice',llm.prompts[1])

    async def test_metadata_only_kinds_never_enter_aggregation(self):
        for kind in ('hearsay', 'suggestion', 'derived', 'unknown'):
            with self.subTest(kind=kind):
                m=LifeModel(); ingest(m,'rumor',kind=kind)
                llm=Stub()
                self.assertIsNone(await _spec_aggregate(
                    m,llm,'How many doctors did I visit?','2026-01-12'))
                self.assertEqual(llm.prompts,[])
                ingest(m,'actual')
                spec={'op':'count_events','verbs':['visit']}
                llm=Stub(spec,spec)
                out=await _spec_aggregate(
                    m,llm,'How many doctors did I visit?','2026-01-12')
                self.assertEqual(out['response'],'1')
                self.assertEqual(out['agg_evidence'],['actual'])
                self.assertTrue(all('rumor' not in p for p in llm.prompts))

    async def test_untyped_metadata_does_not_block_authoritative_records(self):
        m=LifeModel(); ingest(m,'actual'); ingest(m,'rumor',kind='hearsay',typed=None)
        spec={'op':'count_events','verbs':['visit']}
        out=await _spec_aggregate(m,Stub(spec,spec),
                                 'How many doctors did I visit?','2026-01-12')
        self.assertEqual(out['agg_evidence'],['actual'])

    async def test_correction_and_partial_typing_fall_back(self):
        for kwargs in ({'kind':'retraction'},{'kind':'correction'},{'typed':None}):
            m=LifeModel(); ingest(m,'a'); ingest(m,'b',**kwargs)
            llm=Stub()
            self.assertIsNone(await _spec_aggregate(m,llm,'How many visits did I make?','2026-01-12'))
            self.assertEqual(llm.prompts,[])

    async def test_bad_specs_fall_back(self):
        m=LifeModel(); ingest(m,'a')
        llm=Stub([],{'op':'sum','field':'object'}, {'op':'count_events','window':{'kind':'past_days'}})
        self.assertIsNone(await _spec_aggregate(m,llm,'How many visits did I make?','2026-01-12'))

    async def test_spec_runs_before_ruleb_profile(self):
        with patch('lifemodel.reader._spec_aggregate',new=AsyncMock(return_value={'response':'2'})) as agg:
            out=await aanswer(LifeModel(),Stub(),'How many doctors did I visit?','2026-01-12',route='ruleB',agg='spec')
            self.assertEqual(out['response'],'2'); agg.assert_awaited_once()

    async def test_current_state_does_not_aggregate(self):
        with patch('lifemodel.reader._spec_aggregate',new=AsyncMock()) as agg, \
             patch('lifemodel.reader.aretrieve',new=AsyncMock(side_effect=RuntimeError('fallback'))):
            with self.assertRaisesRegex(RuntimeError,'fallback'):
                await aanswer(LifeModel(),Stub(),'How many bikes do I currently own?','2026-01-12',agg='spec')
            agg.assert_not_awaited()

    async def test_total_duration_routes(self):
        with patch('lifemodel.reader._spec_aggregate',new=AsyncMock(return_value={'response':'2'})) as agg:
            await aanswer(LifeModel(),Stub(),'How long did I spend driving altogether?','2026-01-12',agg='spec')
            agg.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
