"""Deterministic aggregation arm: LLM extracts candidate item table -> code dedups/sorts/counts -> LLM answers with items+total.
Usage: python3 agg_answer.py <resid_dir> <models_dir> <out_jsonl>
"""
import asyncio, json, os, re, sys

sys.path.insert(0, '/home/ubuntu/serve-v4')
sys.path.append('/home/ubuntu/mainstack')
from hyra.llm import OpenAICompatLLM


def load_model(path):
    class _M:
        def __init__(s, a): s._a = a
        def export(s): return {"asset": s._a}
    return _M(json.load(open(path))["export"]["asset"])


TABLE_SYS = """You extract a candidate-item table from personal records to answer a counting/enumeration question.

Given the records and the question, list EVERY candidate item that could count toward the answer — err on the side of inclusion; a downstream program will deduplicate and a judge will verify.

Return ONLY a JSON array of objects:
{"item": "short canonical name of the item/event/entity", "date": "YYYY-MM-DD or relative date as stated, or null", "evidence": "the record text <=15 words that supports it"}

Rules:
- One row per DISTINCT item. If two records describe the same item, emit one row (keep the clearest date).
- Include items the question might count even if borderline (mark item name exactly).
- Do NOT answer the question — only list candidates."""


def _norm(s):
    return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()


def dedup_count(rows):
    seen, kept = {}, []
    for r in rows:
        item = _norm(str(r.get('item', '')))
        if not item:
            continue
        if item in seen:
            if r.get('date') and not kept[seen[item]].get('date'):
                kept[seen[item]] = r
            continue
        seen[item] = len(kept)
        kept.append(r)
    kept.sort(key=lambda r: (str(r.get('date') or '9999'), _norm(str(r.get('item', '')))))
    return kept


ANSWER_SYS = """You answer a counting/enumeration question about the user.

You are given a PRE-DIGESTED candidate table: each row is one distinct item extracted from the user's records, with its date and evidence. The table has already been deduplicated and counted by a program — TRUST the row count.

Instructions:
- Answer with the itemized list (numbered) AND the total count.
- If the question asks for a date/window filter, apply it using the date column — drop rows outside the window and recount from the remaining rows.
- If the table has obvious non-matching rows, drop them and recount.
- State the total as a number. If zero rows match, say so.
- Never invent items not in the table."""


async def run_one(llm, ev, models_dir, out, sem):
    async with sem:
        qid = ev['qid']
        rec_lines = [f"- {v}" for k, v in ev['records']]
        table_prompt = f"QUESTION: {ev['question']}\n\nRECORDS:\n" + "\n".join(rec_lines)
        try:
            raw = await llm.complete(TABLE_SYS, table_prompt)
            m = re.search(r'\[.*\]', raw, re.S)
            rows = json.loads(m.group(0)) if m else []
        except Exception as e:
            print('TABLE_ERR', qid, repr(e)[:120], flush=True)
            rows = []
        kept = dedup_count(rows)
        table_text = "\n".join(f"{i+1}. {r.get('item')} | {r.get('date')} | {r.get('evidence')}" for i, r in enumerate(kept))
        ans_prompt = f"QUESTION: {ev['question']}\nDATE ASKED: {ev['qdate']}\n\nCANDIDATE TABLE ({len(kept)} rows, program-deduplicated):\n{table_text or '(empty)'}"
        try:
            resp = await llm.complete(ANSWER_SYS, ans_prompt)
        except Exception as e:
            print('ANS_ERR', qid, repr(e)[:120], flush=True)
            resp = 'ERROR'
        row = {'question_id': qid, 'response': resp, 'n_candidates': len(rows), 'n_deduped': len(kept),
               'channel': ev.get('channel'), 'qtype': ev.get('qtype')}
        out.append(row)
        with open(sys.argv[3], 'a') as f:
            f.write(json.dumps(row) + '\n')


async def main():
    resid_dir, models_dir, _ = sys.argv[1], sys.argv[2], sys.argv[3]
    llm = OpenAICompatLLM(model='Atria-Dawn-Preview', base_url='https://api.atria-asi.ai/v1',
                          api_key=os.environ['ATRIA_API_KEY'], max_tokens=4096, retries=8)
    evs = [json.load(open(os.path.join(resid_dir, f))) for f in sorted(os.listdir(resid_dir)) if f.endswith('.json')]
    done = set()
    if os.path.exists(sys.argv[3]):
        done = {json.loads(l)['question_id'] for l in open(sys.argv[3])}
    sem = asyncio.Semaphore(5)
    out = []
    await asyncio.gather(*[run_one(llm, ev, models_dir, out, sem) for ev in evs if ev['qid'] not in done])

if __name__ == '__main__':
    asyncio.run(main())
