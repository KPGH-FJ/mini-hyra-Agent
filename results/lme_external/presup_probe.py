#!/usr/bin/env python3
"""Counterfactual/presupposition lesion probe — ANSWER_SYS prototype.

Lesions: cat5 questions scored WRONG on the best available arm because
the model bridged an unrecorded premise into an answer (not the
mislabel family fixed by attribution). Baseline responses come from the
existing hyp files; the probe answers the same questions on the same
model snapshots with merged ANSWER_SYS + PRESUPPOSITION CHECK and
judges the delta.

Lesion set:
  conv-0 (audit-ingest model): q161 q182 q184 q188 (+bind-reg q166)
  conv-1 (stock model):        q91 q95
  conv-2 (stock model):        q162 q168 q186
Every cat5 gold is null -> abstention is always the right verdict, so
the clause cannot over-fire inside this set (noted in report).
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

PRESUP = """
- PRESUPPOSITION CHECK: the question may assume an event, attribute,
  role, or detail the memory never recorded. Before answering, test the
  premise itself: is the presumed fact present? A related or near-miss
  record is NOT evidence for the presumed one — never bridge related
  content into an answer. If the premise is absent, say "no record of
  <premise>" and abstain."""

# qid -> (conv, snapshot stem, question text)
LESIONS = [
    ("c0_q161", 0, "attr_audit_c0_atria.json"),
    ("c0_q182", 0, "attr_audit_c0_atria.json"),
    ("c0_q184", 0, "attr_audit_c0_atria.json"),
    ("c0_q188", 0, "attr_audit_c0_atria.json"),
    ("c0_q166", 0, "attr_audit_c0_atria.json"),
    ("c1_q91", 1, "ingest_c1_atria.json"),
    ("c1_q95", 1, "ingest_c1_atria.json"),
    ("c2_q162", 2, "ingest_c2_atria.json"),
    ("c2_q168", 2, "ingest_c2_atria.json"),
    ("c2_q186", 2, "ingest_c2_atria.json"),
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
        rows, correct = [], 0
        for line in open(os.path.join(args.out_dir,
                                      "presup_probe.jsonl")):
            h = json.loads(line)
            p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                               r=h["response"], abs_note=A.ABS_NOTE)
            try:
                v = (await jllm.complete(
                    "You are a strict grader.", p)).strip().lower()
            except Exception as e:
                print("judge fail", h["qid"], e, file=sys.stderr)
                v = "no"
            ok = v.startswith("yes")
            correct += ok
            rows.append({"qid": h["qid"], "correct": ok,
                         "response": h["response"]})
        out = {"arm": "merged+presup", "n": len(rows),
               "acc": correct / max(len(rows), 1), "rows": rows}
        json.dump(out, open(os.path.join(
            args.out_dir, "presup_probe_metrics_atria.json"), "w"),
            indent=2)
        print(f"presup {correct}/{len(rows)}", flush=True)
        return

    llm_a = _make_llm(args, thinking=True)
    models = {}
    for _, ci, snap in LESIONS:
        if ci in models:
            continue
        m = LifeModel()
        m.import_state(json.load(
            open(os.path.join(args.out_dir, snap))))
        models[ci] = m
    qs = {}
    for qid, ci, _ in LESIONS:
        qi = int(qid.split("_q")[1])
        qs[qid] = convs[ci]["qa"][qi]["question"]
    R.ANSWER_SYS = R.ANSWER_SYS + PRESUP
    out = open(os.path.join(args.out_dir, "presup_probe.jsonl"), "w")
    for qid, ci, _ in LESIONS:
        try:
            resp = (await R.aanswer(
                models[ci], llm_a, qs[qid],
                "2023 (post-conversation)"))["response"]
        except Exception as e:
            resp = f"(error: {e})"
        out.write(json.dumps({"qid": qid, "conv": ci,
                              "question": qs[qid], "gold": None,
                              "response": resp},
                             ensure_ascii=False) + "\n")
        out.flush()
        print(f"{qid} {resp[:80]!r}", flush=True)
    out.close()


if __name__ == "__main__":
    asyncio.run(main())
