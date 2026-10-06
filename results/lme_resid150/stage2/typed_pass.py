#!/usr/bin/env python3
"""stage-2 extraction fidelity: a REAL LLM typing pass produces typed fields
over the same snapshot records that stage-1 hand-annotated.

Two passes per question model:
  A) field pass — chunks of ~45 records -> per-rid typed fields
  B) dup pass   — compact lines over ALL records -> suspected-duplicate pairs
     (dup detection needs the whole model in view; chunking would miss
      cross-session repeats)

Output: results/lme_resid150/stage2/typed_<qid>.json  {rid: typed-fields}
Run: ATRIA_API_KEY=... python3 results/lme_resid150/stage2/typed_pass.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
from hyra.llm import OpenAICompatLLM  # noqa: E402

QIDS = ["0a995998", "88432d0a", "d682f1a2", "gpt4_7fce9456",
        "7024f17c", "b5ef892d", "gpt4_f2262a51"]
# rerun subset (schema-revised pass): CLI args or QIDS env
QIDS = sys.argv[1:] or [q for q in os.environ.get("QIDS", "").split(",")
                        if q] or QIDS
OUT_SUFFIX = os.environ.get("OUT_SUFFIX", "")
MODEL_DIR = "results/lme150_rlx1/models"
OUT_DIR = "results/lme_resid150/stage2"

FIELDS_SYS = """You type memory records for a personal memory system. Each input
record is {"rid", "slot", "kind", "day", "value"} where `value` is the
natural-language fact text and `kind` is the extractor's coarse label
(statement/update/correction/retraction/suggestion/hearsay).

For EACH record emit one JSON object:
{"rid": <same rid>,
 "event_id": "e_<short slug>" — a fresh identifier per RECORD. Do NOT
   merge two records into one event_id even if they look like the same
   event; duplicates are linked separately,
 "kind": "asserted|negated|planned|cancelled" — the fact's polarity:
   asserted = it happened/is true; negated = explicitly did NOT happen
   or is no longer true; planned = intended/scheduled but not done;
   cancelled = was planned, now called off,
 "verb": "snake_case" — normalized predicate (buy, exchange, lent,
   view, visit, attend, dry_cleaning_dropoff, ...),
 "object": short noun phrase — what the verb acts on,
 "object_class": coarse category or null — e.g. clothing, property,
   event, vehicle, electronics, pet, document,
 "quantity": number or null — a COUNT/AMOUNT only when the value states
   one; null otherwise,
 "quantifier": "explicit|unspecified|null" — explicit = a number in the
   value; unspecified = plural/no number stated; null = not countable,
 "when_abs": ISO event time or null — "YYYY-MM-DD" when a day is
   stated/resolvable; PARTIAL dates keep their stated precision:
   "YYYY-MM" (e.g. June 2023), "YYYY" (a whole year). null only when
   the record states no event time at all,
 "granularity": "day|week|month|year|null" — the precision of
   when_abs (day only for exact dates; month for YYYY-MM),
 "duration_value": number or null — a DURATION amount when the value
   states one ("3-day trip" -> 3, "2h yoga" -> 2),
 "duration_unit": "minutes|hours|days|weeks|null" — unit of
   duration_value,
 "obligation_status": null|"awaiting_pickup"|"awaiting_return"|
   "fulfilled"|"none" — for items owed to/by someone,
 "counterparty": person/org name or null,
 "location": place name or null,
 "refers_to": null — reserved, always null}.

