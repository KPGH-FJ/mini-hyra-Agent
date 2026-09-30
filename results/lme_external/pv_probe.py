#!/usr/bin/env python3
"""Premise-verification prototype probe — reader-side mechanism, not a clause.

Runs `aanswer(..., premise_check=True)` over three sets on saved model
snapshots:
- LESIONS: cat5 questions the merged stack still confabulates on —
  spliced premises (q182), detail-confab bridges (q95 trophy, q162
  art-scope, q91 store->studio), and lexical premise swaps (q166, q186)
  that the PRESUP clause fixed (mechanism should also catch them).
- GUARDS: questions with REAL supporting records that must still be
  answered — the over-fire control. Includes the three cat5
  benchmark-label artifacts (q161/q184/q188, transcript-verified
  answerable) plus two normal answerable questions.
- ADV_CTRL: cat5 questions the merged stack already abstains correctly
  on — regression control (must stay abstain).

Every row records the verify verdict + atoms for forensics.
Judge: abstention-judged for cat5 rows, gold-judged for guard rows.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A  # noqa: E402

from lme import _make_llm                       # noqa: E402
from lifemodel.model import LifeModel            # noqa: E402
import lifemodel.reader as R                    # noqa: E402

# (qid, conv, snapshot, lesion-type) — expect abstain
LESIONS = [
    ("c0_q182", 0, "attr_audit_c0_atria.json", "splice"),
    ("c0_q156", 0, "attr_audit_c0_atria.json", "bridge"),
    ("c0_q166", 0, "attr_audit_c0_atria.json", "lexical"),
    ("c1_q91", 1, "ingest_c1_atria.json", "bridge"),
    ("c1_q95", 1, "ingest_c1_atria.json", "detail-confab"),
    ("c2_q162", 2, "ingest_c2_atria.json", "bridge"),
    ("c2_q186", 2, "ingest_c2_atria.json", "lexical"),
]
# (qid, conv, snapshot) — expect correct gold answer
GUARDS = [
    ("c0_q161", 0, "attr_audit_c0_atria.json"),
    ("c0_q184", 0, "attr_audit_c0_atria.json"),
    ("c0_q188", 0, "attr_audit_c0_atria.json"),
    ("c0_q3", 0, "attr_audit_c0_atria.json"),
    ("c0_q10", 0, "attr_audit_c0_atria.json"),
]
# (qid, conv, snapshot) — expect abstain (already clean under merged)
ADV_CTRL = [
    ("c1_q79", 1, "ingest_c1_atria.json"),
    ("c2_q152", 2, "ingest_c2_atria.json"),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--api-key", default=os.environ.get("API_KEY"))
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--out-dir",
                    default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    convs = json.load(open(args.data))

    if args.judge:
        jllm = _make_llm(args)
        rows, groups = [], {"lesion": [0, 0], "guard": [0, 0],
                            "adv_ctrl": [0, 0]}
        for line in open(os.path.join(args.out_dir, "pv_probe.jsonl")):
            h = json.loads(line)
            if h["kind"] == "guard":
                note = ""
            else:
                note = A.ABS_NOTE
            p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                               r=h["response"], abs_note=note)
            try:
                v = (await jllm.complete(
                    "You are a strict grader.", p)).strip().lower()
            except Exception as e:
                print("judge fail", h["qid"], e, file=sys.stderr)
                v = "no"
            ok = v.startswith("yes")
            groups[h["kind"]][0] += ok
            groups[h["kind"]][1] += 1
            rows.append({"qid": h["qid"], "kind": h["kind"],
                         "verdict": h.get("verdict"), "correct": ok})
        n = sum(g[1] for g in groups.values())
        acc = sum(g[0] for g in groups.values()) / max(n, 1)
        out = {"arm": "merged+pverify", "n": n, "acc": acc,
               "by_kind": {k: f"{v[0]}/{v[1]}"
                           for k, v in groups.items()},
               "rows": rows}
        json.dump(out, open(os.path.join(
            args.out_dir, "pv_probe_metrics_atria.json"), "w"),
            indent=2)
        print(json.dumps({k: v for k, v in out.items()
                          if k != "rows"}), flush=True)
        return

    llm_a = _make_llm(args, thinking=True)
    items = ([(q, c, s, "lesion", t) for q, c, s, t in LESIONS]
             + [(q, c, s, "guard", None) for q, c, s in GUARDS]
             + [(q, c, s, "adv_ctrl", None) for q, c, s in ADV_CTRL])
    models = {}
    for _, ci, snap, _, _ in items:
        if ci in models:
            continue
        m = LifeModel()
        m.import_state(json.load(
            open(os.path.join(args.out_dir, snap))))
        models[ci] = m
    out = open(os.path.join(args.out_dir, "pv_probe.jsonl"), "w")
    for qid, ci, _, kind, ltype in items:
        qi = int(qid.split("_q")[1])
        q = convs[ci]["qa"][qi]
        try:
            r = await R.aanswer(models[ci], llm_a, q["question"],
                                "2023 (post-conversation)",
                                premise_check=True)
            resp, verify = r["response"], r.get("verify") or {}
        except Exception as e:
            resp, verify = f"(error: {e})", {}
        rec = {"qid": qid, "conv": ci, "kind": kind, "ltype": ltype,
               "question": q["question"], "gold": q.get("answer"),
               "response": resp,
               "verdict": verify.get("verdict"),
               "atoms": verify.get("atoms")}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        print(f"{kind[:4]} {qid} [{verify.get('verdict')}] "
              f"{resp[:70]!r}", flush=True)
    out.close()


if __name__ == "__main__":
    asyncio.run(main())
