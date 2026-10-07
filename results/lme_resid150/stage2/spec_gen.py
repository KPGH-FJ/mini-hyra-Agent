#!/usr/bin/env python3
"""stage-3 arm: vocabulary-aware aggregation-spec generation.

stage-2 showed the bottleneck is spec<->field vocabulary alignment, not
extraction. This arm gives the spec writer the snapshot's ACTUAL typed
vocabulary (distinct verbs/classes/locations with counts) and asks it to
write a closed-DSL aggregation spec; deterministic eval then runs it
verbatim — no gold annotations anywhere in the loop.

Spec DSL (all keys optional except op):
  {"op": "count_events"|"count_distinct"|"sum",
   "verbs": [..], "object_class": [..], "objects_contain": [..],
   "obligation_status": [..], "location": [..],
   "kind": ["asserted"],                # default asserted-only
   "window": {"kind":"past_days","days":N}
             | {"kind":"year","year":YYYY}
             | {"kind":"loose_last_week"},
   "field": "object"|"quantity"|"duration_hours"|"duration_days",
   "exclude_objects_contain": [..]}

Run: ATRIA_API_KEY=... python3 results/lme_resid150/stage2/spec_gen.py
"""
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
from hyra.llm import OpenAICompatLLM  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fidelity_eval as F  # noqa: E402  (resolve_dups/in_window/duration_as)

D = json.load(open("results/lme_resid150/stage1/annotations.json"))
OUT = "results/lme_resid150/stage2"
QIDS = ["0a995998", "88432d0a", "d682f1a2", "gpt4_7fce9456",
        "7024f17c", "b5ef892d", "gpt4_f2262a51"]

SPEC_SYS = """You write a deterministic aggregation spec for a personal-memory
store whose records carry typed fields: kind (asserted|negated|planned|
cancelled), verb, object, object_class, quantity, quantifier, when_abs
(ISO or partial YYYY-MM/YYYY), granularity (day|week|month|year),
duration_value+duration_unit, obligation_status (awaiting_pickup|
awaiting_return|fulfilled), counterparty, location, dup_links.

You will see the QUESTION, its date, and the store's ACTUAL vocabulary
(distinct values with counts). Pick verbs/classes/locations ONLY from
that vocabulary — a predicate using a word the store doesn't have
matches nothing. For "how many times did I X" questions choose every
vocabulary verb that could denote the asked activity (visit covers
attend/diagnose when the object is a doctor, camp covers camping_trip,
take_trip, offroad-... etc.), and filter with objects_contain /
object_class when the question names the target.

Emit spec JSON:
{"op": "count_events"|"count_distinct"|"sum",
 "verbs": [<vocabulary verbs>] or null,
 "object_class": [<vocabulary classes>] or null,
 "objects_contain": [<substrings>] or null,
 "obligation_status": [<values>] or null,
 "location": [<vocabulary locations>] or null,
 "kind": ["asserted"] (default; add others only if the question asks),
 "window": {"kind":"past_days","days":N} | {"kind":"year","year":YYYY}
           | {"kind":"loose_last_week"} | null,
 "field": "object"|"quantity"|"duration_hours"|"duration_days"
          (sum only),
 "exclude_objects_contain": [<substrings>] or null,
 "explain": "one line"}

Notes:
- "how many distinct/different X" -> count_distinct over field=object
- window past_days uses the question date as ref; loose_last_week means
  the ~2 weeks before it (day-granularity records only)
- Return ONLY the JSON object."""


def vocab_of(typed):
    verbs = Counter(str(t.get("verb")) for t in typed.values())
    classes = Counter(str(t.get("object_class"))
                      for t in typed.values() if t.get("object_class"))
    locs = Counter(str(t.get("location"))
                   for t in typed.values() if t.get("location"))
    objs = Counter(str(t.get("object"))
                   for t in typed.values() if t.get("object"))
    obs = Counter(str(t.get("obligation_status"))
                  for t in typed.values() if t.get("obligation_status"))
    kinds = Counter(str(t.get("kind")) for t in typed.values())
    return {"verbs": dict(verbs.most_common(40)),
            "object_class": dict(classes.most_common(25)),
            "location": dict(locs.most_common(25)),
            "objects": dict(objs.most_common(30)),
            "obligation_status": dict(obs),
            "kind": dict(kinds)}


SPEC2_SYS = """You write a deterministic aggregation spec for a personal-memory
store whose records carry typed fields: kind (asserted|negated|planned|
cancelled), verb, object, object_class, quantity, quantifier, when_abs
(ISO or partial YYYY-MM/YYYY), granularity (day|week|month|year),
duration_value+duration_unit, obligation_status (awaiting_pickup|
awaiting_return|fulfilled), counterparty, location, dup_links.

You will see the QUESTION, its date, and the store's ACTUAL vocabulary
(distinct values with counts). Pick verbs/classes/locations ONLY from
that vocabulary.

CRITICAL — extraction is noisy; the same real-world event may be typed
under DIFFERENT frames:
- a used food-delivery order may be verb=eat object_class=food, or
  verb=use/find object_class=service
- a camping trip may be verb=attend object='camping trip', or
  verb=camping_trip object=<place>
- a doctor visit may be verb=diagnose object=<the CONDITION> (the
  doctor entity is often lost), or verb=attend object=<appointment>
- a pending obligation may be kind=planned not asserted; rely on
  obligation_status, not kind, for open-obligation questions
- when_abs is often null — a window clause silently drops such records

Therefore emit "any_of": a LIST of 1-3 alternative conjunctive clauses
(a record passes if ANY clause matches). Cover every plausible surface
realization. Each clause has the same keys:
{"op": "count_events"|"count_distinct"|"sum",
 "any_of": [
   {"verbs":[<vocab verbs>]|null, "object_class":[<vocab classes>]|null,
    "objects_contain":[<substrings>]|null, "obligation_status":[..]|null,
    "location":[<vocab locs>]|null, "kind":["asserted",..]|null,
    "window":{"kind":"past_days","days":N}|{"kind":"year","year":YYYY}
             |{"kind":"loose_last_week"}|null},
   ...],
 "field": "object"|"quantity"|"duration_hours"|"duration_days" (sum only),
 "explain": "one line"}

Rules:
- objects_contain matches if ANY listed substring appears in object
- window applies to when_abs; records with when_abs null fail the
  window — if the question's target may have null dates, include a
  clause without window
- "how many distinct/different X" -> count_distinct over field=object
- Return ONLY the JSON object."""


