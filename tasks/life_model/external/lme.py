"""LongMemEval adapter for the lifemodel package.

Three-stage pipeline mirroring M1/M4 split:

  extract   per haystack session -> LLM -> records -> model.ingest()
  answer    model.export() digest -> LLM reader -> free-text response
  judge     official LongMemEval anscheck prompts -> yes/no per type

Usage:
    python lme.py run   --data oracle.json --n 10 --out hyp.jsonl
    python lme.py judge --hyp hyp.jsonl --ref oracle.json --out metrics.json
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
from hyra.llm import OpenAICompatLLM  # noqa: E402
from lifemodel.model import LifeModel  # noqa: E402


class GLMCompat:
    """OpenAI-compatible non-streamed client (GLM / OpenRouter / others).

    Non-streamed calls with thinking disabled — extraction prompts are
    small enough that streaming keepalive is unnecessary, and thinking
    would burn the token budget on hidden reasoning.
    """

    def __init__(self, model="glm-4.5-air",
                 base_url="https://open.bigmodel.cn/api/paas/v4",
                 api_key=None, max_tokens=4096, retries=6,
                 thinking=False, extra_body=None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("GLM_API_KEY", "")
        self.max_tokens = max_tokens
        self.retries = retries
        self.thinking = thinking
        self.extra_body = extra_body or {}
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0,
                      "calls": 0}

    async def complete(self, system: str, prompt: str) -> str:
        import urllib.request
        delay = 1.5
        last = None
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0.3,
            "stream": False,
            **self.extra_body,
        }).encode()
        for _ in range(self.retries):
            try:
                req = urllib.request.Request(
                    self.base_url + "/chat/completions", data=body,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {self.api_key}"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = json.loads(r.read())
                u = d.get("usage", {})
                self.usage["calls"] += 1
                self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
                self.usage["completion_tokens"] += u.get(
                    "completion_tokens", 0)
                return d["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: BLE001
                last = e
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
        raise last


def _make_llm(args, thinking=False, backend=None):
    """backend: 'glm' | 'openrouter' | None(atria/openai)."""
    backend = backend or ("glm" if getattr(args, "glm", False) else None)
    if backend == "glm":
        body = {"thinking": {"type": "enabled" if thinking
                            else "disabled"}}
        return GLMCompat(api_key=os.environ.get("GLM_API_KEY"),
                         extra_body=body)
    if backend == "openrouter":
        return GLMCompat(
            model=os.environ.get("OR_MODEL",
                                 "stealth/space-bunny-alpha"),
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OR_API_KEY", ""),
            max_tokens=8192)
    return OpenAICompatLLM(model=args.model, base_url=args.base_url,
                           api_key=args.api_key, max_tokens=8192)


# ---------- date helpers ---------------------------------------------------

def _parse_date(s: str) -> _dt.date:
    # "2023/04/10 (Mon) 23:07"
    return _dt.datetime.strptime(s.split(" (")[0], "%Y/%m/%d").date()


def _ordinal(s: str) -> int:
    return _parse_date(s).toordinal()


def _iso(ordinal: int) -> str:
    return _dt.date.fromordinal(int(ordinal)).isoformat()


# ---------- M1: LLM extraction frontend ------------------------------------

EXTRACT_SYS = """You extract memory records from a chat session between a user
and an AI assistant. Extract EVERY piece of personal information the user
reveals: facts, events, preferences, plans, possessions, relationships,
experiences, opinions, problems they mention.
Output a JSON array of records:
{"slot": "snake_case_topic", "value": "what was said",
 "about": null or "person name", "kind": "statement",
 "source": "self", "text": "supporting quote <=20 words"}
- about=null means the fact is about the user; about="name" for facts
  about other people; things others said that the user relays ->
  kind="hearsay".
- ASSISTANT turns: also record the SUBSTANTIVE CONTENT the assistant
  produced — names it invented, lists/tables/texts it generated,
  recommendations it gave, decisions it made -> source="assistant",
  kind="statement", about=null, slot naming the artifact
  (e.g. "assistant_shift_sheet", "assistant_story_detail").
  The user may later ask what the assistant said/created.
- kind="update" if it changes an earlier statement; "correction" /
  "retraction" for taking something back; "suggestion" for advice the
  user received from the assistant.
- Keep slot names consistent across the session (e.g. "car", "job",
  "allergy"). Values short and canonical.
