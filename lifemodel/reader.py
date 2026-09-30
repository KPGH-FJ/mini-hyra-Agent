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
- A value may carry ` (on <date>)` — that is the EVENT's own date,
  resolved to a day (YYYY-MM-DD) or kept verbatim when fuzzy
  ("June 2023", "the week before X"), while `@YYYY-MM-DD` after the
  value is the date it was SAID. When a question asks when something
  happened, prefer the (on ...) event date over the said-date; answer
  at the granularity the question deserves (a "June 2023" answer is
  correct for a "June 2023" fact).
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
- Answer concisely, no preamble.

- EVIDENCE RULE: before asserting an answer, you must be able to point
  to a specific memory entry (a value plus its date) that supports it.
  If memory only supports adjacent facts — not the specific thing asked —
  say exactly "Memory only records X; it does not answer Y."
  Never present adjacent facts as the answer.
- SUBJECT CHECK: each memory line names who it is about ("caroline
  (per self)·slot" / "user·slot"). An answer may only attribute a fact
  to the person its line names. If the question asks about person X but
  the matching records are about person Y, say the records describe Y —
  e.g. "the records describe Y's adoption process, not X's". Never
  silently transfer one person's facts to another."""

PVERIFY_SYS = """You are the premise-verification stage of a memory reader.

A question is only answerable when the facts it PRESUPPOSES are each
stated by a memory record. Work in two steps:

1. Break the question's presupposed claim into atomic parts:
   <who> + <what fact or event> + <the specific detail asked for>
   (the noun or value that would form the answer — "trophy",
   "store", "walk").
2. For EACH atomic part find ONE single record (by number) and quote
   the record's exact words for it. The same person/event described in
   different words counts as a bind; assembling a part across
   different records does NOT count — if the parts live in different
   records or under different people, the premise is SPLICED.
3. The asked-detail is the strict test: it must appear in the bound
   record's own words — verbatim, or as content that directly IS the
   detail (a record narrating the asked event states the detail as its
   content). Never bridge it through a synonym, a broader category, or
   world knowledge: "won first place" does NOT establish "a trophy",
   "dance studio" does NOT establish "a store".

Return ONLY JSON:
{"atoms": [{"part": "...", "role": "who" | "event" | "detail",
            "record": <record number or null>,
            "quote": "<record words or empty>",
            "answer_detail": "<detail atoms only: the exact noun
              phrase the bound record supplies as the detail, in the
              record's own words; empty if it supplies none>"}],
 "verdict": "SUPPORTED" | "SPLICED" | "ABSENT"}
- SUPPORTED: every atomic part binds to a single record.
- SPLICED: the parts exist only spread across different records or
  different people.
- ABSENT: at least one part has no record at all."""


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


def _numbered_records(model, keys: list[str]) -> tuple[str, dict]:
    """One numbered record per edge — the unit premise atoms bind to.

    Returns (listing text, n -> record text)."""
    hist = model.export()["asset"].get("hist", {})
    lines, records, n = [], {}, 0
    for key in keys:
        for e in hist.get(key, []):
            val, day, kind = e[0], e[1], e[2]
            n += 1
            tag = "" if kind in ("statement", "update") else f"[{kind}]"
            lines.append(f"R{n} [{_label(key)}]: {val} @{_iso(day)}{tag}")
            records[n] = f"{_label(key)}: {val}"
    return (("\n".join(lines) if lines else "(no records)"), records)


_PV_ABSTRACT = {
    "setback", "reason", "way", "type", "kind", "thing", "something",
    "anything", "everything", "detail", "aspect", "category", "genre",
    "instrument", "what", "how", "when", "where", "who", "event",
    "experience", "moment", "activity", "stuff", "object", "item",
    "plan", "process", "status", "progress", "feeling", "opinion",
    "preference", "answer", "result", "outcome", "effect", "impact",
    "issue", "problem", "topic", "subject", "role", "part", "area",
    "field", "sort", "person", "people", "someone", "somebody",
    "recent", "latest", "current", "first", "last", "best", "most",
    "main", "own", "new", "old", "long", "much", "many",
}


def _stem(t: str) -> str:
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    for suf in ("es", "s"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)]
    return t


def _in_record(word: str, words: set) -> bool:
    s = _stem(word)
    if len(s) < 3:
        return True
    return any(w == s or (len(w) >= 3 and
                          (w.startswith(s) or s.startswith(w)))
               for w in words)


