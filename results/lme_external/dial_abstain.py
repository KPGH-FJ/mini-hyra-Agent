#!/usr/bin/env python3
"""Abstention-precision dial ablation — ANSWER_SYS variants on LoCoMo conv-0.

One shared ingest of conv-0 (the dial only touches the reader prompt),
then per-arm answers over a 22-question set: all 12 cat5 (adversarial)
+ 10 recall-guard questions that v6 answered correctly (from
metrics_locomo_c0_or.json) — the guard catches a dial turned too far
into abstention.

Usage:
  python dial_abstain.py --data locomo10.json --hyp-c0 hyp_locomo_c0_or.jsonl \
      --metrics-c0 metrics_locomo_c0_or.json --arm evreq|presup|hedge|all
Each arm writes results/lme_external/dial_<arm>.jsonl and prints a
per-question line. Judge separately with judge_dial().
"""
import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                     / "tasks" / "life_model" / "external"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lme import _make_llm                      # noqa: E402
from locomo import _day_of, normalize_turns, sessions  # noqa: E402
from lifemodel.model import LifeModel           # noqa: E402
from lifemodel.ingest_llm import LLMIngestor    # noqa: E402
import lifemodel.reader as R                    # noqa: E402

BASE_SYS = R.ANSWER_SYS

ARMS = {
    # verbatim stack from the imported lifemodel.reader (used for the
    # merged-stack validation: EVIDENCE RULE + SUBJECT CHECK shipped in
    # the package, not appended here)
    "merged": BASE_SYS,
    "evreq": BASE_SYS + """

- EVIDENCE RULE: before asserting an answer, you must be able to point
  to a specific memory entry (a value plus its date) that supports it.
  If memory only supports adjacent facts — not the specific thing asked —
  say exactly "Memory only records X; it does not answer Y."
  Never present adjacent facts as the answer.""",
    "presup": BASE_SYS + """

- PRESUPPOSITION CHECK: first ask what the question assumes. If it
  presupposes an event, attribute, or relationship that has NO record
  in memory, say that it is not recorded — do not answer a different,
  related question.""",
    "hedge": BASE_SYS + """

- HEDGING: when memory does not fully support the answer, give a
  bounded partial answer instead of a complete one — state what IS
  recorded and flag that the asked part is not recorded. A partial
  honest answer beats a confident fabrication. Never invent details
  to fill gaps.""",
    "evhedge": BASE_SYS + """

- EVIDENCE RULE: before asserting an answer, you must be able to point
  to a specific memory entry (a value plus its date) that supports it.
  If memory only supports adjacent facts — not the specific thing asked —
  say exactly "Memory only records X; it does not answer Y."
  Never present adjacent facts as the answer.
- HEDGING: when memory does not fully support the answer, give a
  bounded partial answer instead of a complete one — state what IS
  recorded and flag that the asked part is not recorded. A partial
  honest answer beats a confident fabrication. Never invent details
  to fill gaps.""",
}

JUDGE = """You are grading a memory system answer.
QUESTION: {q}
GOLD ANSWER: {a}
SYSTEM RESPONSE: {r}
Answer yes if the response conveys the gold answer (paraphrase OK).
{abs_note}Reply with only yes or no."""

ABS_NOTE = ("This question is UNANSWERABLE from the conversation; "
            "yes only if the response abstains/doesn't invent. ")


