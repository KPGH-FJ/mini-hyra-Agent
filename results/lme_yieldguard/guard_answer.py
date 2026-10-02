"""Answer the 5 re-ingested ss-assist questions on both guard arms'
models, through both channels (assist stack + profile), and judge.
Writes results/lme_yieldguard/answers.jsonl with every response.
"""
import asyncio, glob, json, os, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
from lifemodel import reader
from lifemodel.profile import render_profile
from hyra.llm import OpenAICompatLLM


class _M:
    def __init__(self, asset): self._a = asset
    def export(self): return {"asset": self._a}


def load_model(path):
    return _M(json.load(open(path))["export"]["asset"])


async def main():
    qs = {q["question_id"]: q
          for q in json.load(open("results/lme_yieldguard/questions.json"))}
    out = open("results/lme_yieldguard/answers.jsonl", "a")
    done = {json.loads(l)["key"] for l in
            open("results/lme_yieldguard/answers.jsonl")} \
        if os.path.exists("results/lme_yieldguard/answers.jsonl") else set()
    llm = OpenAICompatLLM()
    for arm in ["arm_zero", "arm_parity"]:
        for mp in sorted(glob.glob(
                f"results/lme_yieldguard/{arm}/models/*.json")):
            qid = os.path.basename(mp)[:-5]
            q = qs[qid]
            model = load_model(mp)
            for ch in ["assist", "profile"]:
                key = f"{arm}/{ch}/{qid}"
                if key in done:
                    continue
                if ch == "assist":
                    r = await reader.aanswer(
                        model, llm, q["question"], q["question_date"],
                        assist=True)
                else:
                    prof = await render_profile(model, llm)
                    open(f"results/lme_yieldguard/{arm}/"
                         f"{qid}.profile.md", "w").write(prof)
                    r = await reader.aanswer(
                        model, llm, q["question"], q["question_date"],
                        profile=prof)
                out.write(json.dumps({
                    "key": key, "arm": arm, "channel": ch, "qid": qid,
                    "response": r["response"]}) + "\n")
                out.flush()
                print(key, "->", r["response"][:70], flush=True)


asyncio.run(main())
