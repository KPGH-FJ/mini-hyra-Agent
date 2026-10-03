"""3x majority-vote re-judge of boundary cat5 rows (v3 losses + arm flips)."""
import asyncio, glob, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import adv_cov as A
from locomo_final import atria_llm

OUT = os.path.dirname(os.path.abspath(__file__))
DRAWS = 3
SEM = 8


def load(pat):
    d = {}
    for f in glob.glob(os.path.join(OUT, pat)):
        for l in open(f):
            r = json.loads(l)
            d[r["qid"]] = r
    return d


async def judge_once(jllm, h):
    note = "" if h.get("gold") else A.ABS_NOTE
    p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                       r=h["response"], abs_note=note)
    for _ in range(4):
        try:
            async with SEM_L:
                v = (await jllm.complete("You are a strict grader.",
                                         p)).strip().lower()
            return v.startswith("yes")
        except Exception:
            continue
    return None


SEM_L = asyncio.Semaphore(SEM)


async def main():
    boundary = json.load(open(os.path.join(OUT, "v3_boundary_qids.json")))
    v3 = load("grnd3_cat5_*.jsonl")
    v2 = load("grnd2_cat5_*.jsonl")
    jllm = atria_llm()
    results = {}
    for arm, rows in (("v3", v3), ("v2", v2)):
        for q in boundary:
            h = rows.get(q)
            if not h:
                continue
            draws = await asyncio.gather(
                *[judge_once(jllm, h) for _ in range(DRAWS)])
            maj = None
            ys = sum(1 for d in draws if d is True)
            if ys >= 2:
                maj = True
            elif ys <= len([d for d in draws if d is not None]) - 2 and \
                    len([d for d in draws if d is not None]) >= 2:
                maj = False
            if maj is None and ys + (len(draws) - ys) >= 0:
                maj = ys >= 2
            results[f"{arm}:{q}"] = {
                "draws": draws, "majority": maj,
                "orig": h.get("correct")}
            print(f"{arm} {q} draws={draws} maj={maj} orig={h.get('correct')}",
                  flush=True)
    with open(os.path.join(OUT, "v3_judge3x.json"), "w") as f:
        json.dump(results, f, indent=1)

    # majority-corrected totals
    for arm, pat in (("v3", "grnd3_cat5_*.jsonl"),
                     ("v2", "grnd2_cat5_*.jsonl")):
        rows = load(pat)
        s = 0
        for q, r in rows.items():
            c = r.get("correct")
            k = f"{arm}:{q}"
            if k in results and results[k]["majority"] is not None:
                c = results[k]["majority"]
            s += 1 if c else 0
        print(f"{arm} majority-corrected cat5: {s}/{len(rows)} "
              f"({s/len(rows)*100:.1f}%)", flush=True)


asyncio.run(main())
