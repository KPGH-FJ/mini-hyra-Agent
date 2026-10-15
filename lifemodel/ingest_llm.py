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
- SELF-CONTAINED RECORDS: every record must stand alone — named
  subject + complete fact + temporal anchor inline. Never emit bare
  values ("5 days", "peace lily", "last month") without their
  referent; resolve pronouns in the value to the named referent. Keep
  dates and durations inside the fact record, never split them into a
  separate vertex; acquisition/state-change facts keep {item + action
  + source + date} in one record. `about` names a PERSON or is null —
  never a topic noun.
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

YIELD_SYS = """You extract the ASSISTANT side of a chat session that a
previous pass already covered for the user. Capture ONLY the
assistant's substantive contributions — things it produced,
recommended, suggested, designed, explained, or stated about itself.
Each record: {"slot": short_snake_name, "value": the content —
verifiable details, named entities, numbers, quoted phrases —
"about": whom it concerns (null if the assistant itself), "kind":
"statement", "source": "assistant", "text": "<=160 char quote or
summary"}.
Decompose artifacts (tables, plans, lists, drafts) row by row — one
record per row/item. Keep quotable phrases verbatim inside value.
Return ONLY a JSON array of records."""

VERIFY_SYS = """You audit extraction completeness for a chat session.
You get the session and the records already extracted from it. Re-read
the session line by line and emit ONLY records for facts that are NOT
yet captured: skipped attributes, entities, numbers, quoted phrases,
process/step descriptions, image descriptions, and assistant-produced
content (recommendations, artifact rows, advice).
Each record: {"slot": short_snake_name, "value": the content,
"about": whom it concerns, "kind": "statement", "source": who said
it, "text": "<=160 char quote or summary"}.
Do NOT re-emit anything already extracted. Return ONLY a JSON array of
the MISSED records (empty array if nothing was missed)."""

