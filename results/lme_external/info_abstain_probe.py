#!/usr/bin/env python3
"""Informative-abstention micro-arm.

_pv_abstain now names true attribution when a bound atom's entity is
recorded under another owner ("Oscar is recorded under caroline:
'Has a guinea pig named Oscar'"). Re-probe the pv112 miss set on the
same stock snapshots; target = still semantically refuses but the OR
judge now accepts the abstention (q178 was judged False on the bare
phrasing while merged's owner-naming reply was True).

Set: q178 (ABSENT w/ Oscar bound), q167 (SPLICED), c2_q186 (SUPPORTED
control — verdict should not change), q152/c2_q152 (clean abstains —
note must not corrupt), c1_q95 (SUPPORTED control).
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A  # noqa: E402

from lme import _make_llm                        # noqa: E402
from lifemodel.model import LifeModel            # noqa: E402
import lifemodel.reader as R                    # noqa: E402

SNAPS = {0: "ingest_c0_atria.json", 1: "ingest_c1_atria.json",
         2: "ingest_c2_atria.json"}
QIDS = {"c0_q178", "c0_q167", "c0_q152", "c1_q95", "c2_q186",
        "c2_q152"}
OUT = "info_abstain.jsonl"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    convs = json.load(open(args.data))
    od = os.path.dirname(os.path.abspath(__file__))

    if args.judge:
        jargs = argparse.Namespace(api_key=os.environ.get("OR_API_KEY"),
                                   base_url="https://openrouter.ai/api/v1",
                                   model="stealth/space-bunny-alpha")
        jllm = _make_llm(jargs)
        for line in open(os.path.join(od, OUT)):
            h = json.loads(line)
            note = "" if h.get("gold") else A.ABS_NOTE
            p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                               r=h["response"], abs_note=note)
            try:
                v = (await jllm.complete(
                    "You are a strict grader.", p)).strip().lower()
            except Exception as e:
                v = f"err {e}"
            print(f"  {h['qid']} -> {v!r}   {h['response'][:90]!r}",
                  flush=True)
        return

    aargs = argparse.Namespace(api_key=os.environ.get("ATRIA_API_KEY"),
                               base_url="https://api.atria-asi.ai/v1",
                               model="Atria-Dawn-Preview")
    llm = _make_llm(aargs, thinking=True)
    out = open(os.path.join(od, OUT), "w")
    for ci in range(3):
        m = LifeModel()
        m.import_state(json.load(open(os.path.join(od, SNAPS[ci]))))
        for row in A.cat5_qs(convs[ci], ci):
            if row["qid"] not in QIDS:
                continue
            r = await R.aanswer(m, llm, row["question"],
                                "2023 (post-conversation)",
                                premise_check=True)
            ver = (r.get("verify") or {}).get("verdict")
            rec = {**row, "response": r["response"], "verdict": ver}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{row['qid']} [{ver}] {r['response'][:130]!r}",
                  flush=True)
    out.close()


if __name__ == "__main__":
    asyncio.run(main())
