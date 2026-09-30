"""M1 LLM ingest frontend — pluggable implementation.

Real-world lifemodel input is unstructured (chat turns, diary, notes),
not schema-conformant records. This module is the bridge: an LLM
extracts records per session, and the frontend enforces
*canonicalization* — new facts reuse existing slot/entity names rather
than minting near-duplicate vertices.

Two mechanisms, both first-class:

1. Catalog reuse: every extraction call receives the store's current
   slot names; the LLM must reuse them when a fact fits.
2. Local canonicalization: a returned slot is normalized (lowercase,
   snake) and, when it is a near-duplicate of a catalog entry (token
   overlap >= THRESH), folded to the canonical name before ingest.

`about` entity names get the same treatment: near-duplicate entity
names fold to the canonical form so the store's person-alias layer can
keep one vertex per entity.
"""
from __future__ import annotations

import asyncio
import json
import re

EXTRACT_SYS = """You extract memory records from a chat session — either between a
user and an AI assistant, or between named people whose speaker names
prefix each utterance line as `Name:`. Extract EVERY piece of personal
information the speakers reveal: facts, events, preferences, plans,
possessions, relationships, experiences, opinions, problems they
mention.
Output a JSON array of records:
{"slot": "snake_case_topic", "value": "what was said",
 "about": null or "person name", "kind": "statement",
 "source": "self", "text": "supporting quote <=20 words"}
- about=null means the fact is about the user (or about the utterance's
  own speaker in a named-person chat); about="name" for facts about
  other people; things a speaker relays that others said ->
  kind="hearsay".
- SPEAKER BINDING: when utterance lines carry a `Name:` speaker prefix
  — a chat between named people, no AI assistant exists there; the
  prefix may also sit inside an outer role tag like `USER: Name: ...`
  — bind each record to the real name: source="<that name, lowercase>"
  and about=null for the speaker themself, about="<person name>" for
  facts about someone else. Never collapse named speakers into
  source="self"/"user"/"assistant" — generic labels destroy
  attribution downstream.
- ASSISTANT turns (only when the session actually has an assistant
  side): also record the SUBSTANTIVE CONTENT the assistant
  produced — names it invented, lists/tables/texts it generated,
  recommendations it gave -> source="assistant", kind="statement",
  about=null.
  CRITICAL: decompose assistant artifacts into their CONTENT, row by
  row. A generated table/schedule/list is NOT one record "created a
  sheet" — each cell assignment is its own record:
  slot "rotation_admon_sunday", value "8am-4pm", source="assistant".
  The user later asks about the content, not the artifact's existence.
- kind="update" if it changes an earlier statement; "correction" /
  "retraction" for taking something back; "suggestion" for advice.
- EVENT DATES: when the utterance says WHEN something happened or will
  happen, append it to the value as ` (on <date>)`. Resolve to
  YYYY-MM-DD against the session date when a single day is identified
  ("last Tuesday", "May 7th"); when the stated time is fuzzy or
  relative to another event ("June 2023", "the week before my talk",
  "next month"), keep it VERBATIM, e.g. ` (on June 2023)` — never drop
  it and never invent a day. This is the event's own date, distinct
  from the session date. Only append when a date is actually stated.
- Keep slot names consistent; reuse names from the existing slot list
  when one covers the fact.
Extract liberally — even small details count. Empty array only if truly
nothing personal is said. Return ONLY the JSON array."""

MERGE_SYS = """You are the canonicalization stage of a memory ingestor.
Stage 1 produced NEW slot names for one session; the store already has
a CATALOG of existing slot names. Map each new name to an existing
catalog name when they denote the same attribute/fact, or keep the new
name when nothing fits. Merge aggressively across synonyms and phrasing
variants (car_gps_issue -> car_problem), but do not merge distinct
attributes. Return ONLY a JSON object {new_name: canonical_name}."""

AUDIT_SYS = """You audit extracted memory records for speaker
attribution. The session is a chat between named people; each
utterance line is prefixed `Name:` with the speaker's real name.
You get the session and a JSON array of records. Every record has
"source" (who was credited), "about" (who the fact concerns), and
"text" (a supporting quote). Generic sources like "self", "user" and
"assistant" mean the extractor did not name the speaker.
For EVERY record: locate the utterance its text/value came from and set
source = that speaker's lowercase first name. Set about=null when the
fact is about the speaker themself, or about="<person name>" when it
concerns someone else. Fix kind="hearsay" when a speaker relays a third
party's words. Do NOT add or drop records and do NOT change
slot/value/text — fix attribution only. Keep the array order.
Return ONLY the corrected JSON array of records."""

_SLOT_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set:
    return set(_SLOT_TOKEN_RE.findall(str(s).lower()))


def _canon(slot: str, catalog: list[str], thresh: float = 0.5) -> str:
    """Fold a candidate slot onto an existing catalog name when the
    token overlap is high enough. Returns the (possibly new) name."""
    slot = re.sub(r"\W+", "_", str(slot).strip().lower()).strip("_")[:60]
    if not slot:
        return slot
    if slot in catalog:
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


def _json_list(text: str):
    t = text.strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else [v]
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", t, re.S)
    if m:
        try:
            v = json.loads(m.group(1))
            return v if isinstance(v, list) else []
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


