#!/usr/bin/env python3
"""Relaxed-gate cat5 regression sentinel (LoCoMo conv-0).

PR #67 (333e9c8, OPEN at run time — main still strict) relaxes the
premise gate: premise_expected=False -> NO_PREMISE pass-through;
synthesis_needed=True -> SYNTHESIS_OK iff every atom bound a record.
Factual defense unchanged (unbound atom -> ABSENT; non-synthesis
splice -> SPLICED). Sentinal question: does the relaxed gate leak
the adversarial defense? Spliced-premise fakes (q182-type) should
still refuse — their who/event atoms can't all bind.

conv-0 stock snapshot (ingest_c0_atria.json), premise_check=
"relaxed", Atria answer + Atria judge for the stock-74.5%
comparison; records verdicts for abstain-form forensics.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A                              # noqa: E402

from lme import _make_llm                        # noqa: E402
import lifemodel.reader as R                    # noqa: E402

OUT = "rlx_cat5_c0.jsonl"
MET = "rlx_cat5_c0_metrics_atria.json"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out-dir", default=os.path.dirname(__file__))
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    convs = json.load(open(args.data))

    if args.judge:
        jllm = _make_llm(argparse.Namespace(
            api_key=os.environ.get("ATRIA_API_KEY"),
            base_url="https://api.atria-asi.ai/v1",
            model="Atria-Dawn-Preview"))
        rows = [json.loads(l) for l in
                open(os.path.join(args.out_dir, OUT))]
        for h in rows:
            if "correct" in h:
                continue
            note = "" if h.get("gold") else A.ABS_NOTE
            p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                               r=h["response"], abs_note=note)
            v = "err"
            for _ in range(4):
                try:
                    v = (await jllm.complete(
                        "You are a strict grader.", p)).strip().lower()
                    break
                except Exception:
                    continue
            h["correct"] = (None if v == "err"
                            else v.startswith("yes"))
            print(f"  {h['qid']}[{h.get('verdict')}] -> {v!r}",
                  flush=True)
        with open(os.path.join(args.out_dir, OUT), "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n = len(rows)
        judged = [r for r in rows if r.get("correct") is not None]
        strict = sum(1 for r in judged if r["correct"])
        json.dump({"n": n, "judged": len(judged),
                   "strict": strict,
                   "strict_acc": round(strict / n, 4),
                   "unjudged": n - len(judged)},
                  open(os.path.join(args.out_dir, MET), "w"),
                  indent=2)
        print(f"METRICS {strict}/{n} strict "
              f"({len(judged)} judged)", flush=True)
        return

    llm = _make_llm(argparse.Namespace(
        api_key=os.environ.get("ATRIA_API_KEY"),
        base_url="https://api.atria-asi.ai/v1",
        model="Atria-Dawn-Preview"), thinking=True)
    m = await A.get_model(convs[0], 0, llm, args.out_dir)
    qset = A.cat5_qs(convs[0], 0)
    out_path = os.path.join(args.out_dir, OUT)
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["qid"] for l in open(out_path)}
    out = open(out_path, "a")
    for row in qset:
        if row["qid"] in done:
            continue
        try:
            r = await R.aanswer(m, llm, row["question"],
                                "2023 (post-conversation)",
                                premise_check="relaxed")
            ver = (r.get("verify") or {}).get("verdict")
            rec = {**row, "response": r["response"], "verdict": ver}
        except Exception as e:
            rec = {**row, "response": f"(error: {e})",
                   "verdict": "ERROR"}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        print(f"{row['qid']} [{rec['verdict']}] "
              f"{rec['response'][:110]!r}", flush=True)
    out.close()


if __name__ == "__main__":
    asyncio.run(main())
