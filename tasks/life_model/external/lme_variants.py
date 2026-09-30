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
import time as _time

# stack root override lets an ablation run against a shadow package
# (e.g. results/oldstack with #41-era lifemodel) instead of the repo
_STACK_ROOT = os.environ.get(
    "LME_STACK_ROOT",
    os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, _STACK_ROOT)
from lifemodel.model import LifeModel  # noqa: E402
from lifemodel.ingest_llm import LLMIngestor  # noqa: E402
from lifemodel import reader  # noqa: E402
from lme import GLMCompat, _ordinal  # noqa: E402
from hyra.llm import OpenAICompatLLM  # noqa: E402

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


# ---------- answer-side aggregation variants ------------------------------
# Same retrieval (aretrieve -> digest) for every arm; only the answering
# stage differs.

ENUM_SYS = ("You are the evidence-extraction stage of a memory QA system. "
            "Given the user's memory and question, list EVERY memory line "
            "relevant to answering, verbatim, one per line. Include all "
            "items of the same semantic family — completeness matters "
            "more than brevity.")


async def _digest_of(model, llm, question, qdate):
    keys = await reader.aretrieve(model, llm, question, qdate)
    return keys, reader.render_vertices(model, keys)


async def v_twopass(model, llm, question, qdate):
    """Two-pass: enumerate evidence lines verbatim, then answer from the
    enumeration only — separates 'find everything' from 'compute right'."""
    keys, dg = await _digest_of(model, llm, question, qdate)
    ev = await llm.complete(
        ENUM_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nQUESTION: {question}\n\n"
        "Relevant evidence lines:")
    resp = (await llm.complete(
        ANSWER_SYS,
        f"Today's date: {qdate}\n\nEVIDENCE (verbatim from memory):\n{ev}\n\n"
        f"QUESTION: {question}\n\nAnswer:")).strip()
    return {"response": resp, "selected": keys, "digest": dg}


_ROUTER_SYS = ("Classify the question into exactly one label: "
               "count (how many / how often / total / list), "
               "compare (which is more/earlier/first, before or after), "
               "when (a date or time), other. Reply with the label only.")

_COUNT_SYS = (ANSWER_SYS + "\n\nThis is a COUNTING question. Mandatory "
              "format: first write one line per qualifying item "
              "(value @date), then a final line with just the total.")

_CMP_SYS = (ANSWER_SYS + "\n\nThis is a COMPARISON question. Mandatory "
            "format: list each candidate with its date, state the "
            "comparison explicitly, then the final answer.")

_WHEN_SYS = (ANSWER_SYS + "\n\nThis is a DATE question. Mandatory "
             "format: list the relevant dated events, then answer with "
             "the resolved date.")

_ROUTE_SYS = {"count": _COUNT_SYS, "compare": _CMP_SYS,
              "when": _WHEN_SYS, "other": ANSWER_SYS}


async def v_router(model, llm, question, qdate):
    """Type-router: classify the question, then answer under a
    type-specific format template."""
    keys, dg = await _digest_of(model, llm, question, qdate)
    label = (await llm.complete(_ROUTER_SYS,
                                f"QUESTION: {question}")).strip().lower()
    sys = _ROUTE_SYS.get(label, ANSWER_SYS)
    resp = (await llm.complete(
        sys, f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
             f"QUESTION: {question}\n\nAnswer:")).strip()
    return {"response": resp, "selected": keys, "digest": dg}


_VERIFY_SYS = ("You are the verification stage of a memory QA system. "
               "Given the memory, the question, and a draft answer, "
               "audit it: list the items the draft counted or relied on, "
               "check the enumeration against the memory for omissions "
               "and date/conflict mistakes, then output ONLY the final "
               "answer (concise, no preamble).")


async def v_verify(model, llm, question, qdate):
    """Self-verify: draft answer -> audit enumeration/omissions -> final."""
    keys, dg = await _digest_of(model, llm, question, qdate)
    draft = (await llm.complete(
        ANSWER_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
        f"QUESTION: {question}\n\nAnswer:")).strip()
    resp = (await llm.complete(
        _VERIFY_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nQUESTION: {question}\n\n"
        f"DRAFT ANSWER: {draft}\n\nAudit, then final answer:")).strip()
    return {"response": resp, "selected": keys, "digest": dg}