class LLMIngestor:
    """Async LLM-driven ingestor for a LifeModel.

    llm: any object with `async complete(system, prompt) -> str`
    (hyra.llm.OpenAICompatLLM, GLMCompat, ...).
    """

    def __init__(self, llm, day_of=None, audit=False):
        self.llm = llm
        # day_of(date_or_label) -> int day; default = caller supplies ints
        self.day_of = day_of or (lambda d: int(d))
        # audit=True adds a per-session attribution re-check pass
        # (+1 LLM call/session; named-person chats only)
        self.audit = audit
        self.n_extracted = 0

    async def _aaudit(self, turns: list, recs: list, ents: list) -> list:
        """Re-align every record's source/about to the named utterance
        speaker. On shape loss or error the unaudited records are kept."""
        body = "\n".join(t["content"] for t in turns)
        prompt = ("SESSION:\n" + body + "\n\nRECORDS:\n"
                  + json.dumps(
                      [{k: r[k] for k in
                        ("slot", "value", "about", "kind", "source",
                         "text")} for r in recs], ensure_ascii=False)
                  + "\n\nCorrected records JSON array:")
        try:
            fixed = _json_list(
                await self.llm.complete(AUDIT_SYS, prompt))
        except Exception:
            return recs
        if len(fixed) != len(recs):
            return recs
        for r, f in zip(recs, fixed):
            if not isinstance(f, dict):
                continue
            src = str(f.get("source", r["source"])).strip().lower()
            if src:
                r["source"] = src
            ab = f.get("about", r.get("about"))
            r["about"] = (_canon(str(ab), ents, thresh=0.4)
                          if ab else None)
        return recs

    def catalog(self, model) -> list[str]:
        """Existing slot names the extractor should reuse."""
        hist = model.export()["asset"].get("hist", {})
        return sorted({k.split("|")[-1] for k in hist})

    def entity_catalog(self, model) -> list[str]:
        hist = model.export()["asset"].get("hist", {})
        return sorted({k.split("|")[1] for k in hist
                       if k.count("|") == 2})

    async def _amerge_slots(self, new_slots: list[str],
                            catalog: list[str]) -> dict:
        """Stage-2 merge: LLM maps the session's fresh slot names onto
        the catalog. Beats per-call forced reuse because the merge sees
        the whole session's new names at once (variant ablation:
        +4pp over single-call reuse)."""
        new_slots = [s for s in dict.fromkeys(new_slots) if s]
        if not new_slots or not catalog:
            return {}
        prompt = ("CATALOG:\n" + ", ".join(catalog[:400])
                  + "\n\nNEW NAMES:\n" + ", ".join(new_slots)
                  + "\n\nMapping JSON object:")
        text = await self.llm.complete(MERGE_SYS, prompt)
        t = text.strip()
        i, j = t.find("{"), t.rfind("}")
        m = {}
        if i >= 0 and j > i:
            try:
                v = json.loads(t[i:j + 1])
                if isinstance(v, dict):
                    m = {str(k): str(vv) for k, vv in v.items()}
            except Exception:
                pass
        return {k: v for k, v in m.items() if v in catalog}

    async def aextract(self, date_label, turns: list, model=None,
                       twostage: bool = True) -> list:
        """turns: [{role, content}] -> normalized record dicts."""
        body = "\n".join(
            ("USER" if t["role"] == "user" else "ASSISTANT")
            + ": " + t["content"] for t in turns)
        catalog = self.catalog(model) if model is not None else []
        known = ""
        if catalog and not twostage:
            known = ("\n\nExisting slot names (REUSE one verbatim "
                     "when it covers the fact; invent a new name "
                     "only when none fits):\n"
                     + ", ".join(catalog[:400]))
        prompt = (f"Session date: {date_label}\n{known}\n\n{body}\n\n"
                  "Records JSON array:")
        text = await self.llm.complete(EXTRACT_SYS, prompt)
        recs = _json_list(text)
        # A substantive session yielding zero records is almost always a
        # transient extraction failure, not an empty session — retry once
        # with an explicit nudge.
        if not recs and len(body) > 500:
            nudge = ("\n\nYou returned an empty array before. Re-read the "
                     "session carefully — there IS personal information "
                     "here. List every fact, preference, plan, event, or "
                     "assistant artifact, one record each.")
            text = await self.llm.complete(
                EXTRACT_SYS,
                prompt[:-len("Records JSON array:")]
                + nudge + "\n\nRecords JSON array:")
            recs = _json_list(text)
        day = self.day_of(date_label)
        ents = self.entity_catalog(model) if model is not None else []
        raw_slots = [r["slot"] for r in recs
                     if isinstance(r, dict) and r.get("slot")]
        merge = (await self._amerge_slots(raw_slots, catalog)
                 if twostage else {})
        out = []
        for i, r in enumerate(recs):
            if not isinstance(r, dict) or not r.get("slot"):
                continue
            about = r.get("about")
            if about:
                about = _canon(str(about), ents, thresh=0.4)
            raw = str(r["slot"])
            slot = merge.get(raw) or _canon(raw, catalog)
            out.append({
                "id": f"llm_{day}_{i}_{self.n_extracted}",
                "day": day,
                "source": r.get("source", "self"),
                "kind": r.get("kind", "statement"),
                "slot": slot,
                "value": r.get("value"),
                "about": about,
                "text": str(r.get("text", ""))[:200],
            })
            self.n_extracted += 1
        if self.audit and out:
            out = await self._aaudit(turns, out, ents)
        return out

    def extract(self, date_label, turns: list, model=None) -> list:
        return asyncio.run(self.aextract(date_label, turns, model))

    async def aingest_session(self, model, date_label, turns: list) -> int:
        """Extract and ingest one session; returns record count."""
        recs = await self.aextract(date_label, turns, model)
        for r in recs:
            model.ingest(r)
        return len(recs)
