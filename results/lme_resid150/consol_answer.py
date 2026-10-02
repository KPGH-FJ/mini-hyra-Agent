"""Consolidation arm: meta-judgment clause + temporal-composition guidance, prompt layer only.
Usage: python3 consol_answer.py <ev_dir> <out_jsonl>
"""
import asyncio, json, os, sys

sys.path.insert(0, '/home/ubuntu/serve-v4')
from hyra.llm import OpenAICompatLLM

META_SYS = """You answer questions about a user from their records/profile below.

META-JUDGMENT — weigh evidence before refusing: if the materials clearly imply a direction (stated preferences, context, repeated patterns, an inferable chain), give the best-grounded answer and briefly state what you inferred. A grounded extrapolation beats an abstention; refuse only when there is genuinely no signal.

TEMPORAL COMPOSITION — for "how long ago / how much time" questions, compose arithmetically: e.g. an event M months ago that was booked N months in advance means booked N+M months ago. Resolve relative dates to absolute first, then compute the interval to the question's date.

Answer directly with the itemized evidence. Never invent facts not in the materials."""


async def run_one(llm, ev, sem):
    async with sem:
        qid = ev['qid']
        if ev.get('profile'):
            mat = "PROFILE:\n" + ev['profile']
        else:
            mat = "RECORDS:\n" + "\n".join(f"- {v}" for k, v in ev['records'])
        prompt = f"QUESTION: {ev['question']}\nDATE ASKED: {ev['qdate']}\n\n{mat}"
        try:
            resp = await llm.complete(META_SYS, prompt)
        except Exception as e:
            print('ERR', qid, repr(e)[:100], flush=True)
            resp = 'ERROR'
        row = {'question_id': qid, 'response': resp}
        with open(sys.argv[2], 'a') as f:
            f.write(json.dumps(row) + '\n')


async def main():
    ev_dir = sys.argv[1]
    llm = OpenAICompatLLM(model='Atria-Dawn-Preview', base_url='https://api.atria-asi.ai/v1',
                          api_key=os.environ['ATRIA_API_KEY'], max_tokens=4096, retries=8)
    evs = [json.load(open(os.path.join(ev_dir, f))) for f in sorted(os.listdir(ev_dir)) if f.endswith('.json')]
    done = set()
    if os.path.exists(sys.argv[2]):
        done = {json.loads(l)['question_id'] for l in open(sys.argv[2])}
    sem = asyncio.Semaphore(5)
    await asyncio.gather(*[run_one(llm, ev, sem) for ev in evs if ev['qid'] not in done])

if __name__ == '__main__':
    asyncio.run(main())
