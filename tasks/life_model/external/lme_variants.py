"""M4 retrieval-layer variant ablation on the LongMemEval oracle sample.

One ingest pass per question (cached to disk as model export), then each
variant answers from an identical restored memory — a controlled ablation
where only the retrieval stage differs.

Usage:
    GLM_API_KEY=... python3 lme_variants.py run \
        --data ~/longmemeval/data/longmemeval_oracle.json \
        --per-type 12 --out-dir results/lme_retrieval \
        --variants base entity twohop pick50 kwfilter

Outputs per variant: hyp_<v>.jsonl (question_id/response/usage deltas).
Then judge each with lme.py --glm judge.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..")))
from lifemodel.model import LifeModel  # noqa: E402
from lifemodel.ingest_llm import LLMIngestor  # noqa: E402
from lifemodel import reader  # noqa: E402
from lme import GLMCompat, _ordinal  # noqa: E402

RETRIEVE_SYS = reader.RETRIEVE_SYS
ANSWER_SYS = reader.ANSWER_SYS


# ---------- variant retrieval stages --------------------------------------

async def _answer_from_keys(model, llm, question, qdate, keys):
    dg = reader.render_vertices(model, keys)
    prompt = (f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
              f"QUESTION: {question}\n\nAnswer:")
    resp = (await llm.complete(ANSWER_SYS, prompt)).strip()
    return {"response": resp, "selected": keys, "digest": dg}


def _entity_of(key: str) -> str:
    parts = key.split("|")
    if len(parts) == 3:
        return parts[1]
    src = parts[0]
    return "user" if src == "self" else src


async def v_base(model, llm, question, qdate):
    """Reference: vertex catalog -> LLM picks <=25 -> render."""
    return await reader.aanswer(model, llm, question, qdate)


async def v_pick50(model, llm, question, qdate):
    """Budget sweep: same two-stage with max_pick=50."""
    keys = await reader.aretrieve(model, llm, question, qdate, max_pick=50)
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_pick10(model, llm, question, qdate):
    """Budget sweep: same two-stage with max_pick=10."""
    keys = await reader.aretrieve(model, llm, question, qdate, max_pick=10)
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_entity(model, llm, question, qdate):
    """Entity-level catalog: LLM picks entities, all their vertices render."""
    cat = reader.vertex_catalog(model)
    ent2keys = {}
    for k in cat:
        ent2keys.setdefault(_entity_of(k), []).append(k)
    ents = {e: sum(cat[k][1] for k in ks) for e, ks in ent2keys.items()}
    max_ent = 10
    if len(ents) <= max_ent:
        keys = list(cat)
        return await _answer_from_keys(model, llm, question, qdate, keys)
    listing = "\n".join(f"{e}  ({n} entries)" for e, n in ents.items())
    sys = ("You are the retrieval stage of a memory system. Given the "
           "user's question and a catalog of remembered entities, pick "
           "the entity names that could contain the answer. Favor recall. "
           "Return ONLY a JSON array of the picked entity strings.")
    prompt = (f"Today: {qdate}\n\nENTITY CATALOG:\n{listing}\n\n"
              f"QUESTION: {question}\n\nRelevant entity names JSON array:")
    picks = reader._json_list(await llm.complete(sys, prompt))
    keys = []
    for e in picks:
        keys.extend(ent2keys.get(e, []))
    if not keys:
        keys = list(cat)
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_twohop(model, llm, question, qdate):
    """Two-hop: pick vertices -> expand to their entities' vertices ->
    LLM refines the expansion to <=10 keys -> render."""
    cat = reader.vertex_catalog(model)
    seed = await reader.aretrieve(model, llm, question, qdate, max_pick=15)
    ents = {_entity_of(k) for k in seed}
    cand = [k for k in cat if _entity_of(k) in ents]
    if len(cand) <= 10:
        return await _answer_from_keys(model, llm, question, qdate, cand)
    listing = "\n".join(f"{k}  ({cat[k][1]} entries)" for k in cand)
    prompt = (f"Today: {qdate}\n\nVERTEX CATALOG (candidate subset):\n"
              f"{listing}\n\nQUESTION: {question}\n\n"
              "Relevant vertex keys JSON array:")
    picks = reader._json_list(await llm.complete(RETRIEVE_SYS, prompt))
    keys = [k for k in picks if isinstance(k, str) and k in cat]
    return await _answer_from_keys(model, llm, question, qdate,
                                   keys[:10] if keys else cand[:10])


_TOK = re.compile(r"[a-z0-9]+")


def _toks(s: str) -> set:
    return set(_TOK.findall(s.lower()))


async def v_kwfilter(model, llm, question, qdate):
    """Keyword prefilter: token-overlap top-50 of catalog -> LLM picks."""
    cat = reader.vertex_catalog(model)
    max_pick = 25
    if len(cat) <= max_pick:
        return await _answer_from_keys(model, llm, question, qdate,
                                       list(cat))
    qt = _toks(question)
    ranked = sorted(cat, key=lambda k: -len(qt & _toks(reader._label(k))))
    cand = ranked[:50]
    if len(cand) <= max_pick:
        return await _answer_from_keys(model, llm, question, qdate, cand)
    listing = "\n".join(f"{k}  ({cat[k][1]} entries)" for k in cand)
    prompt = (f"Today: {qdate}\n\nVERTEX CATALOG (prefiltered):\n{listing}"
              f"\n\nQUESTION: {question}\n\nRelevant vertex keys JSON array:")
    picks = reader._json_list(await llm.complete(RETRIEVE_SYS, prompt))
    keys = [k for k in picks if isinstance(k, str) and k in cat]
    return await _answer_from_keys(model, llm, question, qdate,
                                   keys[:max_pick] if keys else cand)


def _slot_of(key: str) -> str:
    return key.split("|")[-1]


def _overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _dedup(keys):
    return list(dict.fromkeys(keys))


async def v_fam(model, llm, question, qdate):
    """Family expansion: LLM picks, then auto-include every catalog
    vertex whose slot tokens overlap a picked slot's tokens >=0.5."""
    cat = reader.vertex_catalog(model)
    keys = await reader.aretrieve(model, llm, question, qdate)
    picked_slot_toks = [_toks(_slot_of(k)) for k in keys]
    extra = [k for k in cat if k not in set(keys) and any(
        _overlap(_toks(_slot_of(k)), s) >= 0.5 for s in picked_slot_toks)]
    return await _answer_from_keys(model, llm, question, qdate,
                                   _dedup(keys + extra))