_EXTRACT_SYS = ("You are the extraction stage of a memory QA system. "
                "Given the memory and question, output a JSON array of "
                "candidate items: each element {\"value\": <short "
                "value/name>, \"date\": \"YYYY-MM-DD\" (the event date if "
                "given, else the said date)}. Include every plausibly "
                "relevant item — dedupe by meaning. JSON array only.")


async def v_code(model, llm, question, qdate):
    """Code-assist: LLM extracts candidate (value,date) items as JSON;
    Python deterministically dedupes/sorts/counts them; the final answer
    is composed with the pre-computed table + count."""
    keys, dg = await _digest_of(model, llm, question, qdate)
    raw = reader._json_list(await llm.complete(
        _EXTRACT_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nQUESTION: {question}\n\n"
        "Candidate items JSON array:"))
    items, seen = [], set()
    for it in raw:
        if not isinstance(it, dict):
            continue
        v, d = str(it.get("value", "")).strip(), str(it.get("date", ""))
        sig = (v.lower(), d)
        if v and sig not in seen:
            seen.add(sig)
            items.append((d, v))
    items.sort()
    table = "\n".join(f"- {v} @{d}" for d, v in items) or "(none)"
    resp = (await llm.complete(
        ANSWER_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nPRE-EXTRACTED "
        f"CANDIDATES (deduped, sorted, deterministic count="
        f"{len(items)}):\n{table}\n\nQUESTION: {question}\n\nAnswer:")
            ).strip()
    return {"response": resp, "selected": keys, "digest": dg}


_AGG_RE = re.compile(
    r"(how many|how often|how much|total|number of|list|first|last|"
    r"most recent|earliest|latest|before|after|between|when|longer|"
    r"longest|oldest|newest|ago|since)", re.I)


async def v_gate(model, llm, question, qdate):
    """Gated code-assist: the extract+candidate-table path only runs for
    aggregation-flavored questions (keyword gate, favors recall); other
    questions get a plain single-shot answer — saves the extra call."""
    keys, dg = await _digest_of(model, llm, question, qdate)
    if not _AGG_RE.search(question):
        resp = (await llm.complete(
            ANSWER_SYS,
            f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
            f"QUESTION: {question}\n\nAnswer:")).strip()
        return {"response": resp, "selected": keys, "digest": dg}
    raw = reader._json_list(await llm.complete(
        _EXTRACT_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nQUESTION: {question}\n\n"
        "Candidate items JSON array:"))
    items, seen = [], set()
    for it in raw:
        if not isinstance(it, dict):
            continue
        v, d = str(it.get("value", "")).strip(), str(it.get("date", ""))
        sig = (v.lower(), d)
        if v and sig not in seen:
            seen.add(sig)
            items.append((d, v))
    items.sort()
    table = "\n".join(f"- {v} @{d}" for d, v in items) or "(none)"
    resp = (await llm.complete(
        ANSWER_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nPRE-EXTRACTED "
        f"CANDIDATES (deduped, sorted, deterministic count="
        f"{len(items)}):\n{table}\n\nQUESTION: {question}\n\nAnswer:")
            ).strip()
    return {"response": resp, "selected": keys, "digest": dg}


def _iso_or_none(d: str):
    try:
        return _dt.date.fromisoformat(d.strip()[:10])
    except Exception:
        return None


async def v_tjoin(model, llm, question, qdate):
    """Temporal-join: same extraction as code-assist, but Python also
    computes deterministic time facts — per-item delta since previous
    event and the overall earliest/latest/span — and feeds them to the
    answer stage."""
    keys, dg = await _digest_of(model, llm, question, qdate)
    raw = reader._json_list(await llm.complete(
        _EXTRACT_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nQUESTION: {question}\n\n"
        "Candidate items JSON array:"))
    items, seen = [], set()
    for it in raw:
        if not isinstance(it, dict):
            continue
        v, d = str(it.get("value", "")).strip(), str(it.get("date", ""))
        sig = (v.lower(), d)
        if v and sig not in seen:
            seen.add(sig)
            items.append((d, v))
    items.sort(key=lambda t: (_iso_or_none(t[0]) or _dt.date.min, t[1]))
    lines, prev = [], None
    for d, v in items:
        dd = _iso_or_none(d)
        delta = f" (+{(dd - prev).days}d since prev)" if dd and prev \
            else ""
        if dd:
            prev = dd
        lines.append(f"- {v} @{d}{delta}")
    dated = [(_iso_or_none(d), v, d) for d, v in items if _iso_or_none(d)]
    span = (f"earliest {dated[0][2]}, latest {dated[-1][2]}, "
            f"span {(dated[-1][0] - dated[0][0]).days} days, "
            f"n={len(items)}") if dated else f"n={len(items)}"
    table = "\n".join(lines) or "(none)"
    resp = (await llm.complete(
        ANSWER_SYS,
        f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\nPRE-EXTRACTED "
        f"CANDIDATES (deduped, sorted; computed span: {span}):\n{table}\n\n"
        f"QUESTION: {question}\n\nAnswer:")).strip()
    return {"response": resp, "selected": keys, "digest": dg}


