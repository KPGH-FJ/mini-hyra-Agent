"""ruleB-150 actual: aanswer(route='ruleB', qtype=mapped) on verify150 snapshots, latest main code.
Usage: python3 ruleB150.py <questions.json> <models_dir> <profiles_dir> <out_jsonl>
"""
import asyncio, json, os, sys

sys.path.insert(0, '/home/ubuntu/serve-v4')
sys.path.insert(0, '/home/ubuntu/m4-complete/results/main_latest')
from hyra.llm import OpenAICompatLLM
from lifemodel.reader import aanswer

_QT = {"temporal-reasoning": "temporal", "multi-session": "ms",
       "single-session-preference": "pref"}


def load_model(path):
    class _M:
        def __init__(s, a): s._a = a
        def export(s): return {"asset": s._a}
    return _M(json.load(open(path))["export"]["asset"])


async def run_one(llm, q, models_dir, profiles_dir, sem):
    async with sem:
        qid = q['question_id']
        mp = os.path.join(models_dir, qid + '.json')
        if not os.path.exists(mp):
            return
        model = load_model(mp)
        qt = _QT.get(q['question_type'], 'other')
        pf = os.path.join(profiles_dir, qid + '.profile.md')
        prof = open(pf).read() if os.path.exists(pf) else None
        for attempt in range(6):
            try:
                r = await aanswer(model, llm, q['question'], q['question_date'],
                                  route='ruleB', qtype=qt, profile=prof)
                row = {'question_id': qid, 'question_type': q['question_type'],
                       'route_qtype': qt, 'channel': 'profile' if qt in _QT.values() else 'assist',
                       'response': r['response'], 'n_selected': len(r.get('selected', [])),
                       'digest_chars': len(r.get('digest', ''))}
                with open(sys.argv[4], 'a') as f:
                    f.write(json.dumps(row) + '\n')
                return
            except Exception as e:
                if attempt == 5:
                    print('FAIL', qid, repr(e)[:100], flush=True)
                await asyncio.sleep(20 * (attempt + 1))


async def main():
    qfile, models_dir, profiles_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    llm = OpenAICompatLLM(model='Atria-Dawn-Preview', base_url='https://api.atria-asi.ai/v1',
                          api_key=os.environ['ATRIA_API_KEY'], max_tokens=8192, retries=8)
    qs = json.load(open(qfile))
    done = set()
    if os.path.exists(sys.argv[4]):
        done = {json.loads(l)['question_id'] for l in open(sys.argv[4])}
    sem = asyncio.Semaphore(6)
    await asyncio.gather(*[run_one(llm, q, models_dir, profiles_dir, sem)
                           for q in qs if q['question_id'] not in done])

if __name__ == '__main__':
    asyncio.run(main())