Extract liberally — even small details count. Empty array only if truly
nothing personal is said. Return ONLY the JSON array."""


async def _ask(llm: OpenAICompatLLM, system: str, prompt: str) -> str:
    return await llm.complete(system, prompt)


def extract_session(llm, date_str: str, turns: list,
                    known_slots: list = None) -> list:
    body = []
    for t in turns:
        role = "USER" if t["role"] == "user" else "ASSISTANT"
        body.append(f"{role}: {t['content']}")
    known = ""
    if known_slots:
        known = ("\n\nExisting slot names (REUSE one of these verbatim "
                 "when it covers the fact; invent a new name only when "
                 "none fits):\n" + ", ".join(sorted(known_slots)[:400]))
    prompt = (f"Session date: {date_str}\n{known}\n\n"
              + "\n".join(body) + "\n\nRecords JSON array:")
    text = asyncio.run(_ask(llm, EXTRACT_SYS, prompt))
    recs = _json_list(text)
    day = _ordinal(date_str)
    out = []
    for i, r in enumerate(recs):
        if not isinstance(r, dict) or not r.get("slot"):
            continue
        out.append({
            "id": f"lme_{day}_{i}",
            "day": day,
            "source": r.get("source", "self"),
            "kind": r.get("kind", "statement"),
            "slot": str(r["slot"])[:60],
            "value": r.get("value"),
            "about": r.get("about"),
            "text": str(r.get("text", ""))[:200],
        })
    return out


def _json_list(text: str):
    """Tolerant JSON array extraction (fences / prose)."""
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


# ---------- M4: LLM reader over exported asset -----------------------------

def digest(model: LifeModel, now_ord: int) -> str:
    """Render the store's history map as an annotated text digest.

    Keys are 'src|slot' (self claims) or 'src|about|slot' (claims about
    an entity) — group entity claims under the entity name so the reader
    sees one block per subject regardless of who said it.
    """
    asset = model.export()["asset"]
    hist = asset.get("hist", {})
    lines = []
    for key, edges in sorted(hist.items()):
        parts_k = key.split("|")
        if len(parts_k) == 3:
            src, about, slot = parts_k
            who = f"{about} (per {src})"
        else:
            src, slot = parts_k
            who = "user" if src == "self" else src
        parts = []
        for e in edges:
            val, day, kind = e[0], e[1], e[2]
            tag = "" if kind in ("statement", "update") else f"[{kind}]"
            parts.append(f"{val} @{_iso(day)}{tag}")
        lines.append(f"- {who}·{slot}: " + " -> ".join(parts))
    for slot, d in sorted(asset.get("drv", {}).items()):
        if d.get("value") is not None:
            lines.append(f"- derived·{slot}: {d['value']}")
    return "\n".join(lines) if lines else "(memory empty)"


ANSWER_SYS = """You are an assistant with a long-term memory of the user.
Below is everything remembered: each line is an attribute with its value
history and the dates it was said. Tags: [correction] corrected, [retraction]
withdrawn, [hearsay] second-hand claim, [suggestion] someone suggested.

Answer the user's question using ONLY this memory.
- Resolve relative dates against today's date given below.
- If several values exist over time, the LATEST non-retracted one is current.
- Search the memory thoroughly: the answer may sit under a differently-
  named attribute (e.g. a car problem may be under car_gps_issue).
  Use the closest relevant entries.
- Entries shown as "X (per assistant)" or tagged [suggestion] are things
  the assistant or others said — you MAY still use them as answers.
- Abstain ONLY if no attribute is remotely relevant; then say exactly:
  "I don't have enough information to answer that."
