"""LongMemEval harness with M1 ingest-variant knobs (ablation lab).

Same pipeline as lme.py (extract -> ingest -> digest -> LLM answer ->
GLM judge); extraction behavior is driven by env vars so each variant is
an identical run with one knob moved:

  LME_THRESH    float; <0 disables local slot canon entirely (stock lme
                behavior). ingest_llm.py parity = 0.5.
  LME_ENTITY    0/1 fold `about` names onto the entity catalog (thr 0.4).
  LME_GRAIN     'session' (default) | 'round' (one extraction call per
                user+assistant round — more calls, fresher catalog).
  LME_TWOSTAGE  0/1: stage-1 free slot names, stage-2 LLM call merges the
                session's new names onto the catalog.
  LME_EXAMPLES  0/1: catalog lines shown with a sample existing value.
  LME_CONC      int question-level concurrency (default 4).

Usage mirrors lme.py:
    python lme_v.py run   --data oracle.json --per-type 12 --out hyp.jsonl
    python lme_v.py judge --hyp hyp.jsonl --ref oracle.json --out m.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "..")))

from lme import (_make_llm, _json_list, _ordinal, _iso, digest,  # noqa: E402
                 ANSWER_SYS, _judge_prompt, EXTRACT_SYS)
from lifemodel.model import LifeModel  # noqa: E402

THRESH = float(os.environ.get("LME_THRESH", "0.5"))
ENTITY = os.environ.get("LME_ENTITY", "1") == "1"
GRAIN = os.environ.get("LME_GRAIN", "session")
TWOSTAGE = os.environ.get("LME_TWOSTAGE", "0") == "1"
EXAMPLES = os.environ.get("LME_EXAMPLES", "0") == "1"
CONC = int(os.environ.get("LME_CONC", "4"))

_SLOT_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set:
    return set(_SLOT_TOKEN_RE.findall(str(s).lower()))


def _canon(slot: str, catalog: list, thresh: float) -> str:
    slot = re.sub(r"\W+", "_", str(slot).strip().lower()).strip("_")[:60]
    if not slot or slot in catalog:
        return slot
    ts = _tokens(slot)
    best, best_j = slot, 0.0
    for c in catalog:
        ct = _tokens(c)
        if not ct:
            continue
        j = len(ts & ct) / max(len(ts | ct), 1)
        if j > best_j:
            best_j, best = j, c
    return best if best_j >= thresh else slot


def _catalog(model: LifeModel) -> list:
    hist = model.export()["asset"].get("hist", {})
    return sorted({k.split("|")[-1] for k in hist})


def _entity_catalog(model: LifeModel) -> list:
    hist = model.export()["asset"].get("hist", {})
    return sorted({k.split("|")[1] for k in hist if k.count("|") == 2})


def _catalog_block(model: LifeModel) -> str:
    """Prompt block advertising existing slots (optionally w/ samples)."""
    hist = model.export()["asset"].get("hist", {})
    if not hist:
        return ""
    if not EXAMPLES:
        slots = sorted({k.split("|")[-1] for k in hist})
        return ("\n\nExisting slot names (REUSE one of these verbatim "
                "when it covers the fact; invent a new name only when "
                "none fits):\n" + ", ".join(slots[:400]))
    seen = {}
    for k, edges in hist.items():
        slot = k.split("|")[-1]
        for e in edges:
            v = str(e[0])[:40]
            if v not in seen.setdefault(slot, []):
                seen[slot].append(v)
    lines = [f"{s}: " + " | ".join(vals[:2])
             for s, vals in sorted(seen.items())[:300]]
    return ("\n\nExisting attributes (REUSE a name verbatim when it "
            "covers the fact):\n" + "\n".join(lines))


MERGE_SYS = """You consolidate memory attribute names.
Given NEW slot names extracted from one session and the EXISTING catalog,
decide the final name for each new slot: reuse a catalog name verbatim
when it covers the same fact, otherwise keep a normalized snake_case form
of the new name. Output ONLY a JSON object {"new_name": "final_name"}."""


def _rounds(turns: list) -> list:
    """Split a session into rounds: a user turn + following assistant
    turns, up to the next user turn."""
    out, cur = [], []
    for t in turns:
        if t["role"] == "user" and cur:
            out.append(cur)
            cur = []
        cur.append(t)
    if cur:
        out.append(cur)
    return out


async def _extract_one(llm, date_str: str, turns: list,
                       model: LifeModel, free_slots: bool) -> list:
    body = "\n".join(("USER" if t["role"] == "user" else "ASSISTANT")
                     + ": " + t["content"] for t in turns)
    known = "" if free_slots else _catalog_block(model)
    sys_p = EXTRACT_SYS
    if free_slots:
        sys_p = (EXTRACT_SYS
                 + "\n- Invent concise snake_case slot names freely; a "
                   "later step consolidates them.")
    prompt = (f"Session date: {date_str}\n{known}\n\n{body}\n\n"
              "Records JSON array:")
    return _json_list(await llm.complete(sys_p, prompt))


async def _merge_names(llm, new_names: list, catalog: list) -> dict:
    if not new_names:
        return {}
    prompt = ("EXISTING catalog:\n" + ", ".join(catalog[:400])
              + "\n\nNEW names:\n" + ", ".join(sorted(set(new_names)))
              + "\n\nJSON mapping:")
    m = _json_list(await llm.complete(MERGE_SYS, prompt))
    if isinstance(m, list):  # tolerate [{old:new}] shape
        m = {list(d.keys())[0]: list(d.values())[0] for d in m
             if isinstance(d, dict) and d}
    return m if isinstance(m, dict) else {}


async def extract_v(llm, date_str: str, turns: list,
                    model: LifeModel) -> list:
    """Extract records for one session honoring the env knobs."""
    units = [turns] if GRAIN == "session" else _rounds(turns)
    raw, new_names = [], []
    for u in units:
        raw += await _extract_one(llm, date_str, u, model,
                                  free_slots=TWOSTAGE)
    if TWOSTAGE:
        mapping = await _merge_names(
            llm, [str(r.get("slot")) for r in raw
                  if isinstance(r, dict) and r.get("slot")],
            _catalog(model))
    else:
        mapping = {}
    day = _ordinal(date_str)
    catalog = _catalog(model)
    ents = _entity_catalog(model) if ENTITY else []
    out = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict) or not r.get("slot"):
            continue
        slot = mapping.get(str(r["slot"]), str(r["slot"]))
        if THRESH >= 0:
            slot = _canon(slot, catalog, THRESH)
        about = r.get("about")
        if about and ENTITY:
            about = _canon(str(about), ents, 0.4)
        out.append({
            "id": f"lmev_{day}_{i}",
            "day": day,
            "source": r.get("source", "self"),
            "kind": r.get("kind", "statement"),
            "slot": slot,
            "value": r.get("value"),
            "about": about,
            "text": str(r.get("text", ""))[:200],
        })
    return out


async def answer_v(llm, model: LifeModel, q: dict) -> str:
    now = _ordinal(q["question_date"])
    prompt = (f"Today's date: {_iso(now)} ({q['question_date']})\n\n"
              f"MEMORY:\n{digest(model, now)}\n\n"
              f"QUESTION: {q['question']}\n\nAnswer:")
    return (await llm.complete(ANSWER_SYS, prompt)).strip()


async def _pipeline(llm, llm_answer, q: dict) -> dict:
    model = LifeModel()
    nrecs = 0
    for date, sess in zip(q["haystack_dates"], q["haystack_sessions"]):
        try:
            recs = await extract_v(llm, date, sess, model)
        except Exception as e:  # noqa: BLE001
            print(f"[{q['question_id']}] extract fail @{date}: {e}",
                  file=sys.stderr, flush=True)
            recs = []
        for r in recs:
            model.ingest(r)
        nrecs += len(recs)
    try:
        resp = await answer_v(llm_answer, model, q)
    except Exception as e:  # noqa: BLE001
        resp = f"__answer_error__ {e}"
    return {"question_id": q["question_id"],
            "question_type": q["question_type"],
            "response": resp, "n_records": nrecs}


def _select(args):
    data = json.load(open(args.data))
    counts, out = {}, []
    if args.per_type:
        data = [q for q in data
                if not q["question_id"].endswith("_abs")]
    for q in data:
        if args.per_type:
            if counts.get(q["question_type"], 0) >= args.per_type:
                continue
            counts[q["question_type"]] = \
                counts.get(q["question_type"], 0) + 1
            out.append(q)
        elif len(out) < args.n:
            out.append(q)
    return out


def run(args):
    qs = _select(args)
    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            if line.strip():
                done.add(json.loads(line)["question_id"])
    todo = [q for q in qs if q["question_id"] not in done]
    llm = _make_llm(args)
    llm_answer = _make_llm(args, thinking=True)
    fh = open(args.out, "a")
    wlock = asyncio.Lock()
    sem = asyncio.Semaphore(CONC)
    left = [len(todo)]

    async def work(q):
        async with sem:
            res = await _pipeline(llm, llm_answer, q)
        async with wlock:
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            left[0] -= 1
            print(f"[{len(todo)-left[0]}/{len(todo)}] {res['question_id']} "
                  f"({res['question_type']}) recs={res['n_records']} "
                  f"resp={res['response'][:60]!r} usage={llm.usage}",
                  flush=True)

    async def go():
        await asyncio.gather(*[work(q) for q in todo])

    asyncio.run(go())
    fh.close()


def judge(args):
    ref = {q["question_id"]: q for q in json.load(open(args.ref))}
    llm = _make_llm(args, backend=args.judge_backend or (
        'glm' if getattr(args, 'glm', False) else None))

    async def one(h, q):
        absn = q["question_id"].endswith("_abs")
        prompt = _judge_prompt(q["question_type"], q["question"],
                               q["answer"], h["response"], absn)
        out = await llm.complete("You are a strict grader. "
                                 "Reply yes or no only.", prompt)
        return out.strip().lower().startswith("yes")

    rows, by_type = [], {}
    for line in open(args.hyp):
        if not line.strip():
            continue
        h = json.loads(line)
        q = ref[h["question_id"]]
        try:
            ok = asyncio.run(one(h, q))
        except Exception as e:  # noqa: BLE001
            print("judge fail", h["question_id"], e, file=sys.stderr)
            ok = False
        rows.append({"question_id": h["question_id"],
                     "question_type": q["question_type"], "correct": ok})
        by_type.setdefault(q["question_type"], []).append(ok)
    acc = sum(r["correct"] for r in rows) / max(len(rows), 1)
    per = {k: sum(v) / len(v) for k, v in by_type.items()}
    out = {"n": len(rows), "accuracy": acc, "by_type": per, "rows": rows}
    json.dump(out, open(args.out, "w"), indent=2)
    print(json.dumps({"n": len(rows), "accuracy": acc,
                      "by_type": per}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get(
        "OPENAI_MODEL", "Atria-Dawn-Preview"))
    ap.add_argument("--glm", action="store_true",
                    help="use GLM (GLM_API_KEY) instead of OpenAI-compat")
    ap.add_argument("--base-url", default=os.environ.get(
        "OPENAI_BASE_URL", "https://api.atria-asi.ai/v1"))
    ap.add_argument("--api-key", default=os.environ.get(
        "OPENAI_API_KEY", os.environ.get("ATRIA_API_KEY", "")))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", required=True)
    r.add_argument("--n", type=int, default=10)
    r.add_argument("--per-type", type=int, default=0)
    r.add_argument("--out", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--hyp", required=True)
    j.add_argument("--ref", required=True)
    j.add_argument("--out", required=True)
    j.add_argument("--judge-backend", default=None,
                   choices=["glm", "openrouter"])
    args = ap.parse_args()
    {"run": run, "judge": judge}[args.cmd](args)


if __name__ == "__main__":
    main()
