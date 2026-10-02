"""sec_pick / sec_all arms for >=60v profile questions.

Splits the cached rendered profile into `## ` sections, builds a
domain roster (title + bullet count + top-3 entity hints), then:
- sec_pick: LLM picks 1-3 sections from the roster; answer uses only
  picked sections.
- sec_all: answer with all sections (same content, sectioned frame).
Both arms use PROFILE_ANSWER_SYS (advisory-clause version).
"""
import asyncio, json, os, re, sys
sys.path.insert(0, "/home/ubuntu/m4-complete")
sys.path.insert(0, "/home/ubuntu/serve-v4")
sys.path.insert(0, "/home/ubuntu/m4-complete/results/mainstack")
from hyra.llm import OpenAICompatLLM
import importlib
lf = importlib.import_module("lifemodel.reader")
PROFILE_ANSWER_SYS = lf.PROFILE_ANSWER_SYS

PICK_SYS = """You are routing a question to sections of a persona profile.
Pick the 1-3 section indices most likely to contain the facts needed
to answer. Prefer the fewest sections that plausibly cover the question.
Reply with a JSON array of indices only, e.g. [0, 2]."""


def split_sections(text):
    parts = re.split(r'(?m)^(?=## )', text)
    head = [p for p in parts if p.startswith('## ')]
    if head:
        return head
    parts = re.split(r'(?m)^(?=### )', text)
    head = [p for p in parts if p.startswith('### ')]
    if head:
        return head
    parts = re.split(r'(?m)^(?=\*\*[^\n*]+\*\*\s*$)', text)
    return [p for p in parts if re.match(r'^\*\*', p)]


def summarize(sec):
    title = sec.split('\n', 1)[0].lstrip('# ').strip().strip('*').strip()
    bullets = [l for l in sec.split('\n') if l.strip().startswith('-')]
    subs = re.findall(r'(?m)^###\s+(.+)$', sec)
    if subs:
        ents = [s.strip() for s in subs[:3]]
    else:
        ents = [' '.join(b.lstrip('- ').split()[:6]) for b in bullets[:3]]
    return title, len(bullets), ents


async def run_item(llm, m, out_dir):
    arms = os.environ.get("ARMS", "sec_pick,sec_all").split(",")
    prof = open(m['profile_path']).read()
    secs = split_sections(prof)
    row = {"qid": m['qid'], "n_sections": len(secs)}
    if "sec_pick" in arms:
        roster = []
        for i, s in enumerate(secs):
            t, nb, ents = summarize(s)
            roster.append(f"[{i}] {t} — {nb} bullets — e.g. {'; '.join(ents)}")
        pick_raw = (await llm.complete(
            PICK_SYS,
            "SECTIONS:\n" + "\n".join(roster) + f"\n\nQUESTION: {m['question']}")).strip()
        mraw = re.search(r'\[[\d,\s]*\]', pick_raw)
        try:
            idxs = [int(x) for x in json.loads(mraw.group(0))][:3] if mraw else list(range(len(secs)))
        except Exception:
            idxs = list(range(len(secs)))
        idxs = [i for i in idxs if 0 <= i < len(secs)] or list(range(len(secs)))
        picked = "\n\n".join(secs[i] for i in idxs)
        row["picked"] = idxs
        row["pick_raw"] = pick_raw[:80]
        row["sec_pick"] = (await llm.complete(
            PROFILE_ANSWER_SYS.format(qdate=m['qdate']),
            f"PROFILE SECTIONS:\n{picked}\n\nQUESTION: {m['question']}")).strip()
    if "sec_all" in arms:
        allsecs = "\n\n".join(secs)
        row["sec_all"] = (await llm.complete(
            PROFILE_ANSWER_SYS.format(qdate=m['qdate']),
            f"PROFILE SECTIONS:\n{allsecs}\n\nQUESTION: {m['question']}")).strip()
    return row


async def main():
    manifest = json.load(open(sys.argv[1]))
    out_path = sys.argv[2]
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["qid"] for l in open(out_path)}
    llm = OpenAICompatLLM()
    fh = open(out_path, "a")
    sem = asyncio.Semaphore(4)

    async def one(m):
        if m['qid'] in done:
            return
        row = await run_item(llm, m, None)
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        print(m['qid'], 'secs', row['n_sections'], 'picked', row.get('picked'), flush=True)

    await asyncio.gather(*(one(m) for m in manifest))


asyncio.run(main())