TYPED_SYS = """You type memory records for a personal memory system. Each input
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
 "verb": "snake_case" — normalized predicate, chosen from the
   CANONICAL frame the user would search by, not the outcome or
   surface phrasing: visiting a professional/person -> visit
   (NOT diagnose/schedule); using a service or product -> use
   (NOT eat/find); a trip staying outdoors -> camp; making
   bread/cake/cookies -> bake (NOT try/experiment); eating a
   meal -> eat; viewing a property -> view; buying -> buy;
   exchanging -> exchange; lending -> lent. Other verbs allowed
   when no canonical frame fits,
 "object": short noun phrase — the ENTITY the verb acts on: the
   person visited, service used, place stayed at, item made —
   NEVER the topic/condition/outcome (for "saw the ENT about
   sinusitis" object = "ENT specialist", not the condition; for
   "ordered Domino's" object = the service, not the food),
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
 "counterparty": person/org name — REQUIRED whenever the record
   involves a named person, professional or organization
   ("Dr. Patel", "ENT specialist", "Zara"); null only when the
   record involves no one but the user,
 "location": place name or null}.

Rules:
- one output object per input record, same order; rids echoed verbatim
- unknown/unstated fields are null — never invent
- "planned" facts keep the planned date in when_abs, not the mention day
- records carrying obligation_status are asserted STATES (the
  obligation exists now): kind=asserted, not planned — even if
  fulfillment lies in the future
- when the value text states a date-like event time — including
  parenthesized `(on ...)` annotations — when_abs MUST be set to it
  (loose anchors keep verbatim granularity, never left null)
- Return ONLY the JSON array."""

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

    def __init__(self, llm, day_of=None, audit=False,
                 yield_guard=True, verify=True, typed=False):
        self.llm = llm
        # day_of(date_or_label) -> int day; default = caller supplies ints
        self.day_of = day_of or (lambda d: int(d))
        # audit=True adds a per-session attribution re-check pass
        # (+1 LLM call/session; named-person chats only)
        self.audit = audit
        # yield_guard rescues the silent whole-side loss: a session that
        # HAS assistant turns but produced zero assistant-sourced records
        # gets one focused re-extract (+1 call, only when it fires).
        self.yield_guard = yield_guard
        # verify adds a per-session completeness audit (+1 call/session):
        # single-round extraction stochastically drops ~40-75% of
        # extractable facts, and the misses correlate across resamples —
        # a directed "what did you miss" pass beats re-sampling
        # (ss-assist lesions: .96 vs .88 union / .80 flat, lab-verified).
        self.verify = verify
        # typed=True adds a canonical-frame annotation pass per session
        # (chunks of 20 records/call): every record gains a `typed`
        # dict (verb/object/when_abs/kind/quantity/...) that the store
        # persists rid-keyed — the typed-record layer enabling
        # deterministic enumeration at read. Lab-validated chain:
        # oracle fields 5/5 -> canonical frame 4/7 -> spec-verify 7/7.
        self.typed = typed
        self.n_extracted = 0
        # telemetry: guard/verify fire rates feed cost calibration
        self.stats = {"sessions": 0, "empty_retries": 0,
                      "yield_guard_fires": 0, "yield_recs": 0,
                      "verify_fires": 0, "verify_recs": 0,
                      "typed_recs": 0}

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
        self.stats["sessions"] += 1
        if not recs and len(body) > 500:
            self.stats["empty_retries"] += 1
            nudge = ("\n\nYou returned an empty array before. Re-read the "
                     "session carefully — there IS personal information "
                     "here. List every fact, preference, plan, event, or "
                     "assistant artifact, one record each.")
            text = await self.llm.complete(
                EXTRACT_SYS,
                prompt[:-len("Records JSON array:")]
                + nudge + "\n\nRecords JSON array:")
            recs = _json_list(text)
        if self.yield_guard and recs:
            asst_chars = sum(len(t["content"]) for t in turns
                             if t.get("role") == "assistant")
            asst_recs = [r for r in recs if isinstance(r, dict)
                         and str(r.get("source", "")).strip().lower()
                         == "assistant"]
            if asst_chars >= 200 and not asst_recs:
                extra = [r for r in _json_list(
                    await self.llm.complete(
                        YIELD_SYS,
                        f"Session date: {date_label}\n\n{body}\n\n"
                        "Assistant items JSON array:"))
                    if isinstance(r, dict)]
                self.stats["yield_guard_fires"] += 1
                self.stats["yield_recs"] += len(extra)
                recs = recs + extra
        if self.verify and recs:
            missed = [r for r in _json_list(
                await self.llm.complete(
                    VERIFY_SYS,
                    f"Session date: {date_label}\n\nSESSION:\n{body}\n\n"
                    "ALREADY EXTRACTED:\n"
                    + json.dumps(recs, ensure_ascii=False)
                    + "\n\nMissed records JSON array:"))
                if isinstance(r, dict)]
            if missed:
                self.stats["verify_fires"] += 1
                self.stats["verify_recs"] += len(missed)
                recs = recs + missed
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
        if self.typed and out:
            await self._atype_fields(out)
            self.stats["typed_recs"] += sum(
                1 for r in out if r.get("typed"))
        if self.audit and out:
            out = await self._aaudit(turns, out, ents)
        return out

    async def _atype_fields(self, recs: list, chunk: int = 20) -> None:
        """Canonical-frame typing pass: annotate each record with typed
        fields in-place. Rids the pass drops get one focused retry;
        still-missing records simply carry no `typed` key (absence =
        untyped, never guess)."""
        items = [{"rid": r["id"], "slot": r["slot"], "kind": r["kind"],
                  "day": r["day"], "value": r["value"]} for r in recs]
        got = {}
        for i in range(0, len(items), chunk):
            part = items[i:i + chunk]
            prompt = ("RECORDS:\n" + json.dumps(part, ensure_ascii=False)
                      + "\n\nTyped fields JSON array:")
            for o in _json_list(await self.llm.complete(TYPED_SYS, prompt)):
                if isinstance(o, dict) and o.get("rid"):
                    rid = str(o.pop("rid"))
                    got[rid] = o
            missing = [it for it in part if it["rid"] not in got]
            if missing:
                prompt = ("RECORDS:\n" + json.dumps(missing,
                                                  ensure_ascii=False)
                          + "\n\nTyped fields JSON array:")
                for o in _json_list(
                        await self.llm.complete(TYPED_SYS, prompt)):
                    if isinstance(o, dict) and o.get("rid"):
                        rid = str(o.pop("rid"))
                        got[rid] = o
        for r in recs:
            t = got.get(r["id"])
            if t:
                r["typed"] = t

    def extract(self, date_label, turns: list, model=None) -> list:
        return asyncio.run(self.aextract(date_label, turns, model))

    async def aingest_session(self, model, date_label, turns: list) -> int:
        """Extract and ingest one session; returns record count."""
        recs = await self.aextract(date_label, turns, model)
        for r in recs:
            model.ingest(r)
        return len(recs)
