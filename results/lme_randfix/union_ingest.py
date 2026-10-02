"""Randomness-lesion ingest arms: union2 and verify_pass.

union2: run aextract twice per session (independent samples — Atria has
no seed; temperature 0.7 sampling makes the passes independent), then
union-merge per session BEFORE ingest: same slot → keep the richer
record (longer value+text); divergent values (<0.5 token overlap) keep
both as slot / slot__b. Logs union_added per session = records kept
only because of the second pass (quantifies random attrition).

verify_pass: one aextract, then a completeness second pass ("re-read
the session line by line — which attributes/entities/numbers/quotes
were missed? list ONLY missing records"), deduped vs pass-1 by
slot+value overlap. Logs verify_found item types.

ARM=union2|verify env selects. Same selfc stack; writes models +
arm_log.jsonl per out_dir.
"""
import asyncio, json, os, re, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")

import lifemodel.ingest_llm as ingest_llm
from lifemodel.ingest_llm import LLMIngestor, _json_list
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


def _overlap(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-z0-9]+", a.lower()))
    tb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _rlen(r) -> int:
    return len(str(r.get("value") or "")) + len(str(r.get("text") or ""))


def union_merge(r1: list, r2: list) -> tuple[list, int]:
    """Union of two extract passes. Returns (merged, added_by_pass2)."""
    by_slot = {}
    for r in r1:
        by_slot.setdefault(r["slot"], []).append(r)
    merged = [r for rs in by_slot.values() for r in rs]
    added = 0
    for r in r2:
        mem = by_slot.get(r["slot"], [])
        if not mem:
            merged.append(r)
            added += 1
            continue
        # same slot: if any member covers the same fact, keep the richer
        hit = None
        for m in mem:
            if _overlap(str(m.get("value") or ""), str(r.get("value") or "")) >= 0.5:
                hit = m
                break
        if hit is None:
            r = dict(r, slot=r["slot"] + "__b")
            merged.append(r)
            added += 1
        elif _rlen(r) > _rlen(hit):
            merged[merged.index(hit)] = r
    return merged, added


async def verify_add(llm, ing, model, date_label, body, recs):
    slim = [{"slot": r["slot"], "value": r.get("value")}
            for r in recs]
    prompt = (f"Session date: {date_label}\n\n{body}\n\n"
              f"ALREADY EXTRACTED ({len(recs)}):\n"
              + json.dumps(slim, ensure_ascii=False)
              + "\n\nMISSING records JSON array:")
    found = _json_list(await llm.complete(VERIFY_SYS, prompt))
    out = []
    day = ing.day_of(date_label)
    cat = ing.catalog(model)
    ents = ing.entity_catalog(model)
    existing = [(r["slot"], str(r.get("value") or "")) for r in recs]
    for i, raw in enumerate(found):
        if not isinstance(raw, dict) or not raw.get("slot"):
            continue
        val = str(raw.get("value") or "")
        if any(s == raw["slot"] and _overlap(v, val) >= 0.5
               for s, v in existing):
            continue
        about = raw.get("about")
        if about:
            about = ingest_llm._canon(str(about), ents, thresh=0.4)
        out.append({
            "id": f"llm_{day}_v{i}_{ing.n_extracted}",
            "day": day,
            "source": raw.get("source", "self"),
            "kind": raw.get("kind", "statement"),
            "slot": ingest_llm._canon(str(raw["slot"]), cat),
            "value": raw.get("value"),
            "about": about,
            "text": str(raw.get("text", ""))[:200],
        })
        ing.n_extracted += 1
    return out


async def session_arm(llm, ing, model, date_label, sess, log, qid, arm):
    body = "\n".join(("USER" if t["role"] == "user" else "ASSISTANT")
                     + ": " + t["content"] for t in sess)
    ev = {"qid": qid, "date": date_label}
    if arm == "union2":
        r1 = await ing.aextract(date_label, sess, model)
        r2 = await ing.aextract(date_label, sess, model)
        recs, added = union_merge(r1, r2)
        ev.update(n1=len(r1), n2=len(r2), union_added=added)
    else:
        recs = await ing.aextract(date_label, sess, model)
        found = await verify_add(llm, ing, model, date_label, body, recs)
        recs.extend(found)
        ev.update(n1=len(recs) - len(found), verify_found=len(found),
                  verify_items=[f["slot"] for f in found][:8])
    for r in recs:
        model.ingest(r)
    ev["n_final"] = len(recs)
    log.write(json.dumps(ev, ensure_ascii=False) + "\n")
    log.flush()


async def main():
    qs_file, out_dir = sys.argv[1], sys.argv[2]
    arm = os.environ.get("ARM", "union2")
    mdir = os.path.join(out_dir, "models")
    os.makedirs(mdir, exist_ok=True)
    log = open(os.path.join(out_dir, "arm_log.jsonl"), "a")
    llm = OpenAICompatLLM()
    sem = asyncio.Semaphore(4)

    async def run_one(q):
        mp = os.path.join(mdir, q["question_id"] + ".json")
        if os.path.exists(mp):
            return
        async with sem:
            model = LifeModel()
            ing = LLMIngestor(llm, day_of=_ordinal)
            n = 0
            for date, sess in zip(q["haystack_dates"],
                                  q["haystack_sessions"]):
                for _try in range(5):
                    try:
                        await session_arm(llm, ing, model, date, sess,
                                          log, q["question_id"], arm)
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
            print(q["question_id"], "records", n, flush=True)

    await asyncio.gather(*(run_one(q)
                         for q in json.load(open(qs_file))))


asyncio.run(main())