async def v_topic(model, llm, question, qdate):
    """Two-round pick: round 1 the LLM picks semantic families (slot
    names), round 2 includes ALL vertices under those slots."""
    cat = reader.vertex_catalog(model)
    if len(cat) <= 50:
        return await _answer_from_keys(model, llm, question, qdate,
                                       list(cat))
    fams = sorted({_slot_of(k) for k in cat})
    sys = ("You are the retrieval stage of a memory system. Given the "
           "user's question and a list of memory topic families (slot "
           "names), pick the families that could contain the answer. "
           "Favor recall: include a family when plausibly relevant. "
           "Return ONLY a JSON array of the picked family names.")
    prompt = (f"Today: {qdate}\n\nTOPIC FAMILIES:\n" + ", ".join(fams) +
              f"\n\nQUESTION: {question}\n\nRelevant family names "
              "JSON array:")
    picks = {f for f in reader._json_list(await llm.complete(sys, prompt))
             if f in set(fams)}
    keys = [k for k in cat if _slot_of(k) in picks]
    return await _answer_from_keys(model, llm, question, qdate,
                                   (keys or list(cat))[:150])


async def v_recur(model, llm, question, qdate):
    """Recursive expansion: if the pick hits the cap, a second round
    asks the LLM which topics are still missing."""
    cat = reader.vertex_catalog(model)
    keys = await reader.aretrieve(model, llm, question, qdate)
    if len(keys) >= 50 and len(cat) > len(keys):
        rest = [k for k in cat if k not in set(keys)]
        listing = "\n".join(f"{k}  ({cat[k][1]} entries)" for k in rest)
        sys = (RETRIEVE_SYS + " You already picked other vertices; now "
               "pick ONLY additional keys that are still needed for "
               "completeness (or [] if nothing is missing).")
        prompt = (f"Today: {qdate}\n\nREMAINING VERTEX CATALOG:\n{listing}"
                  f"\n\nQUESTION: {question}\n\nAdditional vertex keys "
                  "JSON array:")
        extra = [k for k in reader._json_list(
            await llm.complete(sys, prompt)) if k in cat]
        keys = keys + extra[:100]
    return await _answer_from_keys(model, llm, question, qdate,
                                   _dedup(keys))


