#!/usr/bin/env python3
"""Deterministic self-sufficiency post-check for extracted records.

selfcheck(records, named_conv=True) -> per-record flags + summary.

Flags:
- no_subject: value carries neither a capitalized person-name nor a
  self marker (I/my/me/we/our/user/speaker name) — referent
  unresolvable. `bare_fragment` subtype when it also has no verb-ish
  token ("5 days", "peace lily", "last month").
- temporal_unanchored: value contains a temporal word
  (ago/last/next/yesterday/NN (days|weeks|months)|month names)
  without an inline " (on ...)" anchor.
- about_nonperson: `about` is set but is not a person name — names
  are built dynamically from capitalized tokens across the record
  set's values+sources (plus a small pronoun-free lexicon).
- generic_source: `source` is self/user/assistant while the record
  set contains named sources (named-conversation ingest).

Run on: LoCoMo Arm C records (selfcontained_ab.json) and a fresh
self-contained-bullet re-extract of lab#1's 3 LME autopsy sessions
(b5ef892d camping, e831120c movie, 3a704032 plant) whose raw turns
live in results/lme_completeness/data_ms25.json on
origin/results/m4-decomp-ms.
"""
import json
import re
import sys

SELF_MARKERS = re.compile(r"\b(i|me|my|mine|we|our|us|user|you|your)\b",
                          re.I)
VERBISH = re.compile(
    r"\b\w+(?:ed|ing)\b|\b(?:got|went|had|has|was|were|is|are|did|do|"
    r"made|took|gave|bought|met|saw|felt|became|started|finished|"
    r"moved|visited|attended|joined|left|came|loves?|likes?|wants?|"
    r"needs?|plans?|uses?|hopes?|wishes?|owns?|keeps?|enjoys?)\b", re.I)
TEMPORAL = re.compile(
    r"\bago\b|\blast\s+(?:week|month|year|night|weekend|time|summer|"
    r"winter|spring|fall|autumn|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)\b|\bnext\s+(?:week|month|year|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
    r"\byesterday\b|\btomorrow\b|\b\d+\s*(?:days?|weeks?|months?|"
    r"years?|hours?)\b|\b(?:january|february|march|april|may|june|"
    r"july|august|september|october|november|december)\b", re.I)
ANCHOR = re.compile(r"\(on\s", re.I)
GENERIC_SRC = {"self", "user", "assistant", "system", ""}
CAP_TOKEN = re.compile(r"\b([A-Z][a-z]{2,})\b")
STOP_CAP = {"The", "This", "That", "It", "She", "He", "Her", "His",
            "Their", "They", "We", "Our", "But", "And", "When", "What",
            "How", "Why", "Yes", "No", "After", "Before", "During",
            "While", "Big", "New", "San", "Los", "Las"}


def build_names(records):
    names = set()
    for r in records:
        for field in (r.get("value"), r.get("source"), r.get("about")):
            for t in CAP_TOKEN.findall(str(field or "")):
                if t not in STOP_CAP:
                    names.add(t.lower())
    return names


def selfcheck(records):
    """records: list of {source, about, slot, value} dicts."""
    names = build_names(records)
    named_srcs = {str(r.get("source") or "").lower() for r in records}
    has_named = bool(named_srcs - GENERIC_SRC)
    out = []
    for r in records:
        v = str(r.get("value") or "")
        src = str(r.get("source") or "").lower()
        about = r.get("about")
        flags = []
        toks = set(t.lower() for t in CAP_TOKEN.findall(v))
        has_name = bool(toks & names) or bool(toks - STOP_CAP)
        has_self = bool(SELF_MARKERS.search(v))
        if not has_name and not has_self:
            flags.append("no_subject")
            if not VERBISH.search(v):
                flags.append("bare_fragment")
        if TEMPORAL.search(v) and not ANCHOR.search(v):
            flags.append("temporal_unanchored")
        if about and str(about).lower() not in names \
                and str(about).lower() not in ("none", "null"):
            flags.append("about_nonperson")
        if has_named and src in GENERIC_SRC:
            flags.append("generic_source")
        out.append({"record": r, "flags": flags,
                    "value": v})
    return out


def summarize(rows):
    n = len(rows)
    counts = {}
    for r in rows:
        for f in r["flags"]:
            counts[f] = counts.get(f, 0) + 1
    clean = sum(1 for r in rows if not r["flags"])
    return {"records": n, "clean": clean,
            "clean_rate": round(clean / n, 3) if n else 0,
            "flag_counts": counts}


def _report(title, rows):
    s = summarize(rows)
    print(f"== {title}: {s['records']} recs, clean {s['clean']} "
          f"({s['clean_rate']}), flags {s['flag_counts']}")
    for r in rows:
        if r["flags"]:
            rec = r["record"]
            print(f"   {rec.get('source')}|{rec.get('about')}|"
                  f"{rec.get('slot')}: {r['value'][:95]}  "
                  f"{r['flags']}")


async def _lme_side(llm):
    sys.path.insert(0, "/home/ubuntu/mha-ced/tasks/life_model/external")
    from lifemodel.ingest_llm import LLMIngestor
    data = json.load(open("/tmp/data_ms25.json"))
    targets = {"b5ef892d", "e831120c", "3a704032"}
    ing = LLMIngestor(llm, day_of=lambda x, d=None: x)
    for q in data:
        if q["question_id"] not in targets:
            continue
        print(f"### {q['question_id']} {q['question'][:70]}")
        all_rows = []
        for sid, sess in zip(q["haystack_session_ids"],
                             q["haystack_sessions"]):
            date = sess[0].get("said_date") or ""
            recs = await ing.aextract(date, sess, twostage=False)
            for r in recs:
                r["_q"] = q["question_id"]
            all_rows += recs
            print(f"  {sid}: {len(recs)} recs", flush=True)
        _report(f"{q['question_id']} selfcontained-extract", 
                selfcheck(all_rows))
        json.dump(all_rows, open(
            f"lme_autopsy_reextract_{q['question_id']}.json", "w"),
            ensure_ascii=False, indent=2)


def _locomo_side():
    d = json.load(open("/home/ubuntu/mha-ced/results/lme_external/"
                       "selfcontained_ab.json"))
    for sess, recs in d["C_selfcontained"].items():
        _report(f"locomo {sess} armC", selfcheck(recs))


async def main():
    _locomo_side()
    import os
    sys.path.insert(0, "/home/ubuntu/mha-ced/tasks/life_model/external")
    from lme import _make_llm
    import argparse
    llm = _make_llm(argparse.Namespace(
        api_key=os.environ.get("ATRIA_API_KEY"),
        base_url="https://api.atria-asi.ai/v1",
        model="Atria-Dawn-Preview"), thinking=True)
    await _lme_side(llm)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
