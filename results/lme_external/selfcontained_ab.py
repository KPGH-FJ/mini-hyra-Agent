#!/usr/bin/env python3
"""Self-sufficiency bullet verification — lab#1's finalized text on LoCoMo.

Arm C: package EXTRACT_SYS + SELF-CONTAINED RECORDS bullet (verbatim
from lab#1 phase-1, which zeroed L1-L4 on the LME side). Re-extract
conv-0 s13/s17/s18 — the sessions holding the 5 pronoun-loss lesion
records — and check RECORD FORM ONLY (no scoring): does "Her son got
into an accident" become "Melanie's son got into an accident"? Side
check: does self-sufficiency fix source/about binding without naming
the speaker?
"""
import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/ubuntu/mha-ced/tasks/life_model/external")

from lme import _make_llm                        # noqa: E402
from locomo import _day_of, normalize_turns      # noqa: E402
from lifemodel.ingest_llm import LLMIngestor      # noqa: E402
import lifemodel.ingest_llm as IL                # noqa: E402

TARGETS = {"session_13", "session_17", "session_18"}

SELFCONTAINED_BULLET = (
    "\n- SELF-CONTAINED RECORDS: every record must stand alone — named"
    " subject + complete fact + temporal anchor inline. Never emit"
    " bare values (\"5 days\", \"peace lily\", \"last month\") without"
    " their referent; keep dates and durations inside the fact"
    " record, never split them into a separate vertex;"
    " acquisition/state-change facts keep {item + action + source +"
    " date} in one record.")

TOPIC_ABOUTS = {"son", "kids", "children", "child", "friend", "buddy",
                "dog", "cat", "pet", "pets", "husband", "wife", "mom",
                "dad", "sister", "brother", "family", "pottery",
                "accident", "painting", "bowl", "house"}

NAMES = re.compile(r"\b(melanie|caroline|john|maria|gina|oscar|bailey|"
                   r"oliver)\b", re.I)
PRON = re.compile(r"\b(her|his|their)\s+\w+", re.I)
LESION = re.compile(r"accident|adopt|buddy|friend|injur|pottery|fear|"
                    r"scared|kid|son", re.I)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    convs = json.load(open(args.data))

    llm = _make_llm(argparse.Namespace(
        api_key=os.environ.get("ATRIA_API_KEY"),
        base_url="https://api.atria-asi.ai/v1",
        model="Atria-Dawn-Preview"), thinking=True)

    results = {}
    for arm, extra in (("A_stock", ""),
                       ("C_selfcontained", SELFCONTAINED_BULLET)):
        IL.EXTRACT_SYS = IL.EXTRACT_SYS + extra if extra else \
            IL.EXTRACT_SYS
        stock = IL.EXTRACT_SYS
        ing = LLMIngestor(llm, day_of=_day_of)
        arm_rows = {}
        conv = convs[0]["conversation"]
        for k in conv:
            if k not in TARGETS:
                continue
            turns = normalize_turns(conv[k])
            date = conv.get(k + "_date_time", k)
            recs = await ing.aextract(date, turns, twostage=False)
            arm_rows[k] = recs
            topic = [r for r in recs
                     if str(r.get("about") or "").lower()
                     in TOPIC_ABOUTS]
            pron = [r for r in recs
                    if PRON.search(str(r.get("value") or ""))
                    and not NAMES.search(str(r.get("value") or ""))]
            print(f"== {arm} {k}: {len(recs)} recs, "
                  f"{len(topic)} topic-about, {len(pron)} pronoun-only",
                  flush=True)
            for r in recs:
                v = str(r.get("value") or "")
                if not LESION.search(v) and r not in topic \
                        and r not in pron:
                    continue
                tag = (" [TOPIC-ABOUT]" if r in topic else
                       " [PRONOUN]" if r in pron else " [lesion-class]")
                print(f"   {r.get('source')}|{r.get('about')}|"
                      f"{r.get('slot')}: {v[:100]}{tag}")
        IL.EXTRACT_SYS = stock
        results[arm] = arm_rows

    json.dump(results, open("selfcontained_ab.json", "w"),
              ensure_ascii=False, indent=2)
    print("wrote selfcontained_ab.json")


if __name__ == "__main__":
    asyncio.run(main())