def _clause_passes(clause, r, qdate):
    if clause.get("kind"):
        if r.get("kind") not in clause["kind"]:
            return False
    elif r.get("kind") != "asserted":
        return False
    if clause.get("verbs") and r.get("verb") not in clause["verbs"]:
        return False
    if clause.get("object_class") and \
            r.get("object_class") not in clause["object_class"]:
        return False
    if clause.get("objects_contain"):
        o = F.norm(r.get("object"))
        if not any(F.norm(s) in o for s in clause["objects_contain"]):
            return False
    if clause.get("exclude_objects_contain"):
        o = F.norm(r.get("object"))
        if any(F.norm(s) in o for s in clause["exclude_objects_contain"]):
            return False
    if clause.get("obligation_status") and \
            r.get("obligation_status") not in clause["obligation_status"]:
        return False
    if clause.get("location") and r.get("location") not in clause["location"]:
        return False
    w = clause.get("window")
    if w:
        iw = F.in_window(r, w, qdate)
        if iw is not True:
            return False
    return True


def passes(spec, r, pool):
    qd = F.qdate(spec["_qdate"])
    if spec.get("any_of"):
        return any(_clause_passes(c, r, qd) for c in spec["any_of"])
    return _clause_passes(spec, r, qd)


def answer_with_spec(q, spec, typed):
    pool = [{**t, "rid": rid} for rid, t in typed.items()]
    groups = F.resolve_dups(pool)
    events = [min(m, key=lambda r: r["rid"]) for m in groups.values()]
    sel = [r for r in events if passes(spec, r, pool)]
    op = spec.get("op")
    if op == "count_events":
        result = len(sel)
    elif op == "count_distinct":
        result = len({F.norm(r.get("object")) for r in sel})
    elif op == "sum":
        f = spec.get("field", "quantity")
        result = sum((r.get(f) if r.get(f) is not None
                      else F.duration_as(r, f)) or 0 for r in sel)
    else:
        result = None
    return {"answer": result, "evidence": [r["rid"] for r in sel],
            "pool": len(pool)}


async def main():
    llm = OpenAICompatLLM(model="Atria-Dawn-Preview",
                          base_url="https://api.atria-asi.ai/v1",
                          api_key=os.environ["ATRIA_API_KEY"],
                          max_tokens=2048, retries=6)
    rescued = targets = heldok = 0
    out = {}
    for q in D["questions"]:
        qid = q["qid"]
        data = F.load_typed(qid)
        typed = data["typed"]
        vocab = vocab_of(typed)
        prompt = (f"QUESTION: {q['question']}\n"
                  f"QUESTION DATE: {q['qdate']}\n\n"
                  f"STORE VOCABULARY:\n{json.dumps(vocab, indent=1)}\n\n"
                  "Spec JSON:")
        spec = None
        sys_prompt = SPEC2_SYS if os.environ.get("ARM") == "v2" \
            else SPEC_SYS
        for _ in range(3):
            txt = (await llm.complete(sys_prompt, prompt)).strip()
            i, j = txt.find("{"), txt.rfind("}")
            try:
                spec = json.loads(txt[i:j + 1])
                break
            except Exception:
                continue
        if spec is None:
            print(f"{qid}: spec generation FAILED")
            continue
        spec["_qdate"] = q["qdate"]
        res = answer_with_spec(q, spec, typed)
        gold_num = str(q["gold"]).split(" ")[0]
        try:
            ok = abs(float(res["answer"]) - float(gold_num)) < 1e-6
        except (TypeError, ValueError):
            ok = str(res["answer"]) == str(q["gold"])
        tag = "HELDOUT" if q.get("held_out") else "TARGET"
        if not q.get("held_out"):
            targets += 1
            rescued += ok
        else:
            heldok += ok
        out[qid] = {"spec": spec, "result": res, "gold": q["gold"],
                    "flat": q["flat_answer"], "match": bool(ok)}
        print(f"{tag} {qid} | gold={q['gold']} | vocab-spec="
              f"{res['answer']} | flat={q['flat_answer']} | "
              f"{'MATCH' if ok else 'MISS'}", flush=True)
        print(f"   spec: {json.dumps({k: v for k, v in spec.items() if k != '_qdate'}, ensure_ascii=False)[:300]}")
        print(f"   evidence({len(res['evidence'])}): {res['evidence']}")
    print(f"\nvocab-spec rescue: {rescued}/{targets} targets, "
          f"{heldok}/2 heldout preserved")
    arm = os.environ.get("ARM", "")
    suffix = f"_{arm}" if arm else ""
    json.dump(out, open(f"{OUT}/spec_gen_results{suffix}.json", "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
