"""150q full re-ingest: verify=True + yield_guard=True per session.

Per session: aextract (selfc stack) -> verify completeness audit
(always, +1 call) -> yield_guard topup (only if assistant turns
>300 chars but zero assistant records, +1 call when fired).
"""
import asyncio, json, os, re, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")

import lifemodel.ingest_llm as ingest_llm
from lifemodel.ingest_llm import LLMIngestor, _json_list, _canon
from lifemodel.model import LifeModel
from hyra.llm import OpenAICompatLLM
sys.path.insert(0, "tasks/life_model/external")
from lme import _ordinal

_BULLET = (
    "\n- SELF-CONTAINED RECORDS: every record must stand alone — named "
    "subject + complete fact + temporal anchor inline. Never emit bare "
    "values (\"5 days\", \"peace lily\", \"last month\") without their "
    "referent; keep dates and durations inside the fact record, never "
    "split them into a separate vertex; acquisition/state-change facts "
    "keep {item + action + source + date} in one record.")
if "SELF-CONTAINED RECORDS" not in ingest_llm.EXTRACT_SYS:
    ingest_llm.EXTRACT_SYS = ingest_llm.EXTRACT_SYS.rstrip() + _BULLET

VERIFY_SYS = """You are the completeness-audit stage of a memory ingestor.
You get a chat session AND the records already extracted from it.
Re-read the session line by line and list ONLY the records that were
MISSED: any attribute, entity, name, number, date, quote, or
assistant-produced item not covered by an existing record.
Same JSON schema:
{"slot": "snake_case_topic", "value": "what was said", "about": null,
 "kind": "statement", "source": "self|assistant", "text": "quote <=20 words"}
Return ONLY the JSON array — empty if nothing was missed."""

TOPUP_SYS = """You extract ONLY the assistant's substantive output from a chat
session — every suggestion, recommendation, list/table item, name it
invented, plan or advice it produced. Record schema:
{"slot": "snake_case_topic", "value": "what was said", "about": null,
 "kind": "statement", "source": "assistant", "text": "quote <=20 words"}
One record per item/attribute — decompose artifacts row by row, keep
verbatim citable lines (exact quotes, named items, colors, numbers).
Return ONLY the JSON array."""


def _overlap(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-z0-9]+", a.lower()))
    tb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _mkrec(ing, model, day, raw, i, prefix):
    if not isinstance(raw, dict) or not raw.get("slot"):
        return None
    cat = ing.catalog(model)
    ents = ing.entity_catalog(model)
    about = raw.get("about")
    if about:
        about = _canon(str(about), ents, thresh=0.4)
    r = {
        "id": f"llm_{day}_{prefix}{i}_{ing.n_extracted}",
        "day": day,
        "source": raw.get("source", "self"),
        "kind": raw.get("kind", "statement"),
        "slot": _canon(str(raw["slot"]), cat),
        "value": raw.get("value"),
        "about": about,
        "text": str(raw.get("text", ""))[:200],
    }
    ing.n_extracted += 1
    return r


async def verify_add(llm, ing, model, date_label, body, recs):
    slim = [{"slot": r["slot"], "value": r.get("value")}
            for r in recs]
    prompt = (f"Session date: {date_label}\n\n{body}\n\n"
              f"ALREADY EXTRACTED ({len(recs)}):\n"
              + json.dumps(slim, ensure_ascii=False)
              + "\n\nMISSING records JSON array:")
    found = _json_list(await llm.complete(VERIFY_SYS, prompt))
    day = ing.day_of(date_label)
    existing = [(r["slot"], str(r.get("value") or "")) for r in recs]
    out = []
    for i, raw in enumerate(found):
        val = str(raw.get("value") or "")
        if any(s == raw.get("slot") and _overlap(v, val) >= 0.5
               for s, v in existing):
            continue
        r = _mkrec(ing, model, day, raw, i, "v")
        if r:
            out.append(r)
    return out


async def topup(llm, ing, model, date_label, body):
    prompt = f"Session date: {date_label}\n\n{body}\n\nRecords JSON array:"
    found = _json_list(await llm.complete(TOPUP_SYS, prompt))
    day = ing.day_of(date_label)
    out = []
    for i, raw in enumerate(found):
        raw = dict(raw, source="assistant")
        r = _mkrec(ing, model, day, raw, i, "top")
        if r:
            out.append(r)
    return out


async def session_ingest(llm, ing, model, date_label, sess, log, qid):
    body = "\n".join(("USER" if t["role"] == "user" else "ASSISTANT")
                     + ": " + t["content"] for t in sess)
    recs = await ing.aextract(date_label, sess, model)
    ev = {"qid": qid, "date": date_label, "n1": len(recs)}
    found = await verify_add(llm, ing, model, date_label, body, recs)
    recs.extend(found)
    ev["verify_found"] = len(found)
    ac = sum(len(t["content"]) for t in sess
             if t["role"] == "assistant")
    arecs = [r for r in recs if r.get("source") == "assistant"]
    if ac > 300 and not arecs:
        added = await topup(llm, ing, model, date_label, body)
        recs.extend(added)
        ev["guard_topup"] = len(added)
    for r in recs:
        model.ingest(r)
    ev["n_final"] = len(recs)
    log.write(json.dumps(ev, ensure_ascii=False) + "\n")
    log.flush()


async def main():
    qs_file, out_dir = sys.argv[1], sys.argv[2]
    shard_i, shard_n = int(sys.argv[3]), int(sys.argv[4])
    mdir = os.path.join(out_dir, "models")
    os.makedirs(mdir, exist_ok=True)
    log = open(os.path.join(out_dir, f"arm_log_{shard_i}.jsonl"), "a")
    llm = OpenAICompatLLM()
    sem = asyncio.Semaphore(6)
    qs = [q for i, q in enumerate(json.load(open(qs_file)))
          if i % shard_n == shard_i]

    async def run_one(q):
        mp = os.path.join(mdir, q["question_id"] + ".json")
        if os.path.exists(mp):
            return
        async with sem:
            model = LifeModel()
            ing = LLMIngestor(llm, day_of=_ordinal)
            for date, sess in zip(q["haystack_dates"],
                                  q["haystack_sessions"]):
                for _try in range(5):
                    try:
                        await session_ingest(llm, ing, model, date,
                                             sess, log,
                                             q["question_id"])
                        break
                    except Exception as e:
                        if "429" in str(e) and _try < 4:
                            await asyncio.sleep(30 * (_try + 1))
                            continue
                        raise
            n = sum(len(v) for v in
                    model.export()["asset"]["hist"].values())
            json.dump({"n_records": n, "export": model.export()},
                      open(mp, "w"))
            print(shard_i, q["question_id"], "records", n, flush=True)

    await asyncio.gather(*(run_one(q) for q in qs))

asyncio.run(main())
