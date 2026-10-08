#!/usr/bin/env python3
"""deterministic re-eval of the STORED v3 specs under the three harness
fixes — zero LLM calls:
  A) dup-merge now requires date compatibility (_date_compat)
  B) window null_mode: rerun each window-bearing spec under
     strict / mention_day / tolerant sensitivity
  C) `counterparties` clause selector now exists in the DSL

usage: python3 results/lme_resid150/stage2/reeval_fix.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fidelity_eval as F  # noqa: E402
from spec_gen import answer_with_spec  # noqa: E402

OUT = "results/lme_resid150/stage2"
D = json.load(open("results/lme_resid150/stage1/annotations.json"))
SPECS = json.load(open(f"{OUT}/spec_gen_results_v3.json"))
QIDS = ["0a995998", "88432d0a", "d682f1a2", "gpt4_7fce9456",
        "7024f17c", "b5ef892d", "gpt4_f2262a51"]


def gold_num(g):
    try:
        return float(str(g).split(" ")[0])
    except ValueError:
        return None


def verdict(ans, g):
    gn = gold_num(g)
    if gn is not None and isinstance(ans, (int, float)):
        return abs(float(ans) - gn) < 1e-6
    return str(ans) == str(g)


def run(qid, spec, null_mode=None):
    data = F.load_typed(qid)
    s = json.loads(json.dumps(spec))
    if null_mode:
        for c in (s.get("any_of") or [s]):
            if c.get("window"):
                c["window"]["null_mode"] = null_mode
    return answer_with_spec(None, s, data["typed"],
                            data.get("records"))


def main():
    qs = {q["qid"]: q for q in D["questions"]}
    print(f"{'qid':18} {'gold':>6} {'strict':>8} {'mday':>8} {'tol':>8}")
    tot = {"strict": 0, "mention_day": 0, "tolerant": 0}
    for qid in QIDS:
        spec = SPECS[qid]["spec"]
        gold = qs[qid]["gold"]
        row = {}
        for nm in ("strict", "mention_day", "tolerant"):
            r = run(qid, spec, None if nm == "strict" else nm)
            row[nm] = (r["answer"], verdict(r["answer"], gold),
                       len(r["evidence"]))
            if verdict(r["answer"], gold):
                tot[nm] += 1
        print(f"{qid:18} {str(gold):>6} "
              + " ".join(f"{str(row[nm][0])[:6]:>8}"
                         for nm in ("strict", "mention_day", "tolerant"))
              + "   " + " ".join("✓" if row[nm][1] else "✗"
                                for nm in ("strict", "mention_day",
                                           "tolerant")))
    print("\nrescued+preserved under each null policy:",
          {k: f"{v}/7" for k, v in tot.items()})


if __name__ == "__main__":
    main()
