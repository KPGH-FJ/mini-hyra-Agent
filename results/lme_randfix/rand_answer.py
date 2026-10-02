import asyncio, json, os, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
from lifemodel import reader
from lifemodel.profile import render_profile
from hyra.llm import OpenAICompatLLM

ARM = sys.argv[1]          # union2 | verify
CHAN = sys.argv[2]         # assist | profile
base = "/home/ubuntu/m4-complete/results/lme_randfix"
mdir = f"{base}/{ARM}/models"
QS = json.load(open(f"{base}/questions.json"))
OUT = f"{base}/answers_{ARM}_{CHAN}.jsonl"
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        done.add(json.loads(l)["qid"])
out = open(OUT, "a")
llm = OpenAICompatLLM()
sem = asyncio.Semaphore(4)

class _M:
    def __init__(s, a): s._a = a
    def export(s): return {"asset": s._a}

def load_model(p):
    return _M(json.load(open(p))["export"]["asset"])

pdir = f"{base}/{ARM}/profiles"
os.makedirs(pdir, exist_ok=True)

async def run_one(q):
    qid = q["question_id"]
    if qid in done:
        return
    async with sem:
        model = load_model(os.path.join(mdir, qid + ".json"))
        qd = q["question_date"]
        for _try in range(5):
            try:
                if CHAN == "assist":
                    resp = await reader.aanswer(model, llm, q["question"],
                                                qd, assist=True)
                else:
                    pp = os.path.join(pdir, qid + ".profile.md")
                    if os.path.exists(pp):
                        prof = open(pp).read()
                    else:
                        prof = await render_profile(model, llm)
                        open(pp, "w").write(prof)
                    resp = await reader.aanswer(model, llm, q["question"],
                                                qd, profile=prof)
                break
            except Exception as e:
                if "429" in str(e) and _try < 4:
                    await asyncio.sleep(30 * (_try + 1))
                    continue
                resp = f"ERR:{e}"
                break
        out.write(json.dumps({"qid": qid, "arm": ARM, "channel": CHAN,
                              "response": resp}, ensure_ascii=False) + "\n")
        out.flush()
        print(ARM, CHAN, qid, "ok", flush=True)

async def main():
    await asyncio.gather(*(run_one(q) for q in QS))

asyncio.run(main())
