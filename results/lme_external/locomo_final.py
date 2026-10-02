#!/usr/bin/env python3
"""LoCoMo final-stack full benchmark (10 convs x all categories).

Final stack = current ingest (merged speaker-binding + self-contained
bullets) + aanswer(premise_check="relaxed", assist=True) — the #73 PR
head (05f4199) semantics. Atria for ingest/answer/judge.

Phases (each resumable, run in order):
  ingest : per-conv checkpointed LLMIngestor -> ingest_final_c{i}.json
           (+ _progress.json with done/partial/failed sessions)
  run    : answer every QA through the final stack ->
           locomo_final_c{i}.jsonl (qid resume, per-q flush,
           900s per-question timeout -> verdict=TIMEOUT)
  judge  : Atria strict-grader -> locomo_final_metrics_atria.json
           (per-conv + per-category + total)

Judge note rule follows adv_cov (ABS_NOTE iff no gold) so the numbers
stay comparable with every prior arm in DIAL_ABSTAIN.md.

Usage:
  python3 locomo_final.py --data /home/ubuntu/locomo/locomo10.json \
      --phase ingest --convs 0-9
  python3 locomo_final.py --data ... --phase run --convs 0-9
  python3 locomo_final.py --data ... --phase judge --convs 0-9
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A                              # noqa: E402

from lme import _make_llm                        # noqa: E402
from lifemodel.model import LifeModel            # noqa: E402
from lifemodel.ingest_llm import LLMIngestor     # noqa: E402
import lifemodel.reader as R                     # noqa: E402

QD = "2023 (post-conversation)"
ANS_SEM = 8
JDG_SEM = 8
SESS_TIMEOUT = 600
ANS_TIMEOUT = 900


def atria_llm(thinking=False):
    return _make_llm(argparse.Namespace(
        api_key=os.environ.get("ATRIA_API_KEY"),
        base_url="https://api.atria-asi.ai/v1",
        model="Atria-Dawn-Preview"), thinking=thinking)


def _conv_range(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


# ---------- phase: ingest -------------------------------------------------

async def ingest_conv(conv, ci, llm, out_dir):
    cache = os.path.join(out_dir, f"ingest_final_c{ci}.json")
    prog_path = os.path.join(out_dir, f"ingest_final_c{ci}_progress.json")
    prog = {"done": [], "failed": [], "partial": []}
    m = LifeModel()
    if os.path.exists(cache):
        m.import_state(json.load(open(cache)))
    if os.path.exists(prog_path):
        prog = json.load(open(prog_path))
        print(f"conv{ci}: resume ({len(prog['done'])} done, "
              f"{len(prog['failed'])} failed, "
              f"{len(prog['partial'])} partial)", flush=True)
    ing = LLMIngestor(A._NudgedLLM(llm), day_of=A._day_of)
    nrec = len(prog["done"])
    for date, sess in A.sessions(conv["conversation"]):
        if date in prog["done"] or date in prog["failed"]:
            continue
        turns = A.normalize_turns(sess)
        print(f"conv{ci} session {date} ({len(turns)} turns)",
              flush=True)
        try:
            got = await asyncio.wait_for(
                ing.aingest_session(m, date, turns), SESS_TIMEOUT)
        except Exception as e:
            print(f"conv{ci} {date} attempt1 fail: {e}", flush=True)
            try:
                got = await asyncio.wait_for(
                    ing.aingest_session(
                        m, date, turns[: max(len(turns) // 2, 1)]),
                    SESS_TIMEOUT)
                prog["partial"].append(date)
                print(f"conv{ci} {date}: partial", flush=True)
            except Exception as e2:
                prog["failed"].append(date)
                print(f"conv{ci} {date} INGEST-FAILED: {e2}",
                      flush=True)
                json.dump(prog, open(prog_path, "w"))
                continue
        prog["done"].append(date)
        nrec += got
        json.dump(m.export()["asset"], open(cache, "w"))
        json.dump(prog, open(prog_path, "w"))
        print(f"conv{ci} {date}: +{got} records ({nrec} sess-records)",
              flush=True)
    if os.path.exists(cache):
        print(f"conv{ci}: ingest done -> {cache}", flush=True)


# ---------- phase: run ----------------------------------------------------

async def run_conv(conv, ci, llm, out_dir, wait=18 * 3600):
    """Answer all QA once the conv's ingest is fully terminal
    (every session in done/partial/failed). The snapshot file alone is
    not enough — it is rewritten after each session."""
    cache = os.path.join(out_dir, f"ingest_final_c{ci}.json")
    prog_path = os.path.join(out_dir, f"ingest_final_c{ci}_progress.json")
    n_sessions = len(A.sessions(conv["conversation"]))
    deadline = asyncio.get_running_loop().time() + wait
    while True:
        prog = (json.load(open(prog_path))
                if os.path.exists(prog_path) else {})
        # partial dates are also appended to done — dedupe via set
        terminal = len(set(prog.get("done", []))
                       | set(prog.get("failed", [])))
        if os.path.exists(cache) and terminal >= n_sessions:
            break
        if asyncio.get_running_loop().time() > deadline:
            print(f"conv{ci}: ingest not done within wait; skip",
                  flush=True)
            return
        print(f"conv{ci}: waiting on ingest "
              f"({terminal}/{n_sessions} sessions)", flush=True)
        await asyncio.sleep(60)
    m = LifeModel()
    m.import_state(json.load(open(cache)))
    out_path = os.path.join(out_dir, f"locomo_final_c{ci}.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["qid"] for l in open(out_path)}
    rows = [{"qid": f"c{ci}_q{qi}", "conv": ci,
             "category": q.get("category"),
             "question": q["question"], "gold": q.get("answer")}
            for qi, q in enumerate(conv["qa"])]
    todo = [r for r in rows if r["qid"] not in done]
    print(f"conv{ci}: {len(todo)} to answer ({len(done)} done)",
          flush=True)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(ANS_SEM)
    fout = open(out_path, "a")

    async def one(row):
        async with sem:
            try:
                r = await asyncio.wait_for(
                    R.aanswer(m, llm, row["question"], QD,
                              premise_check="relaxed", assist=True),
                    ANS_TIMEOUT)
                rec = {**row, "response": r["response"],
                       "verdict": (r.get("verify") or {}).get("verdict")}
            except Exception as e:
                rec = {**row, "response": f"(error: {e})",
                       "verdict": "ERROR"}
            async with lock:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fout.flush()
            print(f"{row['qid']} cat{row['category']} "
                  f"[{rec['verdict']}] {rec['response'][:90]!r}",
                  flush=True)
    await asyncio.gather(*[one(r) for r in todo])
    fout.close()


# ---------- phase: judge --------------------------------------------------

async def judge_conv(ci, out_dir, jllm):
    out_path = os.path.join(out_dir, f"locomo_final_c{ci}.jsonl")
    rows = [json.loads(l) for l in open(out_path)]
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(JDG_SEM)

    async def one(h):
        note = "" if h.get("gold") else A.ABS_NOTE
        p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                           r=h["response"], abs_note=note)
        v = "err"
        for _ in range(4):
            try:
                async with sem:
                    v = (await jllm.complete(
                        "You are a strict grader.", p)).strip().lower()
                break
            except Exception:
                continue
        async with lock:
            h["correct"] = (None if v == "err"
                            else v.startswith("yes"))
    await asyncio.gather(*[one(h) for h in rows
                         if "correct" not in h])
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    for r in rows:
        c = r["category"]
        n, d = by.get(c, (0, 0))
        by[c] = (n + (1 if r.get("correct") else 0), d + 1)
    met = {"n": len(rows),
           "strict": sum(1 for r in rows if r.get("correct")),
           "unjudged": sum(1 for r in rows if r.get("correct") is None),
           "by_cat": {str(k): f"{v[0]}/{v[1]}"
                      for k, v in sorted(by.items())}}
    met["acc"] = round(met["strict"] / met["n"], 4)
    json.dump(met, open(os.path.join(
        out_dir, f"locomo_final_c{ci}_metrics_atria.json"), "w"),
        indent=2)
    print(f"conv{ci}: {met['strict']}/{met['n']} "
          f"({met['acc']}) {met['by_cat']}", flush=True)
    return met


# ---------- main ----------------------------------------------------------

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out-dir", default=os.path.dirname(__file__))
    ap.add_argument("--phase", required=True,
                    choices=["ingest", "run", "judge"])
    ap.add_argument("--convs", default="0-9")
    args = ap.parse_args()
    convs = json.load(open(args.data))
    cis = _conv_range(args.convs)

    if args.phase == "ingest":
        llm = atria_llm()
        for ci in cis:
            await ingest_conv(convs[ci], ci, llm, args.out_dir)
    elif args.phase == "run":
        llm = atria_llm(thinking=True)
        for ci in cis:
            await run_conv(convs[ci], ci, llm, args.out_dir)
    else:
        jllm = atria_llm()
        mets = []
        for ci in cis:
            p = os.path.join(args.out_dir, f"locomo_final_c{ci}.jsonl")
            if os.path.exists(p):
                mets.append(await judge_conv(ci, args.out_dir, jllm))
        if mets:
            tot_n = sum(m["n"] for m in mets)
            tot_s = sum(m["strict"] for m in mets)
            agg = {"convs": [m["n"] for m in mets],
                   "n": tot_n, "strict": tot_s,
                   "acc": round(tot_s / tot_n, 4) if tot_n else 0,
                   "by_cat": {}}
            # re-aggregate categories across convs
            rows_all = []
            for ci in cis:
                p = os.path.join(args.out_dir,
                                 f"locomo_final_c{ci}.jsonl")
                if os.path.exists(p):
                    rows_all += [json.loads(l) for l in open(p)]
            by = {}
            for r in rows_all:
                c = r["category"]
                n, d = by.get(c, (0, 0))
                by[c] = (n + (1 if r.get("correct") else 0), d + 1)
            agg["by_cat"] = {str(k): f"{v[0]}/{v[1]} "
                             f"({v[0]/v[1] * 100:.1f}%)"
                             for k, v in sorted(by.items())}
            json.dump(agg, open(os.path.join(
                args.out_dir, "locomo_final_metrics_atria.json"), "w"),
                indent=2)
            print(json.dumps({k: v for k, v in agg.items()
                              if k != "convs"}, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