# ---------- catalog-crowding repair variants -------------------------------

async def v_famcatalog(model, llm, question, qdate):
    """Catalog grouped into entity-family blocks: the LLM picks
    families; every member vertex of a picked family enters the digest."""
    cat = reader.vertex_catalog(model)
    fams = {}
    for k, (lab, n) in cat.items():
        fams.setdefault(_entity_of(k), []).append(k)
    if len(fams) <= 1:
        return await _answer_from_keys(model, llm, question, qdate,
                                       list(cat))
    listing = "\n".join(
        f"{f}  ({len(ks)} vertices, {sum(cat[k][1] for k in ks)} entries)"
        for f, ks in fams.items())
    prompt = (f"Today: {qdate}\n\nENTITY CATALOG:\n{listing}\n\n"
              f"QUESTION: {question}\n\nRelevant entity names JSON array:")
    picks = reader._json_list(await llm.complete(RETRIEVE_SYS, prompt))
    fam_picks = [f for f in picks if isinstance(f, str) and f in fams]
    if not fam_picks:
        fam_picks = list(fams)
    keys = _dedup([k for f in fam_picks for k in fams[f]])
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_budget(model, llm, question, qdate):
    """Adaptive budget: the LLM may pick up to min(len(cat), 50)
    vertices — pure quantity, no family expansion."""
    cat = reader.vertex_catalog(model)
    budget = min(len(cat), 50)
    if len(cat) <= budget:
        return await _answer_from_keys(model, llm, question, qdate,
                                       list(cat))
    listing = "\n".join(
        f"{k}  ({n} entries)" for k, (_, n) in cat.items())
    prompt = (f"Today: {qdate}\n\nVERTEX CATALOG:\n{listing}\n\n"
              f"QUESTION: {question}\n\nSelect up to {budget} relevant "
              f"vertex keys. JSON array:")
    picks = reader._json_list(await llm.complete(RETRIEVE_SYS, prompt))
    keys = [k for k in picks if isinstance(k, str) and k in cat]
    keys = keys[:budget] if keys else list(cat)[:budget]
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_closure(model, llm, question, qdate):
    """Same vertex pick as base; then auto-include every catalog vertex
    sharing an `about` entity with a picked vertex."""
    cat = reader.vertex_catalog(model)
    keys = await reader.aretrieve(model, llm, question, qdate)
    ents = {_entity_of(k) for k in keys}
    keys += [k for k in cat if k not in set(keys)
             and _entity_of(k) in ents]
    return await _answer_from_keys(model, llm, question, qdate, keys)


# ---------- source-aware variants (srcprior/splitsrc/tiered) ----------------

def _src(key: str) -> str:
    return key.split("|")[0]


async def v_srcprior(model, llm, question, qdate):
    """Partitioned catalog: user block listed in full first, assistant
    block compressed to bare keys after it; pick budget unchanged."""
    cat = reader.vertex_catalog(model)
    if len(cat) <= 50:
        return await _answer_from_keys(model, llm, question, qdate,
                                       list(cat))
    user = [k for k in cat if _src(k) == "self"]
    asst = [k for k in cat if _src(k) != "self"]
    listing = ("USER MEMORY (detailed):\n"
               + "\n".join(f"{k}  ({cat[k][1]} entries)" for k in user)
               + "\n\nASSISTANT MEMORY (key list only):\n"
               + "\n".join(asst))
    prompt = (f"Today: {qdate}\n\nVERTEX CATALOG:\n{listing}\n\n"
              f"QUESTION: {question}\n\nRelevant vertex keys JSON array:")
    picks = reader._json_list(await llm.complete(RETRIEVE_SYS, prompt))
    keys = [k for k in picks if isinstance(k, str) and k in cat]
    keys = keys[:50] if keys else list(cat)[:50]
    heads = {k.split("|")[-1].split("_")[0] for k in keys}
    keys += [k for k in cat if k not in set(keys)
             and k.split("|")[-1].split("_")[0] in heads]
    return await _answer_from_keys(model, llm, question, qdate, keys)


