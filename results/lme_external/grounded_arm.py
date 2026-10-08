#!/usr/bin/env python3
"""Grounded-inference + temporal-anchor arms on the LoCoMo-10 snapshots.

Scopes (resumable, per-question flush):
  cat3    : all convs, cat=3, premise_check="grounded", assist=True,
            ORIGINAL snapshots  -> grnd_cat3_c{i}.jsonl
  cat5    : convs 0-2, cat=5, grounded, original snapshots
            -> grnd_cat5_c{i}.jsonl   (defense sentinel)
  cat2fix : all convs, cat=2, relaxed (baseline gate), RESOLVED
            snapshots            -> anch_cat2_c{i}.jsonl
  judge   : Atria judge on all three files

The temporal fix is applied to the exported asset in-place (hist edge
values) — identical strings to what ingest_llm._resolve_rel_anchors
now produces at extraction time, without re-ingesting.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A                              # noqa: E402

from lifemodel.model import LifeModel            # noqa: E402
from lifemodel.ingest_llm import _resolve_rel_anchors  # noqa: E402
import lifemodel.reader as R                     # noqa: E402
from locomo_final import atria_llm, _conv_range, QD, ANS_SEM, JDG_SEM, \
    ANS_TIMEOUT                                   # noqa: E402


def load_model(out_dir, ci, resolve=False):
    asset = json.load(open(os.path.join(out_dir,
                                        f"ingest_final_c{ci}.json")))
    if resolve:
        n = 0
        for edges in asset.get("hist", {}).values():
            for e in edges:
                v = _resolve_rel_anchors(str(e[0]), e[1])
                if v != e[0]:
                    e[0], n = v, n + 1
        print(f"conv{ci}: resolved {n} relative anchors", flush=True)
    m = LifeModel()
    m.import_state(asset)
    return m


async def run_scope(convs, ci, scope, llm, out_dir):
    resolve = scope == "cat2fix"
    gate = os.environ.get(
        "GATE", "grounded" if scope in ("cat3", "cat5") else "relaxed")
    cat = {"cat3": 3, "cat5": 5, "cat2fix": 2}[scope]
    m = load_model(out_dir, ci, resolve)
    tag = os.environ.get("ARM_TAG", "")
    out_path = os.path.join(
        out_dir,
        f"{scope == 'cat2fix' and 'anch' or 'grnd'}{tag}_"
        f"{scope.rstrip('fix')}_c{ci}.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["qid"] for l in open(out_path)}
    rows = [{"qid": f"c{ci}_q{qi}", "conv": ci, "category": cat,
             "question": q["question"], "gold": q.get("answer")}
            for qi, q in enumerate(convs[ci]["qa"])
            if q.get("category") == cat]
    todo = [r for r in rows if r["qid"] not in done]
    print(f"{scope} conv{ci}: {len(todo)} to answer "
          f"({len(done)} done)", flush=True)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(ANS_SEM)
    fout = open(out_path, "a")

    async def one(row):
        async with sem:
            try:
                r = await asyncio.wait_for(
                    R.aanswer(m, llm, row["question"], QD,
                              premise_check=gate, assist=True),
                    ANS_TIMEOUT)
                rec = {**row, "response": r["response"],
                       "verdict": (r.get("verify") or {}).get("verdict")}
            except Exception as e:
                rec = {**row, "response": f"(error: {e})",
                       "verdict": "ERROR"}
            async with lock:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fout.flush()
            print(f"{scope} {row['qid']} [{rec['verdict']}] "
                  f"{rec['response'][:90]!r}", flush=True)
    await asyncio.gather(*[one(r) for r in todo])
    fout.close()


async def judge_file(path, jllm):
    rows = [json.loads(l) for l in open(path)]
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
            h["correct"] = (None if v == "err" else v.startswith("yes"))
    await asyncio.gather(*[one(h) for h in rows
                         if "correct" not in h])
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(rows)
    s = sum(1 for r in rows if r.get("correct"))
    print(f"{os.path.basename(path)}: {s}/{n} "
          f"({s / n * 100:.1f}%)", flush=True)
    return s, n


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out-dir", default=os.path.dirname(__file__))
    ap.add_argument("--scope", required=True,
                    choices=["cat3", "cat5", "cat2fix", "judge"])
    ap.add_argument("--convs", default="0-9")
    args = ap.parse_args()
    convs = json.load(open(args.data))
    cis = _conv_range(args.convs)

    if args.scope == "judge":
        jllm = atria_llm()
        for pat in ("grnd_cat3", "grnd_cat5", "anch_cat2"):
            for ci in cis:
                p = os.path.join(args.out_dir, f"{pat}_c{ci}.jsonl")
                if os.path.exists(p):
                    await judge_file(p, jllm)
        return

    llm = atria_llm(thinking=True)
    for ci in cis:
        if args.scope == "cat5" and ci > 2:
            continue
        await run_scope(convs, ci, args.scope, llm, args.out_dir)


if __name__ == "__main__":
    asyncio.run(main())