def _pv_gate(verify: dict, records: dict) -> dict:
    """Deterministic detail gate on top of the verifier's verdict.

    Two hard checks the LLM verdict is not trusted with:
    - an event atom and a detail atom bound to DIFFERENT records is a
      splice, whatever the verifier concluded;
    - a detail atom's claimed answer_detail must literally (word-form)
      appear inside its bound record's text — abstract question-type
      words ("setback", "instrument", "reason") are skipped since a
      record narrating the event already carries their content.
    """
    atoms = verify.get("atoms") or []
    rec_words = {}
    for n, text in records.items():
        rec_words[n] = {re.sub(r"[^a-z']", "", w)
                        for w in text.lower().split()}
    def owner(n):
        return str(records.get(n, "")).split("·")[0].split(":")[0]
    bound = {(a.get("record"), owner(a.get("record"))) for a in atoms
             if isinstance(a, dict) and a.get("record")
             and a.get("role") in ("event", "detail")}
    bound = {b for b in bound if b[0] is not None}
    owners = {o for _, o in bound}
    if len(owners) > 1 and verify.get("verdict") == "SUPPORTED":
        verify["verdict"] = "SPLICED"
        verify["gate"] = "atoms-across-owners"
    for a in atoms:
        if not isinstance(a, dict):
            continue
        if a.get("role") != "detail" or not a.get("record"):
            continue
        det = str(a.get("answer_detail") or "").strip().lower()
        toks = [re.sub(r"[^a-z']", "", t) for t in det.split()]
        toks = [t for t in toks
                if len(t) >= 3 and t not in _PV_ABSTRACT]
        if not toks:
            continue
        if all(_in_record(t, rec_words.get(a["record"], set()))
               for t in toks):
            continue
        hit = next((n for n, ws in rec_words.items()
                    if all(_in_record(t, ws) for t in toks)), None)
        if hit is not None:
            a["record"], a["gate"] = hit, "rebound"
        else:
            a["record"], a["gate"] = None, "detail-not-in-record"
            verify["verdict"] = "ABSENT"
    return verify


async def _pverify(llm, question: str, qdate: str, listing: str,
                   records: dict) -> dict:
    """Bind the question's premise atoms to single records, then run
    the deterministic detail gate."""
    prompt = (f"Today: {qdate}\n\nMEMORY RECORDS:\n{listing}\n\n"
              f"QUESTION: {question}\n\nVerify the premise. JSON:")
    t = await llm.complete(PVERIFY_SYS, prompt)
    i, j = t.find("{"), t.rfind("}")
    data = {}
    if i >= 0 and j > i:
        try:
            data = json.loads(t[i:j + 1])
        except Exception:
            data = {}
    verify = {"atoms": data.get("atoms") or [],
              "verdict": str(data.get("verdict", "")).strip().upper()}
    return _pv_gate(verify, records)


def _pv_abstain(verify: dict) -> str:
    atoms = verify.get("atoms") or []
    found = [a["part"] for a in atoms
             if isinstance(a, dict) and a.get("record") and a.get("part")]
    missing = [a["part"] for a in atoms
               if isinstance(a, dict) and not a.get("record")
               and a.get("part")]
    if verify.get("verdict") == "SPLICED" and found:
        return ("Memory records the parts of that claim separately — "
                + "; ".join(found)
                + " — but no record combines them, so it does not "
                  "answer the question.")
    if missing:
        return ("Memory has no record of " + "; ".join(missing)
                + ", so it does not answer the question.")
    return "Memory does not contain the presupposed fact, so it does not answer the question."


async def aanswer(model, llm, question: str, qdate: str,
                  premise_check: bool = False) -> dict:
    """Two-stage answer. Returns {response, selected_vertices, digest}.

    premise_check inserts a verification stage between retrieval and
    answering for adversarial / composite-premise questions: the
    question's presupposed atoms must each bind to ONE single record —
    a premise assembled across records (spliced) or absent from memory
    yields an explicit abstention instead of a bridged answer.
    """
    keys = await aretrieve(model, llm, question, qdate)
    dg = render_vertices(model, keys)
    verify = None
    if premise_check:
        listing, records = _numbered_records(model, keys)
        verify = await _pverify(llm, question, qdate, listing, records)
        if verify["verdict"] in ("SPLICED", "ABSENT"):
            return {"response": _pv_abstain(verify), "selected": keys,
                    "digest": dg, "verify": verify}
    prompt = (f"Today's date: {qdate}\n\nMEMORY:\n{dg}\n\n"
              f"QUESTION: {question}\n\nAnswer:")
    resp = (await llm.complete(ANSWER_SYS, prompt)).strip()
    return {"response": resp, "selected": keys, "digest": dg,
            "verify": verify}


def answer(model, llm, question: str, qdate: str) -> str:
    return asyncio.run(aanswer(model, llm, question, qdate))["response"]
