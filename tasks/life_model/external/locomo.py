#!/usr/bin/env python3
"""LoCoMo external exam adapter (secondary benchmark).

Dataset: github.com/snap-research/locomo — data/locomo10.json.
10 long multi-session conversations between two speakers; ~200 QA per
conversation, categories 1-5 (1 multi-hop, 2 temporal, 3 single-hop,
4 adversarial/unanswerable, 5 open-domain).

Difference vs LongMemEval: BOTH speakers are principals. Every
extracted record gets about=<speaker or mentioned person>; source is
the speaking party. The lifemodel stores 3-part entity vertices
(src|about|slot), so per-person memory stays separated.

Usage:
  python locomo.py --glm run --data locomo10.json --n 30 --out hyp.jsonl
  python locomo.py --glm judge --hyp hyp.jsonl --ref locomo10.json --out m.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lme import _make_llm  # noqa: E402 — reuse backend plumbing
from lifemodel.model import LifeModel  # noqa: E402
from lifemodel.ingest_llm import LLMIngestor  # noqa: E402
from lifemodel.reader import aanswer  # noqa: E402

CAT = {1: "multi-hop", 2: "temporal", 3: "single-hop",
       4: "open-domain", 5: "adversarial"}

ABS = "I don't have enough information to answer that."


def sessions(conv: dict) -> list:
    """-> [(date_label, [{speaker, text}])]"""
    keys = sorted((k for k in conv
                   if k.startswith("session_")
                   and not k.endswith("_date_time")),
                  key=lambda k: int(k.split("_")[1]))
    out = []
    for k in keys:
        label = conv.get(k + "_date_time", "")
        try:  # '1:56 pm on 8 May, 2023' -> '2023-05-08' as resolution anchor
            import datetime as dt
            label = dt.date.fromordinal(_day_of(label)).isoformat()
        except Exception:
            pass
        out.append((label, conv[k]))
    return out


def _day_of(date_label: str) -> int:
    """LoCoMo dates like '1:56 pm on 8 May, 2023' or ISO '2023-05-08'."""
    import datetime as dt
    import re
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_label)
    if m:
        y, mo, d = m.groups()
        return dt.date(int(y), int(mo), int(d)).toordinal()
    m = re.search(r"(\d{1,2})\s+(\w+),?\s+(\d{4})", date_label)
    if m:
        d, mon, y = m.groups()
        try:
            return dt.date(int(y),
                           dt.datetime.strptime(mon[:3], "%b").month,
                           int(d)).toordinal()
        except Exception:
            pass
    return abs(hash(date_label)) % 100000


def normalize_turns(turns: list) -> list:
    return [{"role": "user" if t["speaker"] else "user",
             "content": f'{t["speaker"]}: {t["text"]}'} for t in turns]


def run(args):
    convs = json.load(open(args.data))
    qa_pairs = []
    for ci, c in enumerate(convs):
        for qi, q in enumerate(c["qa"]):
            qa_pairs.append((ci, qi, q))
    if args.per_type:
        by = defaultdict(list)
        for t in qa_pairs:
            by[t[2].get("category")].append(t)
        qa_pairs = [t for cat in sorted(by)
                    for t in by[cat][:args.per_type]]
    if args.n:
        qa_pairs = qa_pairs[:args.n]
    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                done.add(json.loads(line)["qid"])
            except Exception:
                pass
    llm = _make_llm(args)
    llm_a = _make_llm(args, thinking=True)
    ing = LLMIngestor(llm, day_of=_day_of)
    models: dict = {}
    fout = open(args.out, "a")
    for i, (ci, qi, q) in enumerate(qa_pairs):
        qid = f"c{ci}_q{qi}"
        if qid in done:
            continue
        if ci not in models:
            models.clear()  # one lifemodel at a time; conversation-scoped
            m = LifeModel()
            for date, sess in sessions(convs[ci]["conversation"]):
                try:
                    asyncio.run(ing.aingest_session(
                        m, date, normalize_turns(sess)))
                except Exception as e:
                    print(f"[{qid}] ingest fail @{date}: {e}",
                          file=sys.stderr)
            models[ci] = m
        m = models[ci]
        try:
            resp = asyncio.run(aanswer(
                m, llm_a, q["question"], "2023 (post-conversation)",
                premise_check="relaxed", assist=True))["response"]
        except Exception as e:
            resp = f"(error: {e})"
        fout.write(json.dumps({
            "qid": qid, "conv": ci, "category": q.get("category"),
            "question": q["question"], "gold": q.get("answer"),
            "response": resp}, ensure_ascii=False) + "\n")
        fout.flush()
        print(f"[{i+1}/{len(qa_pairs)}] {qid} "
              f"cat{q.get('category')} resp={resp[:60]!r}")


JUDGE = """You are grading a memory system answer.
QUESTION: {q}
GOLD ANSWER: {a}
SYSTEM RESPONSE: {r}
Answer yes if the response conveys the gold answer (paraphrase OK).
{abs_note}Reply with only yes or no."""


def judge(args):
    ref = json.load(open(args.ref))
    gold = {}
    for ci, c in enumerate(ref):
        for qi, q in enumerate(c["qa"]):
            gold[f"c{ci}_q{qi}"] = q
    jllm = _make_llm(args, backend=args.judge_backend)
    rows = []
    for line in open(args.hyp):
        h = json.loads(line)
        g = gold.get(h["qid"])
        if not g:
            continue
        is_abs = h["category"] == 5
        note = ("This question is UNANSWERABLE from the conversation; "
                "yes only if the response abstains/doesn't invent. "
                if is_abs else "")
        p = JUDGE.format(q=g["question"], a=g.get("answer"),
                         r=h["response"], abs_note=note)
        try:
            v = asyncio.run(jllm.complete(
                "You are a strict grader.", p)).strip().lower()
        except Exception:
            v = "no"
        rows.append({"qid": h["qid"], "category": h["category"],
                     "correct": v.startswith("yes")})
    by = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["category"]][0] += r["correct"]
        by[r["category"]][1] += 1
    out = {"n": len(rows),
           "accuracy": sum(r["correct"] for r in rows) / max(len(rows), 1),
           "by_type": {f'{c}:{CAT.get(c)}': v[0] / v[1]
                       for c, v in sorted(by.items())},
           "rows": rows}
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"},
                     ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glm", action="store_true")
    ap.add_argument("--judge-backend", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", required=True)
    r.add_argument("--n", type=int)
    r.add_argument("--per-type", type=int)
    r.add_argument("--out", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--hyp", required=True)
    j.add_argument("--ref", required=True)
    j.add_argument("--out", required=True)
    j.add_argument("--judge-backend", default=None)
    args = ap.parse_args()
    if args.api_key is None and args.glm:
        args.api_key = os.environ.get("GLM_API_KEY")
    if args.cmd == "run":
        run(args)
    else:
        judge(args)


if __name__ == "__main__":
    main()