async def v_splitsrc(model, llm, question, qdate):
    """Source quota: after the base pick, top up from the user block until
    >=60% of selected keys are user-source (as available)."""
    cat = reader.vertex_catalog(model)
    keys = await reader.aretrieve(model, llm, question, qdate)
    n_user = sum(1 for k in keys if _src(k) == "self")
    need = (0.6 * len(keys) - n_user) / 0.4
    if need > 0:
        seen = set(keys)
        extra = [k for k in cat
                 if _src(k) == "self" and k not in seen]
        keys += extra[:int(need + 0.999)]
    return await _answer_from_keys(model, llm, question, qdate, keys)


_ASST_Q = re.compile(
    r"\bassistant\b|chatbot|\brecommend|\bsuggest|\badvice\b", re.I)


def _render_tiered(model, keys: list[str]) -> str:
    hist = model.export()["asset"].get("hist", {})
    lines = []
    for key in keys:
        edges = hist.get(key)
        if not edges:
            continue
        lab = reader._label(key)
        if _src(key) == "self":
            parts = []
            for ei, e in enumerate(edges, 1):
                val, day, kind = e[0], e[1], e[2]
                tag = "" if kind in ("statement", "update") else f"[{kind}]"
                parts.append(f"#{ei} {val} @{reader._iso(day)}{tag}")
            lines.append(f"- {lab}: " + " -> ".join(parts))
        else:
            val, day, kind = edges[0][0], edges[0][1], edges[0][2]
            tag = "" if kind in ("statement", "update") else f"[{kind}]"
            lines.append(f"- {lab}: ({len(edges)} entries) first: "
                         f"{val} @{reader._iso(day)}{tag}")
    return "\n".join(lines) if lines else "(nothing selected)"


async def v_tiered(model, llm, question, qdate):
    """Tiered digest: user vertices render every edge; assistant vertices
    collapse to label + edge count + first edge — unless the question is
    about the assistant itself."""
    keys = await reader.aretrieve(model, llm, question, qdate)
    if _ASST_Q.search(question):
        return await _answer_from_keys(model, llm, question, qdate, keys)
    dg = _render_tiered(model, keys)
    prompt = (f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
              f"QUESTION: {question}\n\nAnswer:")
    resp = (await llm.complete(ANSWER_SYS, prompt)).strip()
    return {"response": resp, "selected": keys, "digest": dg}


VARIANTS = {"base": v_base, "entity": v_entity, "twohop": v_twohop,
            "pick10": v_pick10, "pick50": v_pick50, "kwfilter": v_kwfilter,
            "fam": v_fam, "topic": v_topic, "recur": v_recur,
            "big150": v_big150, "mix": v_mix,
            "twopass": v_twopass, "router": v_router,
            "verify": v_verify, "code": v_code,
            "gate": v_gate, "tjoin": v_tjoin,
            "famcatalog": v_famcatalog, "budget": v_budget,
            "closure": v_closure,
            "srcprior": v_srcprior, "splitsrc": v_splitsrc,
            "tiered": v_tiered}


# ---------- driver ---------------------------------------------------------

def _usage_delta(u0, u1):
    return {k: u1[k] - u0[k] for k in u1}


