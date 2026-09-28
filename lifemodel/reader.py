"""M4 retrieval layer — two-stage serve over the exported asset.

Stage 1 (retrieve): an LLM sees the *catalog* of vertices
(`who·slot` labels + edge counts) and picks which ones may answer the
question. Stage 2 (read): only the selected vertices' full edge
histories are rendered into the answer prompt.

Without retrieval the whole memory digest is dumped to the reader —
fine at 200 records, wrong at 20k. Retrieval is the honest long-horizon
path and it is module-level: `answer()` here is the M4 reference
implementation for open-domain questions.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re

RETRIEVE_SYS = """You are the retrieval stage of a memory system. Given the
user's question and a catalog of memory vertices (who·attribute), pick
the vertex keys that could contain the answer. Favor recall: include a
vertex when it is plausibly relevant, including entities the question
is about. Return ONLY a JSON array of the picked key strings."""

ANSWER_SYS = """You are an assistant with a long-term memory of the user.
Below are the relevant memory entries: each line is an attribute with
its value history and the dates it was said. Tags: [correction]
corrected, [retraction] withdrawn, [hearsay] second-hand claim,
[suggestion] someone suggested, (per assistant) said by the assistant.

Answer the user's question using ONLY this memory.
- Resolve relative dates against today's date given below.
- A value may carry ` (on YYYY-MM-DD)` — that is the EVENT's own date
  (when the thing happened), while `@YYYY-MM-DD` after the value is the
  date it was SAID. When a question asks when something happened,
  prefer the (on ...) event date over the said-date.
- If several values exist over time, the LATEST non-retracted one is
  current.
- COUNTING / AGGREGATION: for "how many", "how often", "total",
  "list", or comparison questions, first enumerate EVERY matching
  entry across all lines (values are numbered per line), dedupe by
  meaning (same fact stated twice = one), then count/compare. Write
  down the enumeration before answering — most aggregation errors come
  from answering off a partial list.
- PERSONALIZATION: for preference/recommendation/opinion questions
  ("would I like", "recommend", "do I prefer", "what should I"),
  treat the memory as the user's PROFILE, not a lookup table. Infer
  their taste from whatever entries exist (likes, dislikes, habits,
  past choices) and give a personalized answer. A recommendation needs
  no literal matching entry — related preferences are enough.
- Abstain ONLY if nothing is remotely relevant; then say exactly:
  "I don't have enough information to answer that."
- Answer concisely, no preamble."""


def _iso(ordinal: int) -> str:
    return _dt.date.fromordinal(int(ordinal)).isoformat()


def _label(key: str) -> str:
    parts = key.split("|")
    if len(parts) == 3:
        src, about, slot = parts
        return f"{about} (per {src})·{slot}"
    src, slot = parts
    who = "user" if src == "self" else src
    return f"{who}·{slot}"


def vertex_catalog(model) -> dict:
    """key -> (label, n_edges). The retrieval index."""
    hist = model.export()["asset"].get("hist", {})
    return {k: (_label(k), len(v)) for k, v in hist.items()}


def _json_list(text: str):
    t = text.strip()
    i, j = t.find("["), t.rfind("]")
    if i >= 0 and j > i:
        try:
            v = json.loads(t[i:j + 1])
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []


def render_vertices(model, keys: list[str]) -> str:
    hist = model.export()["asset"].get("hist", {})
    lines = []
    for key in keys:
        edges = hist.get(key)
        if not edges:
            continue
        parts = []
        for ei, e in enumerate(edges, 1):
            val, day, kind = e[0], e[1], e[2]
            tag = "" if kind in ("statement", "update") else f"[{kind}]"
            parts.append(f"#{ei} {val} @{_iso(day)}{tag}")
        lines.append(f"- {_label(key)}: " + " -> ".join(parts))
    return "\n".join(lines) if lines else "(nothing selected)"


async def aretrieve(model, llm, question: str, qdate: str,
                    max_pick: int = 50) -> list[str]:
    cat = vertex_catalog(model)
    if len(cat) <= max_pick:
        return list(cat)
    listing = "\n".join(f"{k}  ({n} entries)" for k, (_, n) in cat.items())
    prompt = (f"Today: {qdate}\n\nVERTEX CATALOG:\n{listing}\n\n"
              f"QUESTION: {question}\n\nRelevant vertex keys JSON array:")
    picks = _json_list(await llm.complete(RETRIEVE_SYS, prompt))
    keys = [k for k in picks if isinstance(k, str) and k in cat]
    return keys[:max_pick] if keys else list(cat)[:max_pick]


async def aanswer(model, llm, question: str, qdate: str) -> dict:
    """Two-stage answer. Returns {response, selected_vertices, digest}."""
    keys = await aretrieve(model, llm, question, qdate)
    dg = render_vertices(model, keys)
    prompt = (f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
              f"QUESTION: {question}\n\nAnswer:")
    resp = (await llm.complete(ANSWER_SYS, prompt)).strip()
    return {"response": resp, "selected": keys, "digest": dg}


def answer(model, llm, question: str, qdate: str) -> str:
    return asyncio.run(aanswer(model, llm, question, qdate))["response"]
