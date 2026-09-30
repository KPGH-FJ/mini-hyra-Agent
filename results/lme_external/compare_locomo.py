"""Before/after comparison for the LoCoMo fix-stack validation.

Reads old + new hyp files and their OR-judged metrics, prints:
1. per-category accuracy table (before vs after, conv-0)
2. abstention rates per category (before vs after, conv-0; conv-1 after)
3. per-question reconciliation for cat2 (temporal) and cat5 (adversarial):
   qid, gold, old resp, new resp, verdict flip.
"""
import json
import sys
from collections import defaultdict

BASE = "/home/ubuntu/repos/mini-hyra-Agent/results/lme_external"
OLD_HYP = f"{BASE}/hyp_locomo_p12.jsonl"
NEW_C0 = f"{BASE}/hyp_locomo_c0_or.jsonl"
NEW_C1 = f"{BASE}/hyp_locomo_c1_or.jsonl"
M_OLD = f"{BASE}/metrics_locomo_c0_v5_or.json"
M_NEW0 = f"{BASE}/metrics_locomo_c0_or.json"
M_NEW1 = f"{BASE}/metrics_locomo_c1_or.json"

CATS = {1: "multi-hop", 2: "temporal", 3: "single-hop",
        4: "open-domain", 5: "adversarial"}
ABS = "enough information"


def load_hyp(p):
    return {json.loads(l)["qid"]: json.loads(l) for l in open(p)}


def load_m(p):
    d = json.load(open(p))
    return {r["qid"]: r["correct"] for r in d.get("rows", [])}, d


def acc_by_cat(verdicts, hyps):
    by = defaultdict(lambda: [0, 0])
    for qid, ok in verdicts.items():
        cat = hyps.get(qid, {}).get("category")
        if cat:
            by[cat][0] += ok
            by[cat][1] += 1
    return {c: (v[0] / v[1], v[0], v[1]) for c, v in sorted(by.items())}


def abst_by_cat(hyps):
    by = defaultdict(lambda: [0, 0])
    for r in hyps.values():
        by[r["category"]][1] += 1
        if ABS in r["response"].lower():
            by[r["category"]][0] += 1
    return {c: (v[0] / v[1], v[0], v[1]) for c, v in sorted(by.items())}


def main():
    old = load_hyp(OLD_HYP)
    new0 = load_hyp(NEW_C0)
    new1 = load_hyp(NEW_C1) if len(sys.argv) < 2 or sys.argv[1] != "noc1" \
        else {}
    vo, mo = load_m(M_OLD)
    vn, mn = load_m(M_NEW0)
    ao, an = acc_by_cat(vo, old), acc_by_cat(vn, new0)
    bo, bn = abst_by_cat(old), abst_by_cat(new0)
    print("## conv-0 accuracy (OR judge): before -> after")
    print("(before = v5 GLM ingest+answer; after = fix-stack OR "
          "ingest+answer — cross-model, not a clean per-q A/B)")
    print("| cat | v5 acc | v6 acc | v5 abstain | v6 abstain |")
    for c in sorted(CATS):
        a = ao.get(c, (0, 0, 0)); b = an.get(c, (0, 0, 0))
        x = bo.get(c, (0, 0, 0)); y = bn.get(c, (0, 0, 0))
        print(f"| {CATS[c]} | {a[1]}/{a[2]} ({a[0]:.0%}) | "
              f"{b[1]}/{b[2]} ({b[0]:.0%}) | {x[1]}/{x[2]} | {y[1]}/{y[2]} |")
    print(f"\noverall: v5 {mo['accuracy']:.1%} -> v6 {mn['accuracy']:.1%}  "
          f"(n={mo['n']} vs {mn['n']})")
    if new1:
        vn1, mn1 = load_m(M_NEW1)
        a1, b1 = acc_by_cat(vn1, new1), abst_by_cat(new1)
        print("\n## conv-1 after (OR judge)")
        print("| cat | acc | abstain |")
        for c in sorted(CATS):
            b = a1.get(c, (0, 0, 0)); y = b1.get(c, (0, 0, 0))
            print(f"| {CATS[c]} | {b[1]}/{b[2]} ({b[0]:.0%}) | "
                  f"{y[1]}/{y[2]} |")
        print(f"conv-1 overall: {mn1['accuracy']:.1%} (n={mn1['n']})")
    print("\n## per-question reconciliation — cat2 temporal + "
          "cat5 adversarial (conv-0)")
    for qid in sorted(old, key=lambda q: int(q.split("_q")[1])):
        o, n = old[qid], new0.get(qid)
        if not n or o["category"] not in (2, 5):
            continue
        oo = vo.get(qid); nn = vn.get(qid)
        flag = ("SAME" if oo == nn else
                ("FIXED" if nn else "REGRESSED"))
        print(f"\n### {qid} cat{o['category']} [{flag}] "
              f"v5={'T' if oo else 'F'} v6={'T' if nn else 'F'}")
        print("Q:", o["question"][:140])
        print("GOLD:", str(o["gold"])[:140])
        print("v5:", o["response"][:200])
        print("v6:", n["response"][:200])

main()
