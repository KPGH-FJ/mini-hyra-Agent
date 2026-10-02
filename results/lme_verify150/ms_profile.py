import asyncio, json, os, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
from lifemodel import reader
from lifemodel.profile import render_profile
from hyra.llm import OpenAICompatLLM

base = "/home/ubuntu/m4-complete/results/lme_verify150"
mdir = f"{base}/models"
pdir = f"{base}/profiles"
os.makedirs(pdir, exist_ok=True)
QS = [q for q in json.load(open(f"{base}/questions.json"))
      if q["question_type"] == "multi-session"]
OUT = f"{base}/answers_msprofile.jsonl"
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        done.add(json.loads(l)["qid"])
out = open(OUT, "a")
llm = OpenAICompatLLM()
sem = asyncio.Semaphore(5)

class _M:
    def __init__(s, a): s._a = a
    def export(s): return {"asset": s._a}

def load_model(p):
    return _M(json.load(open(p))["export"]["asset"])

async def run_one(q):
    qid = q["question_id"]
    if qid in done:
        return
    async with sem:
        model = load_model(os.path.join(mdir, qid + ".json"))
        nv = sum(len(v) for v in
                 model.export()["asset"]["hist"].values())
        for _try in range(5):
            try:
                pp = os.path.join(pdir, qid + ".profile.md")
                if os.path.exists(pp):
                    prof = open(pp).read()
                else:
                    prof = await render_profile(model, llm)
                    open(pp, "w").write(prof)
                r = await reader.aanswer(model, llm, q["question"],
                                       q["question_date"], profile=prof)
                break
            except Exception as e:
                if "429" in str(e) and _try < 4:
                    await asyncio.sleep(30 * (_try + 1))
                    continue
                r = {"response": f"ERR:{e}"}
                break
        out.write(json.dumps({"qid": qid, "nv": nv,
                              "response": r["response"]},
                             ensure_ascii=False) + "\n")
        out.flush()
        print(qid, nv, "ok", flush=True)

async def main():
    await asyncio.gather(*(run_one(q) for q in QS))

asyncio.run(main())