def pick_qs(conv, hyp_c0, metrics_c0, k_guard=10):
    """All cat5 inside the conv-0 60-slice + k_guard questions v6
    answered correctly (non-cat5). Restrict to the same slice the v6
    run scored: only qids present in hyp_c0."""
    correct = {r["qid"] for r in metrics_c0["rows"] if r["correct"]}
    in_slice = {h["qid"]: h for h in hyp_c0}
    adv, guard = [], []
    for qi, q in enumerate(conv["qa"]):
        qid = f"c0_q{qi}"
        if qid not in in_slice:
            continue
        row = {"qid": qid, "category": q.get("category"),
               "question": q["question"], "gold": q.get("answer")}
        if q.get("category") == 5:
            adv.append(row)
        elif qid in correct and len(guard) < k_guard:
            guard.append(row)
    return adv, guard


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--hyp-c0", required=True)
    ap.add_argument("--metrics-c0", required=True)
    ap.add_argument("--arm", default="all",
                    choices=list(ARMS) + ["all"])
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out-dir", default=os.path.dirname(__file__))
    ap.add_argument("--judge", action="store_true",
                    help="judge existing dial_*.jsonl instead of answering")
    args = ap.parse_args()

    convs = json.load(open(args.data))
    conv = convs[0]
    mc0 = json.load(open(args.metrics_c0))
    hyp_c0 = [json.loads(l) for l in open(args.hyp_c0)]
    adv, guard = pick_qs(conv, hyp_c0, mc0)
    qset = adv + guard
    print(f"qset: {len(adv)} adversarial + {len(guard)} recall-guard",
          file=sys.stderr)

    if args.judge:
        # judge follows the same --api-key/--base-url/--model flags —
        # Atria judged runs need no extra_body (Atria 400s on reasoning)
        jllm = _make_llm(args)
        arms_to_judge = [args.arm] if args.arm != "all" else list(ARMS)
        for arm in arms_to_judge:
            path = f"{args.out_dir}/dial_{arm}.jsonl"
            if not os.path.exists(path):
                continue
            rows, by = [], defaultdict(lambda: [0, 0])
            for line in open(path):
                h = json.loads(line)
                note = ABS_NOTE if h["category"] == 5 else ""
                p = JUDGE.format(q=h["question"], a=h["gold"],
                                 r=h["response"], abs_note=note)
                try:
                    v = (await jllm.complete(
                        "You are a strict grader.", p)).strip().lower()
                except Exception as e:
                    print("judge fail", h["qid"], e, file=sys.stderr)
                    v = "no"
                ok = v.startswith("yes")
                rows.append({"qid": h["qid"], "category": h["category"],
                             "correct": ok})
                by[h["category"]][0] += ok
                by[h["category"]][1] += 1
            out = {"arm": arm, "n": len(rows),
                   "accuracy": sum(r["correct"] for r in rows)
                   / max(len(rows), 1),
                   "by_cat": {c: v[0] / v[1] for c, v in sorted(by.items())},
                   "rows": rows}
            suf = "_atria" if "atria" in (args.base_url or "") else ""
            mp = f"{args.out_dir}/dial_{arm}_metrics{suf}.json"
            json.dump(out, open(mp, "w"), indent=2)
            print(arm, json.dumps({k: v for k, v in out.items()
                                   if k != "rows"}))
        return

    llm = _make_llm(args)                    # non-thinking (extract)
    llm_a = _make_llm(args, thinking=True)   # answer (effort=low)
    m = LifeModel()
    ing = LLMIngestor(llm, day_of=_day_of)
    nrec = 0
    for date, sess in sessions(conv["conversation"]):
        try:
            nrec += await ing.aingest_session(m, date,
                                              normalize_turns(sess))
        except Exception as e:
            print(f"ingest fail @{date}: {e}", file=sys.stderr)
    print(f"ingest done: {nrec} records", file=sys.stderr)

    arms = list(ARMS) if args.arm == "all" else [args.arm]
    for arm in arms:
        R.ANSWER_SYS = ARMS[arm]
        out = open(f"{args.out_dir}/dial_{arm}.jsonl", "w")
        for row in qset:
            try:
                resp = (await R.aanswer(
                    m, llm_a, row["question"],
                    "2023 (post-conversation)"))["response"]
            except Exception as e:
                resp = f"(error: {e})"
            out.write(json.dumps({**row, "response": resp},
                                 ensure_ascii=False) + "\n")
            out.flush()
            print(f"[{arm}] {row['qid']} cat{row['category']} "
                  f"{resp[:70]!r}", flush=True)
        out.close()
    R.ANSWER_SYS = BASE_SYS


if __name__ == "__main__":
    asyncio.run(main())
