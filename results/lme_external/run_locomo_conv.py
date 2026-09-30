"""Conv-scoped LoCoMo runner — same pipeline as locomo.py run(), but
restricted to a single conversation index (for conv-N comparisons).

Writes the same hyp row schema as locomo.py (qid/conv/category/question/
gold/response) so the shared judge can score it.
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

from lme import _make_llm  # noqa: E402
from lifemodel.model import LifeModel  # noqa: E402
from lifemodel.ingest_llm import LLMIngestor  # noqa: E402
from lifemodel.reader import aanswer  # noqa: E402
from locomo import _day_of, normalize_turns, sessions  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glm", action="store_true")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--data", required=True)
    ap.add_argument("--conv", type=int, required=True)
    ap.add_argument("--per-type", type=int, default=12)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    convs = json.load(open(args.data))
    c = convs[args.conv]
    qa_pairs = [(args.conv, qi, q) for qi, q in enumerate(c["qa"])]
    if args.per_type:
        by = defaultdict(list)
        for t in qa_pairs:
            by[t[2].get("category")].append(t)
        qa_pairs = [t for cat in sorted(by)
                    for t in by[cat][:args.per_type]]

    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            if line.strip():
                done.add(json.loads(line)["qid"])

    llm = _make_llm(args)
    llm_a = _make_llm(args, thinking=True)
    ing = LLMIngestor(llm, day_of=_day_of)
    m = LifeModel()
    for date, sess in sessions(convs[args.conv]["conversation"]):
        try:
            asyncio.run(ing.aingest_session(
                m, date, normalize_turns(sess)))
        except Exception as e:
            print(f"ingest fail @{date}: {e}", file=sys.stderr)

    fout = open(args.out, "a")
    for i, (ci, qi, q) in enumerate(qa_pairs):
        qid = f"c{ci}_q{qi}"
        if qid in done:
            continue
        try:
            resp = asyncio.run(aanswer(
                m, llm_a, q["question"], "2023 (post-conversation)"))[
                "response"]
        except Exception as e:
            resp = f"(error: {e})"
        fout.write(json.dumps({
            "qid": qid, "conv": ci, "category": q.get("category"),
            "question": q["question"], "gold": q.get("answer"),
            "response": resp}, ensure_ascii=False) + "\n")
        fout.flush()
        print(f"[{i+1}/{len(qa_pairs)}] {qid} "
              f"cat{q.get('category')} resp={resp[:60]!r}", flush=True)
    fout.close()


if __name__ == "__main__":
    main()