- Answer concisely, no preamble."""


def answer_question(llm: OpenAICompatLLM, model: LifeModel, q: dict) -> str:
    now = _ordinal(q["question_date"])
    dg = digest(model, now)
    prompt = (f"Today's date: {_iso(now)} ({q['question_date']})\n\n"
              f"MEMORY:\n{dg}\n\nQUESTION: {q['question']}\n\nAnswer:")
    return asyncio.run(_ask(llm, ANSWER_SYS, prompt)).strip()


# ---------- judge (official anscheck prompts) -------------------------------

def _judge_prompt(qtype, question, answer, response, abstention):
    if abstention:
        return ("I will give you an unanswerable question, an explanation, "
                "and a response from a model. Please answer yes if the model "
                "correctly identifies the question as unanswerable. The model "
                "could say that the information is incomplete, or some other "
                "information is given but the asked information is not.\n\n"
                f"Question: {question}\n\nExplanation: {answer}\n\n"
                f"Model Response: {response}\n\nDoes the model correctly "
                "identify the question as unanswerable? Answer yes or no only.")
    if qtype == "temporal-reasoning":
        note = (" In addition, do not penalize off-by-one errors for the "
                "number of days.")
    elif qtype == "knowledge-update":
        note = (" If the response contains some previous information along "
                "with an updated answer, the response should be considered "
                "as correct as long as the updated answer is required.")
    elif qtype == "single-session-preference":
        return ("I will give you a question, a rubric for desired "
                "personalized response, and a response from a model. Please "
                "answer yes if the response satisfies the desired response. "
                "Otherwise, answer no. The model does not need to reflect "
                "all the points in the rubric. The response is correct as "
                "long as it recalls and utilizes the user's personal "
                "information correctly.\n\n"
                f"Question: {question}\n\nRubric: {answer}\n\n"
                f"Model Response: {response}\n\n"
                "Is the model response correct? Answer yes or no only.")
    else:
        note = ""
    return ("I will give you a question, a correct answer, and a response "
            "from a model. Please answer yes if the response contains the "
            "correct answer. Otherwise, answer no. If the response is "
            "equivalent to the correct answer or contains all the "
            "intermediate steps to get the correct answer, you should also "
            "answer yes. If the response only contains a subset of the "
            "information required by the answer, answer no." + note +
            f"\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\n"
            f"Model Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only.")


def judge_one(llm: OpenAICompatLLM, q: dict, response: str) -> bool:
    absn = q["question_id"].endswith("_abs")
    prompt = _judge_prompt(q["question_type"], q["question"],
                           q["answer"], response, absn)
    out = asyncio.run(_ask(llm, "You are a strict grader. "
                            "Reply yes or no only.", prompt)).strip().lower()
    return out.startswith("yes")


# ---------- run --------------------------------------------------------------

def run(args):
    data = json.load(open(args.data))
    llm = _make_llm(args)
    llm_answer = _make_llm(args, thinking=True)
    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            if line.strip():
                done.add(json.loads(line)["question_id"])
    fh = open(args.out, "a")
    n = 0
    counts = {}
    if args.per_type:
        data = [q for q in data
                if not q["question_id"].endswith("_abs")]
    for q in data:
        if args.per_type:
            if counts.get(q["question_type"], 0) >= args.per_type:
                continue
        elif n >= args.n:
            break
        if q["question_id"] in done:
            continue
        counts[q["question_type"]] = counts.get(q["question_type"], 0) + 1
        model = LifeModel()
        nrecs = 0
        for date, sess in zip(q["haystack_dates"], q["haystack_sessions"]):
            known = [k.split("|")[-1]
                     for k in model.export()["asset"].get("hist", {})]
            try:
                recs = extract_session(llm, date, sess,
                                       known_slots=known)
            except Exception as e:
                print(f"[{q['question_id']}] extract fail @{date}: {e}",
                      file=sys.stderr)
                recs = []
            for r in recs:
                model.ingest(r)
            nrecs += len(recs)
        try:
            resp = answer_question(llm_answer, model, q)
        except Exception as e:
            resp = f"__answer_error__ {e}"
        fh.write(json.dumps({
            "question_id": q["question_id"],
            "question_type": q["question_type"],
            "response": resp,
            "n_records": nrecs,
        }) + "\n")
        fh.flush()
        usage = llm.usage
        print(f"[{n+1}/{args.n}] {q['question_id']} "
              f"({q['question_type']}) recs={nrecs} resp={resp[:60]!r} "
              f"usage={usage}", flush=True)
        n += 1
    fh.close()


def judge(args):
    ref = {q["question_id"]: q for q in json.load(open(args.ref))}
    llm = _make_llm(args, backend=args.judge_backend or (
        'glm' if getattr(args, 'glm', False) else None))
    rows, by_type = [], {}
    for line in open(args.hyp):
        if not line.strip():
            continue
        h = json.loads(line)
        q = ref[h["question_id"]]
        try:
            ok = judge_one(llm, q, h["response"])
        except Exception as e:
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
    r.add_argument("--per-type", type=int, default=0,
                 help="stratified: n per question_type instead of first-n")
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
