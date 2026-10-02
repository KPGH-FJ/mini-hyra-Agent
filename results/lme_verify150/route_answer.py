"""ruleB routing over verify150 models: per question pick channel by
question_type — temporal-reasoning / multi-session /
single-session-preference -> profile; else assist; enum-size>=90 ->
assist (vertex count from model hist). One answer call per question +
one profile render per profile-routed question.
"""
import asyncio, json, os, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
from lifemodel import reader
from lifemodel.profile import render_profile
from hyra.llm import OpenAICompatLLM

base = "/home/ubuntu/m4-complete/results/lme_verify150"
mdir = f"{base}/models"
QS = json.load(open(f"{base}/questions.json"))
OUT = f"{base}/answers_routeB.jsonl"
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        done.add(json.loads(l)["qid"])
out = open(OUT, "a")
llm = OpenAICompatLLM()
sem = asyncio.Semaphore(6)

class _M:
    def __init__(s, a): s._a = a
    def export(s): return {"asset": s._a}

def load_model(p):
    return _M(json.load(open(p))["export"]["asset"])

pdir = f"{base}/profiles"
os.makedirs(pdir, exist_ok=True)

PROF_TYPES = {"temporal-reasoning", "multi-session",
              "single-session-preference"}
ENUM_PAT = None  # handled by v>=90 vertex rule only

async def run_one(q):
    qid = q["question_id"]
    if qid in done:
        return
    mp = os.path.join(mdir, qid + ".json")
    if not os.path.exists(mp):
        return
    async with sem:
        model = load_model(mp)
        nv = sum(len(v) for v in
                 model.export()["asset"]["hist"].values())
        chan = ("profile" if q["question_type"] in PROF_TYPES
                else "assist")
        if nv >= 90:
            chan = "assist"
        qd = q["question_date"]
        for _try in range(5):
            try:
                if chan == "profile":
                    pp = os.path.join(pdir, qid + ".profile.md")
                    if os.path.exists(pp):
                        prof = open(pp).read()
                    else:
                        prof = await render_profile(model, llm)
                        open(pp, "w").write(prof)
                    r = await reader.aanswer(model, llm,
                                             q["question"], qd,
                                             profile=prof)
                else:
                    r = await reader.aanswer(model, llm,
                                             q["question"], qd,
                                             assist=True)
                break
            except Exception as e:
                if "429" in str(e) and _try < 4:
                    await asyncio.sleep(30 * (_try + 1))
                    continue
                r = {"response": f"ERR:{e}", "selected": [],
                     "digest": ""}
                break
        out.write(json.dumps({"qid": qid, "channel": chan, "nv": nv,
                              "response": r["response"],
                              "n_selected": len(r.get("selected", [])),
                              "digest_chars": len(r.get("digest", ""))},
                             ensure_ascii=False) + "\n")
        out.flush()
        print(qid, chan, nv, "ok", flush=True)

async def main():
    await asyncio.gather(*(run_one(q) for q in QS))

asyncio.run(main())
