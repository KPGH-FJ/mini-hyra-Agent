"""Enum-table answering: grep marked rows -> deterministic dedup/count -> LLM itemized answer.
Usage: python3 enum_answer.py <ev_dir> <enum_dir> <out_jsonl>
"""
import asyncio, json, os, re, sys

sys.path.insert(0, '/home/ubuntu/serve-v4')
from hyra.llm import OpenAICompatLLM
from agg_answer import dedup_count, ANSWER_SYS


async def run_one(llm, ev, enum_dir, sem):
    async with sem:
        qid = ev['qid']
        ef = os.path.join(enum_dir, qid + '.enum.jsonl')
        rows = [json.loads(l) for l in open(ef)] if os.path.exists(ef) else []
        kept = dedup_count(rows)
        table_text = "\n".join(
            f"{i+1}. {r.get('item')} | {r.get('verb','')} | {r.get('date')} | {r.get('detail','')}"
            for i, r in enumerate(kept))
        prompt = (f"QUESTION: {ev['question']}\nDATE ASKED: {ev['qdate']}\n\n"
                  f"COUNTABLE-FACT TABLE ({len(kept)} rows, extracted at ingest time, program-deduplicated):\n"
                  f"{table_text or '(empty)'}")
        try:
            resp = await llm.complete(ANSWER_SYS, prompt)
        except Exception as e:
            print('ANS_ERR', qid, repr(e)[:120], flush=True)
            resp = 'ERROR'
        row = {'question_id': qid, 'response': resp, 'n_enum_rows': len(rows), 'n_deduped': len(kept)}
        with open(sys.argv[3], 'a') as f:
            f.write(json.dumps(row) + '\n')
        return row


async def main():
    ev_dir, enum_dir, _ = sys.argv[1], sys.argv[2], sys.argv[3]
    llm = OpenAICompatLLM(model='Atria-Dawn-Preview', base_url='https://api.atria-asi.ai/v1',
                          api_key=os.environ['ATRIA_API_KEY'], max_tokens=4096, retries=8)
    evs = [json.load(open(os.path.join(ev_dir, f))) for f in sorted(os.listdir(ev_dir)) if f.endswith('.json')]
    done = set()
    if os.path.exists(sys.argv[3]):
        done = {json.loads(l)['question_id'] for l in open(sys.argv[3])}
    sem = asyncio.Semaphore(5)
    await asyncio.gather(*[run_one(llm, ev, enum_dir, sem) for ev in evs if ev['qid'] not in done])

if __name__ == '__main__':
    asyncio.run(main())