Rules:
- one output object per input record, same order; rids echoed verbatim
- unknown/unstated fields are null — never invent
- "planned" facts keep the planned date in when_abs, not the mention day
- Return ONLY the JSON array."""

DUP_SYS = """You get ALL records of one user's memory as compact lines:
`rid | kind | verb | object | when_abs | value-prefix`.
Two records are a SUSPECTED DUPLICATE when they describe the same real
event/fact — same verb+object and same or overlapping time — e.g. the
user mentioned "Wally is in final year" on two days, or "exchanged Zara
boots" twice. Corrections that REPLACE a value are NOT duplicates.
Pairs of (rid_a, rid_b) only. Return ONLY a JSON array of pairs,
e.g. [["rid1","rid2"]]. Empty array if none."""


def load_records(qid):
    snap = json.load(open(f"{MODEL_DIR}/{qid}.json"))
    hist = snap["export"]["asset"]["hist"]
    recs = []
    for key, edges in hist.items():
        slot = key.split("|")[-1]
        source = key.split("|")[0]
        for e in edges:
            recs.append({"rid": e[4] if len(e) > 4 else f"{key}#{len(recs)}",
                         "slot": slot, "source": source, "kind": e[2],
                         "day": e[1], "value": e[0]})
    return recs


def _json_list(text):
    t = text.strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else [v]
    except Exception:
        pass
    i, j = t.find("["), t.rfind("]")
    if i >= 0 and j > i:
        try:
            v = json.loads(t[i:j + 1])
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []


async def type_chunk(llm, chunk):
    prompt = ("RECORDS:\n" + json.dumps(chunk, ensure_ascii=False)
              + "\n\nTyped fields JSON array:")
    text = await llm.complete(FIELDS_SYS, prompt)
    out = _json_list(text)
    return {o["rid"]: o for o in out if isinstance(o, dict) and o.get("rid")}


async def dup_pass(llm, recs):
    lines = []
    for r in recs:
        v = str(r["value"])[:60].replace("\n", " ")
        lines.append(f"{r['rid']} | {r['kind']} | {r['slot']} | {v}")
    prompt = "RECORDS:\n" + "\n".join(lines) + "\n\nDuplicate pairs JSON array:"
    pairs = _json_list(await llm.complete(DUP_SYS, prompt))
    dups = {}
    for p in pairs:
        if isinstance(p, list) and len(p) == 2:
            a, b = str(p[0]), str(p[1])
            dups.setdefault(a, set()).add(b)
            dups.setdefault(b, set()).add(a)
    return {k: sorted(v) for k, v in dups.items()}


async def main():
    llm = OpenAICompatLLM(model="Atria-Dawn-Preview",
                          base_url="https://api.atria-asi.ai/v1",
                          api_key=os.environ["ATRIA_API_KEY"],
                          max_tokens=8192, retries=6)
    for qid in QIDS:
        out_path = f"{OUT_DIR}/typed_{qid}{OUT_SUFFIX}.json"
        recs = load_records(qid)
        # field pass, chunked (per-record work, no cross-record context)
        # small chunks: a 45-record response nears max_tokens and each
        # truncation retry regenerates the whole output from scratch
        typed = {}
        CHUNK = 20
        sem = asyncio.Semaphore(4)

        async def do_chunk(chunk, ci):
            async with sem:
                got = await type_chunk(llm, chunk)
                print(f"  {qid} chunk{ci}: {len(got)}/{len(chunk)}",
                      flush=True)
                missing = [r["rid"] for r in chunk if r["rid"] not in got]
                if missing:  # one retry for dropped records
                    got2 = await type_chunk(
                        llm, [r for r in chunk if r["rid"] in missing])
                    got.update(got2)
                return got

        chunks = [recs[i:i + CHUNK] for i in range(0, len(recs), CHUNK)]
        for got in await asyncio.gather(*[do_chunk(c, i)
                                          for i, c in enumerate(chunks)]):
            typed.update(got)
        # dup pass sees the whole model
        try:
            dups = await dup_pass(llm, recs)
        except Exception:
            dups = {}
        for rid, links in dups.items():
            if rid in typed:
                typed[rid]["dup_links"] = links
        json.dump({"qid": qid, "n_records": len(recs),
                   "n_typed": len(typed), "records": recs,
                   "typed": typed},
                  open(out_path, "w"), ensure_ascii=False, indent=1)
        print(f"{qid}: {len(recs)} records -> {len(typed)} typed, "
              f"{len(dups)} dup groups", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
