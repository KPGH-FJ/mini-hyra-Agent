#!/usr/bin/env python3
"""v3-probe: did the canonical-frame prompt fix the stage-3 failure modes?

For each question, prints the GOLD records' typed fields under the base
(v1/v2) prompt vs the v3 canonical-frame prompt, and what changed:
- verb canonicalized toward the annotation frame?
- counterparty now populated (entity preserved)?
- kind flipped planned->asserted on obligation records?
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "results/lme_resid150/stage2"
D = json.load(open("results/lme_resid150/stage1/annotations.json"))
QIDS = ["0a995998", "88432d0a", "d682f1a2", "b5ef892d", "gpt4_f2262a51"]
FLDS = ("kind", "verb", "object", "object_class", "obligation_status",
        "counterparty", "when_abs", "duration_value", "duration_unit")


def load(qid, suf):
    if suf == "_v3":
        p = f"{OUT}/typed_{qid}_v3.json"
        return json.load(open(p)) if os.path.exists(p) else None
    for s in ("_v2", ""):
        p = f"{OUT}/typed_{qid}{s}.json"
        if os.path.exists(p):
            return json.load(open(p))
    return None


def main():
    qs = {q["qid"]: q for q in D["questions"]}
    for qid in QIDS:
        base = load(qid, "")
        v3 = load(qid, "_v3")
        if base is None or v3 is None:
            print(f"== {qid}: missing file (base={base is not None}, "
                  f"v3={v3 is not None})")
            continue
        bt, vt = base["typed"], v3["typed"]
        print(f"{'='*28} {qid}")
        print(f"Q: {qs[qid]['question'][:100]}")
        n_changes = 0
        for r in qs[qid]["records"]:
            rid = r["rid"]
            if rid not in bt or rid not in vt:
                continue
            diffs = []
            for f in FLDS:
                a, b = bt[rid].get(f), vt[rid].get(f)
                if a != b:
                    diffs.append(f"{f}: {a!r} -> {b!r}")
            tag = "GOLD" if r.get("counts_toward") else "    "
            if diffs:
                n_changes += 1
                print(f"  {tag} {rid}")
                for d in diffs:
                    print(f"      {d}")
        gold = [r for r in qs[qid]["records"] if r.get("counts_toward")]
        print(f"  -- {n_changes} records changed / "
              f"{len(gold)} gold records")
        cp_new = sum(1 for rid, t in vt.items()
                     if t.get("counterparty") and
                     not bt.get(rid, {}).get("counterparty"))
        print(f"  -- counterparty newly populated: {cp_new}")
        kinds = {}
        for rid, t in vt.items():
            kinds[t.get("kind")] = kinds.get(t.get("kind"), 0) + 1
        print(f"  -- v3 kind dist: {kinds}")


if __name__ == "__main__":
    main()
