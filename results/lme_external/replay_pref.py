"""Replay ingest for preference-type wrong questions.

For each question: run the production twostage LLMIngestor over its
haystack sessions (GLM), ingest into a fresh LifeModel, then run the
production reader (aretrieve -> aanswer). Dumps raw extracted records,
the stage-2 merge map, the vertex catalog, the vertices the retriever
SELECTED for the question, and the answer — so each failure is attributed
to extract / merge / retrieve / reader.
"""
import asyncio
import json
import os
import sys

_REPO = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tasks", "life_model", "external"))
sys.path.insert(0, _REPO)

from lme import GLMCompat, _ordinal  # noqa: E402
from lifemodel.model import LifeModel  # noqa: E402
from lifemodel.ingest_llm import (LLMIngestor, _json_list, _canon,  # noqa: E402
                                  EXTRACT_SYS)
from lifemodel.reader import (aanswer, vertex_catalog, render_vertices,  # noqa: E402
                              RETRIEVE_SYS)

DATA = "/home/ubuntu/longmemeval/data/longmemeval_oracle.json"
QIDS = sys.argv[1:] or ["8a2466db", "0edc2aef", "38146c39",
                        "d6233ab6", "09d032c9"]

PREF_TERMS = ("prefer", "like", "love", "enjoy", "want", "interest",
              "favorite", "hope", "wish", "hobby", "recommend",
              "suggest", "consider", "plan", "look")


async def replay(llm, llm_answer, q):
    model = LifeModel()
    ing = LLMIngestor(llm, day_of=_ordinal)
    allrecs, merges = [], []
    for date, sess in zip(q["haystack_dates"], q["haystack_sessions"]):
        catalog = ing.catalog(model)
        # stage-1: production prompt (twostage => no catalog block)
        body = "\n".join(("USER" if t["role"] == "user" else "ASSISTANT")
                         + ": " + t["content"] for t in sess)
        text = await llm.complete(
            EXTRACT_SYS,
            f"Session date: {date}\n\n{body}\n\nRecords JSON array:")
        raw = _json_list(text)
        names = [r["slot"] for r in raw
                 if isinstance(r, dict) and r.get("slot")]
        merge = await ing._amerge_slots(names, catalog)
        merges.append(merge)
        ents = ing.entity_catalog(model)
        for i, r in enumerate(raw):
            if not isinstance(r, dict) or not r.get("slot"):
                continue
            rawslot = str(r["slot"])
            slot = merge.get(rawslot) or _canon(rawslot, catalog)
            about = r.get("about")
            if about:
                about = _canon(str(about), ents, thresh=0.4)
            rec = {"id": f"rp_{i}", "day": _ordinal(date),
                   "source": r.get("source", "self"),
                   "kind": r.get("kind", "statement"),
                   "slot": slot, "value": r.get("value"),
                   "about": about,
                   "text": str(r.get("text", ""))[:200],
                   "_raw_slot": rawslot}
            model.ingest(rec)
            allrecs.append(rec)
    cat = vertex_catalog(model)
    ans = await aanswer(model, llm_answer, q["question"],
                        q["question_date"])
    return allrecs, merges, cat, ans


async def main():
    llm = GLMCompat(api_key=os.environ["GLM_API_KEY"],
                    extra_body={"thinking": {"type": "disabled"}})
    llm_answer = GLMCompat(api_key=os.environ["GLM_API_KEY"],
                           extra_body={"thinking": {"type": "enabled"}})
    orc = {q["question_id"]: q for q in json.load(open(DATA))}
    for qid in QIDS:
        q = orc[qid]
        print("=" * 78)
        print(qid, "Q:", q["question"])
        print("RUBRIC:", str(q["answer"])[:400])
        recs, merges, cat, ans = await replay(llm, llm_answer, q)
        print(f"--- {len(recs)} records; merge maps: {merges}")
        pref_recs = [r for r in recs if any(
            t in (str(r.get("value")) + str(r.get("slot"))
                  + str(r.get("text"))).lower() for t in PREF_TERMS)]
        print(f"--- {len(pref_recs)}/{len(recs)} recs touch pref terms:")
        for r in pref_recs:
            print("   ", json.dumps(r, ensure_ascii=False)[:220])
        print(f"--- vertex catalog ({len(cat)} vertices):")
        for k, (lab, n) in sorted(cat.items()):
            print(f"    {k}  ({n})")
        print(f"--- retriever selected {len(ans['selected'])} vertices:")
        for k in ans["selected"]:
            print("    ", k)
        print("--- digest shown to reader:")
        print(ans["digest"][:2500])
        print("--- reader answer:")
        print(ans["response"][:600])

asyncio.run(main())
