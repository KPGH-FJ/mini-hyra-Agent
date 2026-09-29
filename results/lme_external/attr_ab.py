#!/usr/bin/env python3
"""Attribution-fix ablation — named-persona speaker binding at ingest.

Root cause found in the expanded-adversarial round: LoCoMo renders
two-person chats with every turn role="user" while EXTRACT_SYS frames
the session as user-vs-AI-assistant. Both speakers' self-reports land
under generic `user·`/`assistant·` labels, so the reader-side SUBJECT
CHECK cannot see swaps the labels already lied about.

Arm 'bind': EXTRACT_SYS replaced by BIND_SYS — speaker-name binding
(source=<Name: prefix's name>, about=null = the speaker themself;
generic labels forbidden) and the body rendered as bare `Name: text`
lines instead of the stock `USER: Name: text` double prefix.

Arm 'audit': stock extract unchanged, then one extra LLM pass audits
each record's attribution against the utterance that supports it and
rebinds source/about to the named speaker.

Validation set: conv-0 all 47 cat5 vs the stock baseline 35/47=74.5%;
the 8 mislabel-driven misses (c0_q168-170, q186, q191, q194, q195,
q198) tracked per-qid, plus regression watch on the 35 correct.

Usage (per arm, all-Atria):
  python attr_ab.py --arm bind --data locomo10.json --convs 0 \
      --api-key $ATRIA_API_KEY --base-url ... --model Atria-Dawn-Preview
  python attr_ab.py --arm bind --judge ...same...
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adv_cov as A  # noqa: E402  (shared helpers + sys.path setup)

from lme import _make_llm                       # noqa: E402
from locomo import _day_of, normalize_turns, sessions  # noqa: E402
from lifemodel.model import LifeModel            # noqa: E402
from lifemodel.ingest_llm import LLMIngestor, _canon, _json_list  # noqa: E402
import lifemodel.ingest_llm as IL               # noqa: E402
import lifemodel.reader as R                    # noqa: E402

BIND_SYS = """You extract memory records from a chat between two named
people. Each utterance is prefixed `Name:` — that is the speaker's real
name. Extract EVERY piece of personal information either speaker
reveals: facts, events, preferences, plans, possessions, relationships,
experiences, opinions, problems they mention.
Output a JSON array of records:
{"slot": "snake_case_topic", "value": "what was said",
 "about": null or "person name", "kind": "statement",
 "source": "speaker name", "text": "supporting quote <=20 words"}
- SPEAKER BINDING (critical): source = the lowercase first name of the
  person who uttered the line — copy it from the `Name:` prefix.
  about=null when the fact is about the speaker themself;
  about="<person name>" when it concerns someone else. NEVER emit
  source="self", "user" or "assistant" — there is no AI assistant here;
  generic labels destroy attribution.
- things a speaker relays that a third party said/did -> kind="hearsay",
  about="<that third party>".
- kind="update" if it changes an earlier statement; "correction" /
  "retraction" for taking something back; "suggestion" for advice.
