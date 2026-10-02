"""Yield-guarded re-ingest of the ss-assist A-lesion questions.

arm_zero (always on): after each session's extract, if the session had
substantive assistant turns (>300 chars) but zero assistant-source
records -> one targeted top-up extraction ("list every suggestion /
artifact item the assistant produced"), merged into the session's
records. Zero-cost when the guard doesn't fire.

arm_parity (PARITY=1): on top of arm_zero — sibling-record coverage
check: records grouped by slot stem (slot minus trailing _token);
families with >=3 members where the sparsest record's text is < half
the longest -> targeted top-up for that member's topic.

Writes models to <out>/models/<qid>.json and a guard log jsonl with
per-session trigger evidence.
"""
import asyncio, json, os, re, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")

import lifemodel.ingest_llm as ingest_llm
from lifemodel.ingest_llm import LLMIngestor, _canon, _json_list
from lifemodel.model import LifeModel
from hyra.llm import OpenAICompatLLM

sys.path.insert(0, "tasks/life_model/external")
from lme import _ordinal

# ride on the selfc extraction stack (bullet merged upstream in #65;
# the mainstack shadow predates it so we re-apply here)
_BULLET = (
    "\n- SELF-CONTAINED RECORDS: every record must stand alone — named "
    "subject + complete fact + temporal anchor inline. Never emit bare "
    "values (\"5 days\", \"peace lily\", \"last month\") without their "
    "referent; keep dates and durations inside the fact record, never "
    "split them into a separate vertex; acquisition/state-change facts "
    "keep {item + action + source + date} in one record.")
if "SELF-CONTAINED RECORDS" not in ingest_llm.EXTRACT_SYS:
    ingest_llm.EXTRACT_SYS = ingest_llm.EXTRACT_SYS.rstrip() + _BULLET

TOPUP_SYS = """You extract ONLY the assistant's substantive output from a chat
session — every suggestion, recommendation, list/table item, name it
invented, plan or advice it produced. Record schema:
{"slot": "snake_case_topic", "value": "what was said", "about": null,
 "kind": "statement", "source": "assistant", "text": "quote <=20 words"}
One record per item/attribute — decompose artifacts row by row, keep
verbatim citable lines (exact quotes, named items, colors, numbers).
Return ONLY the JSON array."""


def _norm(ing, model, day, raw, i):
    if not isinstance(raw, dict) or not raw.get("slot"):
        return None
    cat = ing.catalog(model)
    ents = ing.entity_catalog(model)
    about = raw.get("about")
    if about:
        about = _canon(str(about), ents, thresh=0.4)
    return {
        "id": f"llm_{day}_top{i}_{ing.n_extracted}",
        "day": day,
        "source": "assistant",
        "kind": raw.get("kind", "statement"),
        "slot": _canon(str(raw["slot"]), cat),
        "value": raw.get("value"),
        "about": about,
        "text": str(raw.get("text", ""))[:200],
    }


async def topup(llm, ing, model, date_label, body, focus=None):
    prompt = f"Session date: {date_label}\n\n{body}\n\n"
    if focus:
        prompt += (f"FOCUS: re-read the assistant's content about "
                   f"{focus} — list EVERY attribute/detail it "
                   f"described, one record each.\n\n")
    prompt += "Records JSON array:"
    recs = _json_list(await llm.complete(TOPUP_SYS, prompt))
    day = ing.day_of(date_label)
    out = []
    for i, r in enumerate(recs):
        n = _norm(ing, model, day, r, i)
        if n:
            ing.n_extracted += 1
            out.append(n)
    return out


async def guarded_session(llm, ing, model, date_label, sess, log, qid,
                          parity=False):
    body = "\n".join(("USER" if t["role"] == "user" else "ASSISTANT")
                     + ": " + t["content"] for t in sess)
    recs = await ing.aextract(date_label, sess, model)
    ac = sum(len(t["content"]) for t in sess if t["role"] == "assistant")
    arecs = [r for r in recs if r.get("source") == "assistant"]
    ev = {"qid": qid, "date": date_label, "assistant_chars": ac,
          "n_recs": len(recs), "n_assistant": len(arecs)}
    if ac > 300 and not arecs:
        added = await topup(llm, ing, model, date_label, body)
        recs.extend(added)
        ev["zero_trigger"] = True
        ev["topup_added"] = len(added)
    if parity:
        fam = {}
        for r in recs:
            stem = r["slot"].rsplit("_", 1)[0] if "_" in r["slot"] \
                else r["slot"]
            fam.setdefault(stem, []).append(r)
        for stem, mem in fam.items():
            if len(mem) < 3:
                continue
            lens = [(len(str(r.get("text", "") or r.get("value", ""))), r)
                    for r in mem]
            lens.sort()
            if lens[0][0] * 2 < lens[-1][0]:
                sparse = lens[0][1]
                focus = sparse["slot"].replace("_", " ")
                added = await topup(llm, ing, model, date_label, body,
                                    focus=focus)
                recs.extend(added)
                ev.setdefault("parity_triggers", []).append(
                    {"stem": stem, "sparse": sparse["slot"],
                     "added": len(added)})
    for r in recs:
        model.ingest(r)
    log.write(json.dumps(ev) + "\n")
    log.flush()
    return len(recs)


async def run_one(llm, q, mdir, log, parity):
    model = LifeModel()
    ing = LLMIngestor(llm, day_of=_ordinal)
    n = 0
    for date, sess in zip(q["haystack_dates"], q["haystack_sessions"]):
        for _try in range(5):
            try:
                n += await guarded_session(llm, ing, model, date, sess,
                                           log, q["question_id"], parity)
                break
            except Exception as e:
                if "429" in str(e) and _try < 4:
                    await asyncio.sleep(30 * (_try + 1))
                    continue
                raise
    packed = {"n_records": n, "export": model.export()}
    json.dump(packed, open(os.path.join(mdir, q["question_id"] + ".json"),
                         "w"))
    return n


async def main():
    qs_file, out_dir = sys.argv[1], sys.argv[2]
    parity = os.environ.get("PARITY") == "1"
    mdir = os.path.join(out_dir, "models")
    os.makedirs(mdir, exist_ok=True)
    log = open(os.path.join(out_dir, "guard_log.jsonl"), "a")
    llm = OpenAICompatLLM()
    for q in json.load(open(qs_file)):
        mp = os.path.join(mdir, q["question_id"] + ".json")
        if os.path.exists(mp):
            continue
        n = await run_one(llm, q, mdir, log, parity)
        print(q["question_id"], "records", n, flush=True)


asyncio.run(main())
