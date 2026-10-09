"""Naive-RAG baseline on the same LME-150 stratified set — the head-to-head.
BM25 over the question's own haystack utterances -> top-k -> generic answer
prompt -> same Atria judge (adv_cov.JUDGE). No lifemodel machinery: this is
what "just retrieve + answer" scores on identical questions/judge.
Usage: python3 naive_rag150.py <data_strat150.json> <out_jsonl>
"""
import asyncio, json, math, os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from hyra.llm import OpenAICompatLLM

JUDGE = """You are grading a memory system answer.
QUESTION: {q}
GOLD ANSWER: {a}
SYSTEM RESPONSE: {r}
Answer yes if the response conveys the gold answer (paraphrase OK).
Reply with only yes or no."""

ANS_SYS = ("You answer questions about the user's past conversations using "
           "the retrieved utterances below. Use ONLY the retrieved "
           "utterances; if the answer is not there, say you don't know. "
           "Be concise and give concrete values when present.")

K = int(os.environ.get("TOPK", "20"))
TOK = re.compile(r"[a-z0-9']+")


def bm25(docs, query, k):
    """Standard BM25 (k1=1.5, b=0.75). docs = list of token lists."""
    N = len(docs)
    df = Counter()
    tf = []
    for d in docs:
        c = Counter(d)
        tf.append(c)
        df.update(set(d))
    avg = sum(len(d) for d in docs) / max(N, 1)
    idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
    qt = TOK.findall(query.lower())
    scored = []
    for i, d in enumerate(docs):
        s = 0.0
        dl = len(d) or 1
        for t in qt:
            f = tf[i].get(t, 0)
            if f:
                s += idf.get(t, 0) * f * 2.5 / (f + 1.5 * (1 - 0.75 + 0.75 * dl / avg))
        scored.append((s, i))
    scored.sort(reverse=True)
    return [i for _, i in scored[:k]]


def docs_of(q):
    """One doc per utterance, prefixed with role + session date."""
    out = []
    for si, sess in enumerate(q["haystack_sessions"]):
        date = q["haystack_dates"][si] if si < len(q["haystack_dates"]) else ""
        date = date.split(" (")[0] if date else ""
        for u in sess:
            out.append(f"[{date}] {u['role']}: {u['content']}")
    return out


async def run_one(llm, q, sem):
    async with sem:
        docs = docs_of(q)
        toks = [TOK.findall(d.lower()) for d in docs]
        top = bm25(toks, q["question"], K)
        ctx = "\n".join(docs[i] for i in top)
        prompt = (f"RETRIEVED UTTERANCES:\n{ctx}\n\n"
                  f"QUESTION (asked on {q['question_date']}): {q['question']}\n\nANSWER:")
        for attempt in range(6):
            try:
                resp = await llm.complete(ANS_SYS, prompt)
                return {"question_id": q["question_id"],
                        "question_type": q["question_type"],
                        "response": resp.strip(), "n_ctx": len(top)}
            except Exception:
                await asyncio.sleep(15 * (attempt + 1))
        return {"question_id": q["question_id"],
                "question_type": q["question_type"],
                "response": "(error)", "n_ctx": len(top)}


async def judge(llm, row, q, sem):
    async with sem:
        p = JUDGE.format(q=q["question"], a=q["answer"], r=row["response"])
        for attempt in range(4):
            try:
                v = (await llm.complete("You are a strict grader.", p)).strip().lower()
                row["correct"] = v.startswith("yes")
                return
            except Exception:
                await asyncio.sleep(10 * (attempt + 1))
        row["correct"] = None


async def main():
    data_f, out_f = sys.argv[1], sys.argv[2]
    llm = OpenAICompatLLM(model='Atria-Dawn-Preview',
                          base_url='https://api.atria-asi.ai/v1',
                          api_key=os.environ['ATRIA_API_KEY'],
                          max_tokens=8192, retries=8)
    qs = json.load(open(data_f))
    done, rows = set(), []
    if os.path.exists(out_f):
        rows = [json.loads(l) for l in open(out_f)]
        done = {r["question_id"] for r in rows}
    sem = asyncio.Semaphore(8)
    todo = [q for q in qs if q["question_id"] not in done]
    print(f"{len(todo)} to answer (topk={K})", flush=True)
    new = await asyncio.gather(*[run_one(llm, q, sem) for q in todo])
    with open(out_f, "a") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"ans {r['question_id']}: {r['response'][:80]!r}", flush=True)
    rows += new
    byid = {q["question_id"]: q for q in qs}
    await asyncio.gather(*[judge(llm, r, byid[r["question_id"]], sem)
                           for r in rows if "correct" not in r])
    with open(out_f, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(rows)
    ok = sum(1 for r in rows if r.get("correct"))
    by = {}
    for r in rows:
        t = r["question_type"]
        by.setdefault(t, [0, 0])
        by[t][1] += 1
        by[t][0] += bool(r.get("correct"))
    print(f"\nTOTAL {ok}/{n} = {ok / n * 100:.1f}%")
    for t, (a, b) in sorted(by.items()):
        print(f"  {t}: {a}/{b} = {a / b * 100:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