async def v_big150(model, llm, question, qdate):
    """Budget sweep: same two-stage with max_pick=150."""
    keys = await reader.aretrieve(model, llm, question, qdate,
                                  max_pick=150)
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_mix(model, llm, question, qdate):
    """Hybrid: pick50 + slot-prefix family expansion (all slots sharing
    a head token with a picked slot join in)."""
    cat = reader.vertex_catalog(model)
    keys = await reader.aretrieve(model, llm, question, qdate)
    heads = {_slot_of(k).split("_")[0] for k in keys}
    extra = [k for k in cat if k not in set(keys)
             and _slot_of(k).split("_")[0] in heads]
    return await _answer_from_keys(model, llm, question, qdate,
                                   _dedup(keys + extra))


VARIANTS = {"base": v_base, "entity": v_entity, "twohop": v_twohop,
            "pick10": v_pick10, "pick50": v_pick50, "kwfilter": v_kwfilter,
            "fam": v_fam, "topic": v_topic, "recur": v_recur,
            "big150": v_big150, "mix": v_mix}


# ---------- driver ---------------------------------------------------------

def _usage_delta(u0, u1):
    return {k: u1[k] - u0[k] for k in u1}


def run(args):
    data = json.load(open(args.data))
    llm_extract = GLMCompat(api_key=os.environ.get("GLM_API_KEY"),
                            extra_body={"thinking": {"type": "disabled"}})
    llm_answer = GLMCompat(api_key=os.environ.get("GLM_API_KEY"),
                           extra_body={"thinking": {"type": "enabled"}})
    names = args.variants.split(",") if args.variants else list(VARIANTS)
    for v in names:
        assert v in VARIANTS, v
    mdir = os.path.join(args.out_dir, "models")
    os.makedirs(mdir, exist_ok=True)
    done = {v: set() for v in names}
    fhs = {}
    for v in names:
        p = os.path.join(args.out_dir, f"hyp_{v}.jsonl")
        if os.path.exists(p):
            for line in open(p):
                if line.strip():
                    done[v].add(json.loads(line)["question_id"])
        fhs[v] = open(p, "a")

    counts = {}
    todo = []
    for q in data:
        if q["question_id"].endswith("_abs"):
            continue
        if counts.get(q["question_type"], 0) >= args.per_type:
            continue
        counts[q["question_type"]] = counts.get(q["question_type"], 0) + 1
        todo.append(q)

    for i, q in enumerate(todo):
        qid = q["question_id"]
        mp = os.path.join(mdir, qid + ".json")
        if os.path.exists(mp):
            packed = json.load(open(mp))
            exported, nrecs = packed["export"], packed["n_records"]
        else:
            model = LifeModel()
            ing = LLMIngestor(llm_extract, day_of=_ordinal)
            nrecs = 0
            for date, sess in zip(q["haystack_dates"],
                                  q["haystack_sessions"]):
                try:
                    nrecs += asyncio.run(
                        ing.aingest_session(model, date, sess))
                except Exception as e:
                    print(f"[{qid}] extract fail @{date}: {e}",
                          file=sys.stderr)
            exported = model.export()
            json.dump({"n_records": nrecs, "export": exported},
                      open(mp, "w"))
        for v in names:
            if qid in done[v]:
                continue
            m2 = LifeModel()
            m2.import_state(exported["asset"])
            u0 = dict(llm_answer.usage)
            out = None
            try:
                out = asyncio.run(
                    VARIANTS[v](m2, llm_answer, q["question"],
                                q["question_date"]))
                resp = out["response"]
            except Exception as e:  # noqa: BLE001
                resp = f"__answer_error__ {e}"
            u1 = dict(llm_answer.usage)
            row = {"question_id": qid,
                   "question_type": q["question_type"],
                   "response": resp, "n_records": nrecs,
                   "usage": _usage_delta(u0, u1),
                   "selected": out.get("selected") if out else None,
                   "digest_bytes": len(out.get("digest", "")) if out else 0}
            fhs[v].write(json.dumps(row, ensure_ascii=False) + "\n")
            fhs[v].flush()
        print(f"[{i+1}/{len(todo)}] {qid} recs={nrecs} "
              f"extract={llm_extract.usage} answer={llm_answer.usage}",
              flush=True)
    for fh in fhs.values():
        fh.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", required=True)
    r.add_argument("--per-type", type=int, default=12)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--variants", default="")
    args = ap.parse_args()
    {"run": run}[args.cmd](args)


if __name__ == "__main__":
    main()