def run(args):
    data = json.load(open(args.data))
    llm_extract = GLMCompat(api_key=os.environ.get("GLM_API_KEY"),
                            extra_body={"thinking": {"type": "disabled"}})
    if args.answer_backend == "openrouter":
        # one flag switches both clients — needed when the ingest cache
        # must also be built without GLM
        _or = dict(model=os.environ.get("OR_MODEL",
                                        "stealth/space-bunny-alpha"),
                   base_url="https://openrouter.ai/api/v1",
                   api_key=os.environ.get("OR_API_KEY", ""),
                   max_tokens=16384)
        llm_extract = GLMCompat(
            extra_body={"reasoning": {"effort": "low"}}, **_or)
        llm_answer = GLMCompat(**_or)
    elif args.answer_backend == "atria":
        # SSE-streamed client required — Atria kills non-streamed calls
        # in flight at ~5min; rejects reasoning/extra_body params (400)
        _at = dict(model=os.environ.get("OPENAI_MODEL",
                                        "Atria-Dawn-Preview"),
                   base_url=os.environ.get(
                       "OPENAI_BASE_URL", "https://api.atria-asi.ai/v1"),
                   api_key=os.environ.get("OPENAI_API_KEY") or
                   os.environ.get("ATRIA_API_KEY", ""),
                   max_tokens=8192)
        llm_extract = OpenAICompatLLM(**_at)
        llm_answer = OpenAICompatLLM(**_at)
    else:
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
                    r = json.loads(line)
                    if not str(r.get("response", "")).startswith(
                            "__answer_error__"):
                        done[v].add(r["question_id"])
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

    todo_left = list(todo)
    for _round in range(20):
        if not todo_left:
            break
        if _round:
            print(f"[round {_round}] {len(todo_left)} questions deferred",
                  flush=True)
            _time.sleep(180)
        deferred = []
        for i, q in enumerate(todo_left):
            qid = q["question_id"]
            if all(qid in done[v] for v in names):
                continue
            mp = os.path.join(mdir, qid + ".json")
            try:
                if os.path.exists(mp):
                    packed = json.load(open(mp))
                    exported, nrecs = packed["export"], packed["n_records"]
                else:
                    model = LifeModel()
                    ing = LLMIngestor(llm_extract, day_of=_ordinal)
                    nrecs = 0
                    for date, sess in zip(q["haystack_dates"],
                                          q["haystack_sessions"]):
                        for _try in range(5):
                            try:
                                nrecs += asyncio.run(
                                    ing.aingest_session(model, date, sess))
                                break
                            except Exception as e:
                                if "429" in str(e) and _try < 4:
                                    _time.sleep(30 * (_try + 1))
                                    continue
                                # never cache a partial model
                                raise RuntimeError(
                                    f"[{qid}] ingest aborted @{date}: {e}")
                    exported = model.export()
                    json.dump({"n_records": nrecs, "export": exported},
                              open(mp, "w"))
            except RuntimeError as e:
                print(e, file=sys.stderr)
                deferred.append(q)
                continue
            needs_retry = False
            for v in names:
                if qid in done[v]:
                    continue
                m2 = LifeModel()
                m2.import_state(exported["asset"])
                u0 = dict(llm_answer.usage)
                out = None
                try:
                    for _try in range(5):
                        try:
                            out = asyncio.run(
                                VARIANTS[v](m2, llm_answer, q["question"],
                                            q["question_date"]))
                            break
                        except Exception as e:  # noqa: BLE001
                            if "429" in str(e) and _try < 4:
                                _time.sleep(30 * (_try + 1))
                                continue
                            raise
                    resp = out["response"]
                except Exception as e:  # noqa: BLE001
                    resp = f"__answer_error__ {e}"
                    needs_retry = True
                u1 = dict(llm_answer.usage)
                row = {"question_id": qid,
                       "question_type": q["question_type"],
                       "response": resp, "n_records": nrecs,
                       "usage": _usage_delta(u0, u1),
                       "selected": out.get("selected") if out else None,
                       "digest_bytes": len(out.get("digest", ""))
                       if out else 0}
                fhs[v].write(json.dumps(row, ensure_ascii=False) + "\n")
                fhs[v].flush()
                if not resp.startswith("__answer_error__"):
                    done[v].add(qid)
            if needs_retry:
                deferred.append(q)
            print(f"[{i+1}/{len(todo_left)}] {qid} recs={nrecs} "
                  f"extract={llm_extract.usage} answer={llm_answer.usage}",
                  flush=True)
        todo_left = deferred
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
    r.add_argument("--answer-backend", default="glm",
                   choices=["glm", "openrouter", "atria"])
    args = ap.parse_args()
    {"run": run}[args.cmd](args)


if __name__ == "__main__":
    main()
