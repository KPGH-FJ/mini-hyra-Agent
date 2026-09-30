#!/usr/bin/env python3
"""premise_on full adversarial coverage — 112 cat5 questions, conv-0..2.

Answers every cat5 question on the saved stock-ingest snapshots with
aanswer(premise_check=True) — the same snapshots the merged arm used,
so the comparison isolates the reader-side verify stage. Answer model
= Atria (cheap, no OR burn); judge = OR stealth (the judge-of-record
for this comparison) over BOTH this file and the merged-arm hyps, so
both numbers sit under the same judge.

  python pv112.py --data locomo10.json           # answer pass (Atria)
  python pv112.py --data locomo10.json --judge   # OR judge both arms
"""
import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A  # noqa: E402

from lme import _make_llm                       # noqa: E402
from lifemodel.model import LifeModel            # noqa: E402
import lifemodel.reader as R                    # noqa: E402

SNAPS = {0: "ingest_c0_atria.json", 1: "ingest_c1_atria.json",
         2: "ingest_c2_atria.json"}
HYPS = {0: "adv_merged_c0.jsonl", 1: "adv_merged_c1.jsonl",
        2: "adv_merged_c2.jsonl"}
OUT = "pv112.jsonl"
ATRIA = ("https://api.atria-asi.ai/v1", "Atria-Dawn-Preview")
OR = ("https://openrouter.ai/api/v1", "stealth/space-bunny-alpha")


async def judge(llm, path):
    rows, n_ok = [], 0
    for line in open(path):
        h = json.loads(line)
        note = "" if h.get("gold") else A.ABS_NOTE
        p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                           r=h["response"], abs_note=note)
        ok = None
        for attempt in range(4):
            try:
                v = (await llm.complete(
                    "You are a strict grader.", p)).strip().lower()
                ok = v.startswith("yes")
                break
            except Exception as e:
                print("judge fail", h["qid"], attempt, e,
                      file=sys.stderr)
                await asyncio.sleep(8 * (attempt + 1))
        n_ok += bool(ok)
        rows.append({"qid": h["qid"], "correct": ok})
        print(f"  {h['qid']} {ok}", flush=True)
    return {"n": len(rows), "acc": n_ok / max(len(rows), 1),
            "rows": rows}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--out-dir",
                    default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    convs = json.load(open(args.data))
    od = args.out_dir

    if args.judge:
        import argparse as _ap
        jargs = _ap.Namespace(api_key=os.environ.get("OR_API_KEY"),
                              base_url=OR[0], model=OR[1])
        jllm = _make_llm(jargs)
        m = await judge(jllm, os.path.join(od, OUT))
        json.dump(m, open(os.path.join(
            od, "pv112_metrics_or.json"), "w"), indent=2)
        print("pv112 OR-judged:", m["acc"], f"({m['n']})", flush=True)
        merged_rows, tot, ok = [], 0, 0
        for ci in range(3):
            mm = await judge(jllm, os.path.join(od, HYPS[ci]))
            tot += mm["n"]
            ok += sum(r["correct"] for r in mm["rows"])
            merged_rows += mm["rows"]
        out = {"n": tot, "acc": ok / max(tot, 1), "rows": merged_rows}
        json.dump(out, open(os.path.join(
            od, "adv_merged_metrics_or.json"), "w"), indent=2)
        print("merged OR-judged:", out["acc"], f"({tot})", flush=True)
        return

    base, model = ATRIA
    aargs = argparse.Namespace(api_key=os.environ.get("ATRIA_API_KEY"),
                               base_url=base, model=model)
    llm_a = _make_llm(aargs, thinking=True)
    out = open(os.path.join(od, OUT), "w")
    for ci in range(3):
        m = LifeModel()
        m.import_state(json.load(open(os.path.join(od, SNAPS[ci]))))
        for row in A.cat5_qs(convs[ci], ci):
            try:
                r = await R.aanswer(m, llm_a, row["question"],
                                    "2023 (post-conversation)",
                                    premise_check=True)
                resp, verify = r["response"], r.get("verify") or {}
            except Exception as e:
                resp, verify = f"(error: {e})", {}
            rec = {**row, "response": resp,
                   "verdict": verify.get("verdict"),
                   "atoms": verify.get("atoms")}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            print(f"c{ci} {row['qid']} [{verify.get('verdict')}] "
                  f"{resp[:70]!r}", flush=True)
    out.close()


if __name__ == "__main__":
    asyncio.run(main())
