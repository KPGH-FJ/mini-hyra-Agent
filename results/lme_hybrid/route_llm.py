"""route_llm: per-question LLM channel classifier for the 150q slice.

Given question text + question_type + model vertex count, choose
PROFILE (whole-profile answering) or RETRIEVAL (nogate+assist stack).
Writes {qid, choice} rows; then a join computes the routed score.
"""
import asyncio, json, os, sys
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
sys.path.insert(0, "/home/ubuntu/serve-v4")
from hyra.llm import OpenAICompatLLM

ROUTE_SYS = """You are a routing classifier for a memory-QA system with two answer channels:
- PROFILE: the model answers from a single rendered persona-profile document
  (compressed, domain-grouped). Best for: temporal reasoning, aggregation,
  advice/recommendation grounded in user taste, questions where the needed
  fact is a single salient item. Weakness: multi-item enumeration / "list
  all / how many different" questions on large memories (the profile
  summarizes lists and loses counts), and fine-grained update-recall on
  big memories.
- RETRIEVAL: the model retrieves verbatim memory records then answers with
  an assist pass. Best for: enumeration & counting, knowledge-update recall,
  assistant-recommendation recall, very large memories (100+ records).

Pick the channel most likely to answer correctly. Reply with exactly one
word: PROFILE or RETRIEVAL."""


async def main():
    out_path = sys.argv[1]
    join = json.load(open("results/lme_hybrid/route_join.json"))
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["qid"] for l in open(out_path)}
    llm = OpenAICompatLLM()
    fh = open(out_path, "a")

    async def one(o):
        if o["qid"] in done:
            return
        user = (f"QUESTION_TYPE: {o['qtype']}\nMEMORY_SIZE: "
                f"{o['v']} records\nQUESTION: {o['question']}")
        r = (await llm.complete(ROUTE_SYS, user)).strip().upper()
        choice = "profile" if "PROFILE" in r else "assist"
        fh.write(json.dumps({"qid": o["qid"], "choice": choice,
                             "raw": r[:40]}) + "\n")
        fh.flush()
        print(o["qid"], choice, flush=True)

    sem = asyncio.Semaphore(4)

    async def guarded(o):
        async with sem:
            await one(o)

    await asyncio.gather(*(guarded(o) for o in join))


asyncio.run(main())
