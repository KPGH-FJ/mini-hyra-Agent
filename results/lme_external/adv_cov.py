#!/usr/bin/env python3
"""Expanded adversarial coverage — merged ANSWER_SYS on all cat5 of
LoCoMo conv-0..2, all-Atria.

Per conv: ingest every session once (snapshot-cached so a dead process
reuses the model), answer all cat5 rows with the verbatim package
ANSWER_SYS, then judge. Outputs adv_merged_c{i}.jsonl +
adv_merged_c{i}_metrics_atria.json next to this script.

Usage:
  python adv_cov.py --data locomo10.json --convs 0,1,2 \
      --api-key $KEY --base-url URL --model M           # answer phase
  python adv_cov.py --data locomo10.json --convs 0,1,2 --judge \
      --api-key $KEY --base-url URL --model M           # judge phase
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

JUDGE = """You are grading a memory system answer.
QUESTION: {q}
GOLD ANSWER: {a}
SYSTEM RESPONSE: {r}
Answer yes if the response conveys the gold answer (paraphrase OK).
{abs_note}Reply with only yes or no."""

ABS_NOTE = ("This question is UNANSWERABLE from the conversation; "
            "yes only if the response abstains/doesn't invent. ")

# harness mitigation for Atria's reasoning burn on extract calls —
# nudge toward terse direct JSON output (flagged in the report)
NUDGE = ("\n\nKeep it brief — output the JSON array only, terse "
         "records, no commentary, no reasoning dump.")


class _NudgedLLM:
    """Appends the terse-JSON nudge to every extract prompt."""

    def __init__(self, inner):
        self._i = inner

    async def complete(self, system, prompt):
        return await self._i.complete(system, prompt + NUDGE)

    @property
    def usage(self):
        return self._i.usage


def cat5_qs(conv, ci):
    rows = []
    for qi, q in enumerate(conv["qa"]):
        if q.get("category") == 5:
            rows.append({"qid": f"c{ci}_q{qi}", "category": 5,
                         "question": q["question"],
                         "gold": q.get("answer")})
    return rows


async def get_model(conv, ci, llm, out_dir, timeout=600):
    """Ingest all sessions once; per-session snapshot checkpoint +
    progress file so a kill/restart resumes. A session that dies or
    exceeds `timeout` retries on a halved body (marked partial), then
    is skipped as ingest-failed (bounded, recorded in the progress
    file for the report)."""
    cache = os.path.join(out_dir, f"ingest_c{ci}_atria.json")
    prog_path = os.path.join(out_dir, f"ingest_c{ci}_progress.json")
    prog = {"done": [], "failed": [], "partial": []}
    m = LifeModel()
    if os.path.exists(cache) and os.path.exists(prog_path):
        m.import_state(json.load(open(cache)))
        prog = json.load(open(prog_path))
        print(f"conv{ci}: resume snapshot, {len(prog['done'])} sessions "
              f"done, {len(prog['failed'])} failed", file=sys.stderr)
    elif os.path.exists(cache) and not os.path.exists(prog_path):
        # legacy cache from the uncheckpointed run — whole ingest done
        m.import_state(json.load(open(cache)))
        print(f"conv{ci}: loaded full snapshot {cache}", file=sys.stderr)
        return m
    ing = LLMIngestor(llm, day_of=_day_of)
    nrec = 0
    for date, sess in sessions(conv["conversation"]):
        if date in prog["done"] or date in prog["failed"]:
            continue
        turns = normalize_turns(sess)
        print(f"conv{ci} session {date} ({len(turns)} turns)",
              file=sys.stderr)
        try:
            got = await asyncio.wait_for(
                ing.aingest_session(m, date, turns), timeout)
        except Exception as e:
            print(f"conv{ci} session {date} attempt1 fail: {e}",
                  file=sys.stderr)
            try:  # halved body retry -> partial coverage
                got = await asyncio.wait_for(
                    ing.aingest_session(m, date,
                                        turns[: max(len(turns) // 2, 1)]),
                    timeout)
                prog["partial"].append(date)
                print(f"conv{ci} session {date}: partial (halved body)",
                      file=sys.stderr)
            except Exception as e2:
                print(f"conv{ci} session {date} INGEST-FAILED: {e2}",
                      file=sys.stderr)
                prog["failed"].append(date)
                json.dump(prog, open(prog_path, "w"))
                continue
        prog["done"].append(date)
        nrec += got
        print(f"conv{ci} session {date}: +{got} records (total {nrec})",
              file=sys.stderr)
        json.dump(prog, open(prog_path, "w"))
        json.dump(m.export()["asset"], open(cache, "w"))
    print(f"conv{ci} ingest done: {nrec} records "
          f"({len(prog['done'])} ok, {len(prog['partial'])} partial, "
          f"{len(prog['failed'])} failed)", file=sys.stderr)
    return m


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--convs", default="0,1,2")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out-dir", default=os.path.dirname(__file__))
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()

    convs = json.load(open(args.data))
    cis = [int(c) for c in args.convs.split(",")]

    if args.judge:
        jllm = _make_llm(args)
        for ci in cis:
            path = os.path.join(args.out_dir, f"adv_merged_c{ci}.jsonl")
            if not os.path.exists(path):
                continue
            rows, correct = [], 0
            for line in open(path):
                h = json.loads(line)
                note = "" if h.get("gold") else ABS_NOTE
                p = JUDGE.format(q=h["question"], a=h.get("gold"),
                                 r=h["response"], abs_note=note)
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
            out = {"conv": ci, "n": len(rows), "adv_acc":
                   correct / max(len(rows), 1), "rows": rows}
            mp = os.path.join(args.out_dir,
                              f"adv_merged_c{ci}_metrics_atria.json")
            json.dump(out, open(mp, "w"), indent=2)
            print(f"c{ci} adv_acc {correct}/{len(rows)}", flush=True)
        return

    llm = _NudgedLLM(_make_llm(args))        # extract (+ terse-JSON nudge)
    llm_a = _make_llm(args, thinking=True)   # answer
    for ci in cis:
        conv = convs[ci]
        qset = cat5_qs(conv, ci)
        print(f"conv{ci}: {len(qset)} cat5 questions", file=sys.stderr)
        m = await get_model(conv, ci, llm, args.out_dir)
        out_path = os.path.join(args.out_dir, f"adv_merged_c{ci}.jsonl")
        done = set()
        if os.path.exists(out_path):         # resume support
            for line in open(out_path):
                done.add(json.loads(line)["qid"])
        out = open(out_path, "a")
        for row in qset:
            if row["qid"] in done:
                continue
            try:
                resp = (await R.aanswer(
                    m, llm_a, row["question"],
                    "2023 (post-conversation)"))["response"]
            except Exception as e:
                resp = f"(error: {e})"
            out.write(json.dumps({**row, "response": resp},
                                 ensure_ascii=False) + "\n")
            out.flush()
            print(f"[c{ci}] {row['qid']} {resp[:70]!r}", flush=True)
        out.close()


if __name__ == "__main__":
    asyncio.run(main())