- EVENT DATES: when the utterance says WHEN something happened or will
  happen, append it to the value as ` (on <date>)`. Resolve to
  YYYY-MM-DD against the session date when a single day is identified;
  when the stated time is fuzzy or relative to another event ("June
  2023", "the week before my talk"), keep it VERBATIM — never drop it
  and never invent a day. Only append when a date is actually stated.
- Keep slot names consistent; reuse names from the existing slot list
  when one covers the fact.
Extract liberally — even small details count. Empty array only if truly
nothing personal is said. Return ONLY the JSON array."""

AUDIT_SYS = """You audit extracted memory records for speaker
attribution. The session is a chat between two named people; each
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


class BindIngestor(LLMIngestor):
    """Arm (a): named-speaker binding in the extract prompt; body
    rendered as bare `Name: text` lines."""

    async def aextract(self, date_label, turns: list, model=None,
                       twostage: bool = True) -> list:
        body = "\n".join(t["content"] for t in turns)  # "Name: text"
        catalog = self.catalog(model) if model is not None else []
        known = ""
        if catalog and not twostage:
            known = ("\n\nExisting slot names (REUSE one verbatim "
                     "when it covers the fact; invent a new name "
                     "only when none fits):\n"
                     + ", ".join(catalog[:400]))
        prompt = (f"Session date: {date_label}\n{known}\n\n{body}\n\n"
                  "Records JSON array:")
        text = await self.llm.complete(BIND_SYS, prompt)
        recs = _json_list(text)
        if not recs and len(body) > 500:
            nudge = ("\n\nYou returned an empty array before. Re-read "
                     "the session carefully — there IS personal "
                     "information here. List every fact, preference, "
                     "plan, event, or artifact, one record each.")
            text = await self.llm.complete(
                BIND_SYS, prompt[:-len("Records JSON array:")]
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
            src = str(r.get("source", "")).strip().lower() or "self"
            out.append({
                "id": f"llm_{day}_{i}_{self.n_extracted}",
                "day": day,
                "source": src,
                "kind": r.get("kind", "statement"),
                "slot": slot,
                "value": r.get("value"),
                "about": about,
                "text": str(r.get("text", ""))[:200],
            })
            self.n_extracted += 1
        return out


class AuditIngestor(LLMIngestor):
    """Arm (b): stock extract, then an audit pass rebinds attribution."""

    async def aextract(self, date_label, turns: list, model=None,
                       twostage: bool = True) -> list:
        recs = await super().aextract(date_label, turns, model,
                                      twostage)
        if not recs:
            return recs
        body = "\n".join(t["content"] for t in turns)
        prompt = ("SESSION:\n" + body + "\n\nRECORDS:\n"
                  + json.dumps(
                      [{k: r[k] for k in
                        ("slot", "value", "about", "kind", "source",
                         "text")} for r in recs], ensure_ascii=False)
                  + "\n\nCorrected records JSON array:")
        try:
            text = await self.llm.complete(AUDIT_SYS, prompt)
            fixed = _json_list(text)
        except Exception:
            fixed = []
        if len(fixed) != len(recs):          # audit shape lost -> keep
            return recs
        ents = self.entity_catalog(model) if model is not None else []
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


async def get_model(conv, ci, arm, llm, out_dir, timeout=600):
    """Same checkpointing pattern as adv_cov.get_model, per-arm cache."""
    cache = os.path.join(out_dir, f"attr_{arm}_c{ci}_atria.json")
    prog_path = os.path.join(out_dir, f"attr_{arm}_c{ci}_progress.json")
    prog = {"done": [], "failed": [], "partial": []}
    m = LifeModel()
    if os.path.exists(cache) and os.path.exists(prog_path):
        m.import_state(json.load(open(cache)))
        prog = json.load(open(prog_path))
        print(f"attr {arm} conv{ci}: resume, {len(prog['done'])} done",
              file=sys.stderr)
    ing_cls = BindIngestor if arm == "bind" else AuditIngestor
    ing = ing_cls(llm, day_of=_day_of)
    nrec = 0
    for date, sess in sessions(conv["conversation"]):
        if date in prog["done"] or date in prog["failed"]:
            continue
        turns = normalize_turns(sess)
        print(f"attr {arm} conv{ci} session {date} ({len(turns)} turns)",
              file=sys.stderr)
        try:
            got = await asyncio.wait_for(
                ing.aingest_session(m, date, turns), timeout)
        except Exception as e:
            print(f"session {date} attempt1 fail: {e}", file=sys.stderr)
            try:
                got = await asyncio.wait_for(
                    ing.aingest_session(
                        m, date,
                        turns[: max(len(turns) // 2, 1)]), timeout)
                prog["partial"].append(date)
                print(f"session {date}: partial", file=sys.stderr)
            except Exception as e2:
                print(f"session {date} INGEST-FAILED: {e2}",
                      file=sys.stderr)
                prog["failed"].append(date)
                json.dump(prog, open(prog_path, "w"))
                continue
        prog["done"].append(date)
        nrec += got
        print(f"session {date}: +{got} records (total {nrec})",
              file=sys.stderr)
        json.dump(prog, open(prog_path, "w"))
        json.dump(m.export()["asset"], open(cache, "w"))
    print(f"attr {arm} conv{ci} ingest done: {nrec} records "
          f"({len(prog['done'])} ok, {len(prog['partial'])} partial, "
          f"{len(prog['failed'])} failed)", file=sys.stderr)
    return m


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["bind", "audit"])
    ap.add_argument("--data", required=True)
    ap.add_argument("--convs", default="0")
    ap.add_argument("--api-key", default=os.environ.get("API_KEY"))
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--out-dir",
                    default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    convs = json.load(open(args.data))
    cis = [int(c) for c in args.convs.split(",")]

    if args.judge:
        jllm = _make_llm(args)
        for ci in cis:
            path = os.path.join(args.out_dir,
                                f"attr_{args.arm}_c{ci}.jsonl")
            rows, correct = [], 0
            for line in open(path):
                h = json.loads(line)
                note = "" if h.get("gold") else A.ABS_NOTE
                p = A.JUDGE.format(q=h["question"], a=h.get("gold"),
                                   r=h["response"], abs_note=note)
                try:
                    v = (await jllm.complete(
                        "You are a strict grader.", p)).strip().lower()
                except Exception as e:
                    print("judge fail", h["qid"], e, file=sys.stderr)
                    v = "no"
                ok = v.startswith("yes")
                correct += ok
                rows.append({"qid": h["qid"], "correct": ok,
                             "response": h["response"]})
            out = {"conv": ci, "arm": args.arm, "n": len(rows),
                   "adv_acc": correct / max(len(rows), 1),
                   "rows": rows}
            mp = os.path.join(
                args.out_dir,
                f"attr_{args.arm}_c{ci}_metrics_atria.json")
            json.dump(out, open(mp, "w"), indent=2)
            print(f"{args.arm} c{ci} adv_acc {correct}/{len(rows)}",
                  flush=True)
        return

    llm = A._NudgedLLM(_make_llm(args))       # extract (+ terse nudge)
    llm_a = _make_llm(args, thinking=True)    # answer
    for ci in cis:
        conv = convs[ci]
        qset = A.cat5_qs(conv, ci)
        print(f"attr {args.arm} conv{ci}: {len(qset)} cat5 questions",
              file=sys.stderr)
        m = await get_model(conv, ci, args.arm, llm, args.out_dir)
        out_path = os.path.join(args.out_dir,
                                f"attr_{args.arm}_c{ci}.jsonl")
        done = set()
        if os.path.exists(out_path):
            for line in open(out_path):
                done.add(json.loads(line)["qid"])
        out = open(out_path, "a")
        for row in qset:
            if row["qid"] in done:
                continue
            try:
                resp = (await R.aanswer(
                    m, llm_a, row["question"],
                    "2023 (post-conversation)"))["response"]
            except Exception as e:
                resp = f"(error: {e})"
            out.write(json.dumps({**row, "response": resp},
                                 ensure_ascii=False) + "\n")
            out.flush()
            print(f"[{args.arm} c{ci}] {row['qid']} {resp[:70]!r}",
                  flush=True)
        out.close()


if __name__ == "__main__":
    asyncio.run(main())
