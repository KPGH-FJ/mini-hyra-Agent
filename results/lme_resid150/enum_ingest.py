"""Ingest-side enumerable extraction: per-session structured copy of countable facts.
Usage: python3 enum_ingest.py <questions.json> <qid_file> <out_dir>
Each session -> ENUM_SYS -> rows appended to out_dir/<qid>.enum.jsonl
"""
import asyncio, json, os, sys

sys.path.insert(0, '/home/ubuntu/serve-v4')
from hyra.llm import OpenAICompatLLM

ENUM_SYS = """You extract COUNTABLE facts from a single chat session for a personal-memory index.

List every concrete item/event/transaction the user did, owns, bought, made, viewed, attended, returned, lent, borrowed, used, spent, or plans to do — one row per distinct countable thing.

Return ONLY a JSON array:
{"item": "short canonical name", "category": "object|food|event|service|purchase|workout|trip|other", "verb": "did|owns|bought|made|viewed|attended|returned|lent|used|spent|plans", "date": "absolute YYYY-MM-DD resolved from the session date, or null", "detail": "qualifiers <=10 words"}

Rules:
- Resolve every relative date to absolute using the session date.
- One row per distinct item — same item mentioned twice = one row.
- Facts only, no inference, no advice content, no assistant suggestions.
- Empty array if the session has no countable facts."""


async def proc_session(llm, qid, sdate, turns, out_f, sem):
    async with sem:
        text = "\n".join(f"{t['role']}: {t['content'][:600]}" for t in turns)
        prompt = f"SESSION DATE: {sdate}\n\n{text}"
        for attempt in range(6):
            try:
                raw = await llm.complete(ENUM_SYS, prompt)
                import re
                m = re.search(r'\[.*\]', raw, re.S)
                rows = json.loads(m.group(0)) if m else []
                for r in rows:
                    r['session_date'] = sdate
                with open(out_f, 'a') as f:
                    for r in rows:
                        f.write(json.dumps(r) + '\n')
                return len(rows)
            except Exception as e:
                if attempt == 5:
                    print('FAIL', qid, sdate, repr(e)[:100], flush=True)
                    return 0
                await asyncio.sleep(15 * (attempt + 1))


async def main():
    qfile, qids_file, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    qs = {x['question_id']: x for x in json.load(open(qfile))}
    qids = [l.strip() for l in open(qids_file) if l.strip()]
    llm = OpenAICompatLLM(model='Atria-Dawn-Preview', base_url='https://api.atria-asi.ai/v1',
                          api_key=os.environ['ATRIA_API_KEY'], max_tokens=8192, retries=8)
    sem = asyncio.Semaphore(5)
    tasks = []
    for qid in qids:
        q = qs.get(qid)
        if not q:
            continue
        out_f = os.path.join(out_dir, qid + '.enum.jsonl')
        done_sessions = set()
        if os.path.exists(out_f):
            done_sessions = {json.loads(l)['session_date'] for l in open(out_f)}
        for sdate, sess in zip(q['haystack_dates'], q['haystack_sessions']):
            if sdate not in done_sessions:
                tasks.append(proc_session(llm, qid, sdate, sess, out_f, sem))
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
