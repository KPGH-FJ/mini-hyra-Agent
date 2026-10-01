#!/usr/bin/env python3
"""Ingest-recall + subject-binding autopsy — ordered arm.

The pv112 who-swap misses (q189/192/194/195) traced to records whose
grammatical subject was a possessive pronoun: "Her son got into an
accident" — value keeps the pronoun, vertex key takes the OBJECT noun
(`son|son_accident`, `kids|...`, `friend|...`, `accident_fear`,
`pottery_injury_break`), so the reader-side verifier binds the
question's subject freely and the cross-owner gate sees topic owners,
not persons. Coverage is NOT the lesion (38/40 named items already
captured); subject binding is.

Arm A: package EXTRACT_SYS (SPEAKER BINDING already inside).
Arm B: EXTRACT_SYS + SUBJECT bullet — possessive-pronoun subjects
belong to the speaker; resolve the pronoun in the value.

Sessions: conv-0 s13 (Oscar/adoption), s17 (pottery break/painting),
s18 (roadtrip accident). Prints per-session record diffs.
"""
import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A  # noqa: E402

from lme import _make_llm                        # noqa: E402
from locomo import _day_of, normalize_turns, sessions  # noqa: E402
from lifemodel.ingest_llm import LLMIngestor      # noqa: E402
import lifemodel.ingest_llm as IL                # noqa: E402

TARGETS = {"session_13", "session_17", "session_18"}

SUBJECT_BULLET = (
    "\n- SUBJECT BINDING: a fact whose grammatical subject is a "
    "possessive pronoun (\"her son\", \"my kids\", \"his dog\") "
    "belongs to the SPEAKER — about=null, never about=\"son\"/"
    "\"kids\"/an object noun. Resolve the pronoun inside the value "
    "so it names the speaker: \"Melanie's son got into an accident\" "
    "not \"Her son got into an accident\".")

TOPIC_ABOUTS = {"son", "kids", "children", "child", "friend", "buddy",
                "dog", "cat", "pet", "pets", "husband", "wife", "mom",
                "dad", "sister", "brother", "family", "pottery",
                "accident", "painting", "bowl", "house"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    convs = json.load(open(args.data))

    aargs = argparse.Namespace(
        api_key=os.environ.get("ATRIA_API_KEY"),
        base_url="https://api.atria-asi.ai/v1",
        model="Atria-Dawn-Preview")
    llm = _make_llm(aargs, thinking=True)

    stock_sys = IL.EXTRACT_SYS
    results = {}
    for arm, extra in (("A_stock", ""), ("B_subject", SUBJECT_BULLET)):
        IL.EXTRACT_SYS = stock_sys + extra
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
                    if re.search(r"\b(her|his|their)\s+\w+",
                                 str(r.get("value") or "").lower())
                    and not re.search(
                        r"\b(melanie|caroline|john|maria|gina)\b",
                        str(r.get("value") or "").lower())]
            print(f"== {arm} {k}: {len(recs)} recs, "
                  f"{len(topic)} topic-about, {len(pron)} pronoun-values")
            for r in recs:
                tag = (" [TOPIC-ABOUT]" if r in topic else
                       " [PRONOUN]" if r in pron else "")
                print(f"   {r.get('source')}|{r.get('about')}|"
                      f"{r.get('slot')}: {str(r.get('value'))[:95]}{tag}")
        IL.EXTRACT_SYS = stock_sys
        results[arm] = arm_rows

    out = "recall_ab.json"
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
