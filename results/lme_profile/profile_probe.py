"""Profile-completeness probe: render a persona profile from a TemporalGraph
model, then answer the question using ONLY the profile (no retrieval/digest).
Measures profile information loss vs full-memory answers.
"""
import asyncio, json, os, sys, datetime as _dt

sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
sys.path.insert(0, "/home/ubuntu/m4-complete")
from lifemodel import reader  # noqa: E402
from hyra.llm import OpenAICompatLLM  # noqa: E402


class _M:
    def __init__(self, asset): self._a = asset
    def export(self): return {"asset": self._a}


def load_model(path):
    return _M(json.load(open(path))["export"]["asset"])


def memory_dump(model):
    """Every vertex fully rendered — the raw material for the profile."""
    cat = reader.vertex_catalog(model)
    return reader.render_vertices(model, list(cat))


PROFILE_SYS = """You are compiling a PERSONA PROFILE from a user's memory records.
Organize the records into a coherent profile of this person, grouped by life
domain (identity/work, health & habits, hobbies & interests, possessions &
purchases, relationships & social, plans & commitments, events & timeline,
preferences & opinions).

CRITICAL: this profile will be the ONLY memory used to answer questions later.
- Preserve EVERY concrete fact verbatim-ish: names, counts, dates, durations,
  places, prices, items — never generalize "bought a peace lily on 2023-05-07"
  into "bought plants recently".
- Keep temporal anchors (dates / relative times) inline with each fact.
- Keep both user facts AND assistant-provided facts (recommendations, advice
  the user received) — tag assistant-side facts as "assistant suggested X".
- Group by domain; within a domain keep one bullet per atomic fact.
- No preamble, no analysis — emit ONLY the profile document."""


ANSWER_SYS = """You are the user's assistant with access to their persona profile.
Answer the question using ONLY facts present in the profile. Today is {qdate}.
If the profile does not contain the needed information, say so plainly.
Be direct: give the answer first (a number, a list, a fact), then one line of
justification citing the profile facts used."""


async def run_one(llm, model_path, q, out_dir):
    model = load_model(model_path)
    dump = memory_dump(model)
    profile = await llm.complete(
        PROFILE_SYS,
        f"MEMORY RECORDS ({reader.vertex_catalog(model).__len__()} topics):\n"
        + dump)
    answer = await llm.complete(
        ANSWER_SYS.format(qdate=q["question_date"]),
        f"PROFILE:\n{profile}\n\nQUESTION: {q['question']}")
    qid = q["question_id"]
    with open(os.path.join(out_dir, f"{qid}.profile.md"), "w") as f:
        f.write(profile)
    return {"question_id": qid, "question_type": q["question_type"],
            "response": answer, "profile_chars": len(profile),
            "dump_chars": len(dump),
            "n_vertices": len(reader.vertex_catalog(model))}


async def main():
    manifest = json.load(open(sys.argv[1]))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    prof_dir = os.path.join(out_dir, "profiles")
    os.makedirs(prof_dir, exist_ok=True)
    llm = OpenAICompatLLM(
        model=os.environ.get("OPENAI_MODEL", "Atria-Dawn-Preview"),
        base_url=os.environ.get("OPENAI_BASE_URL",
                                "https://api.atria-asi.ai/v1"),
        api_key=os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ATRIA_API_KEY", ""),
        max_tokens=8192)
    done = set()
    outpath = os.path.join(out_dir, "hyp_profile.jsonl")
    if os.path.exists(outpath):
        done = {json.loads(l)["question_id"] for l in open(outpath)}
    fh = open(outpath, "a")
    for i, item in enumerate(manifest):
        if item["q"]["question_id"] in done:
            continue
        row = await run_one(llm, item["model"], item["q"], prof_dir)
        fh.write(json.dumps(row) + "\n"); fh.flush()
        print(f"[{i+1}/{len(manifest)}] {row['question_id']} "
              f"v={row['n_vertices']} prof={row['profile_chars']}B "
              f"dump={row['dump_chars']}B", flush=True)
    fh.close()

asyncio.run(main())
