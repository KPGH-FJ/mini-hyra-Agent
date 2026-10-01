#!/usr/bin/env python3
"""Subject-swap adversarial probe — official SUBJECT CHECK clause.

Synthetic LifeModel mirroring conv-0's vertex-catalog shape (caroline·
adoption_* vs melanie·*; catalog <=50 so aretrieve selects all, zero
retrieve calls — pure reader test). Uses the package's ANSWER_SYS
verbatim — run inside the worktree/tag whose reader.py carries the
clauses under test.

Usage: python probe_subject.py --api-key ... --base-url ... --model ...
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                     / "tasks" / "life_model" / "external"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lme import _make_llm                     # noqa: E402
from lifemodel.model import LifeModel         # noqa: E402
import lifemodel.reader as R                  # noqa: E402

RECS = [
    ("caroline", "adoption_agency_research", "Researching adoption agencies", 738422),
    ("caroline", "adoption_motivation", "Thrilled to make a family for kids who need one", 738422),
    ("caroline", "adoption_goal", "Goal is to give kids a loving home", 738422),
    ("caroline", "single_parent", "Will adopt as a single parent", 738422),
    ("caroline", "adoption_application", "Applied to adoption agencies", 738500),
    ("caroline", "adoption_interview", "Passed adoption agency interviews (on 2023-07-14)", 738550),
    ("melanie", "kids_summer_break_excitement", "Kids excited about summer break", 738422),
    ("melanie", "camping_plans", "Thinking about going camping next month (on 2023-06)", 738422),
    ("melanie", "charity_race", "Ran a charity race for mental health (on 2023-05-07)", 738420),
]

QS = [
    ("subject_swap",  "What is Melanie excited about in her adoption process?"),
    ("ctrl_own_fact", "When is Melanie planning to go camping?"),
    ("ctrl_cross",    "Is Melanie excited about Caroline's adoption?"),
    ("ctrl_absent",   "What is David excited about?"),
    ("ctrl_attributed", "What is Melanie excited about in Caroline's adoption process?"),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    llm = _make_llm(args, thinking=True)
    m = LifeModel()
    for i, (about, slot, val, day) in enumerate(RECS):
        m.ingest({"id": f"r{i}", "day": day, "source": "self",
                  "kind": "statement", "slot": slot, "value": val,
                  "about": about, "text": val})
    print("ANSWER_SYS tail:", R.ANSWER_SYS[-400:], file=sys.stderr)
    for tag, q in QS:
        r = await R.aanswer(m, llm, q, "2023-07-20")
        print(f"[{tag}] {q}\n  -> {r['response'][:200]}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
