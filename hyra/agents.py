"""Agent roles, prompts, and solution materialization.

Reconstructed from the Hyra launch post:
  * Context Agent maintains the EB and distills diverse "inspirations"
    into the task queue — each is a context bundle (base solution id(s) +
    a search direction + notes) for a Proposal Agent to consume.
  * Proposal Agents reflect on the inspiration and emit a COMPLETE
    solution/ dir (solve.sh entry), which is run+scored in a fresh sandbox
    and committed back to the EB.
  * Evaluator co-evolution (two-level loop): when a task ships no
    evaluator, one is generated; after each inner round the evaluator is
    refined from EB history — anti reward-hacking, finer granularity.

Diversity strategy (Context Agent contract): a mix of
  exploit — small targeted delta on the current best;
  explore — structurally different attempt seeded from a strong parent;
  hybrid — combine ideas from two parents;
  repair — fix a failure mode visible in the failure digest;
  fresh  — restart from scratch to escape local optima.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .eb import ExperienceBank
from .llm import LLM, parse_files, render_files

log = logging.getLogger("hyra.agents")

CONTEXT_SYSTEM = """<<CONTEXT_AGENT>>
You are the Context Agent of a research agent. You maintain an Experience
Bank (EB) of committed solutions and distill DIVERSE "inspirations" for
Proposal Agents. Return STRICT JSON — a list of objects:
{"direction": "exploit"|"explore"|"hybrid"|"repair"|"fresh",
 "base_ids": ["s0001", ...],   // 1 id normally, 2 for hybrid; [] for fresh
 "note": "what to change and why, grounded in the EB digest"}
Balance the portfolio: mostly exploit/explore on strong parents, some hybrid,
repair only when the failure digest shows a repeated failure mode, a few
fresh restarts. Ground every note in specifics (scores, params, logs)."""

PROPOSAL_SYSTEM = """<<PROPOSAL>>
You are a Proposal Agent in a research loop. Given the task, an inspiration
(direction + base solution(s) from the Experience Bank), emit a COMPLETE new
solution as files. A solution is a directory whose entry point is `solve.sh`;
running `bash solve.sh` inside it must produce `solution.json` in that dir.

Rules:
- One coherent change per proposal, aligned with the direction. In the header
  comment of solve.sh, state the DELTA vs the base solution and WHY it should
  score better.
- Be defensive: commit a known-good fallback to solution.json first, then
  attempt improvements — a valid output must always exist.
- Never read the evaluator or its data; never hardcode expected outputs —
  that is reward hacking and will be treated as failure.
- Emit EVERY file (including unchanged ones you still need) with this exact
  protocol:

<<<FILE: solve.sh>>>
#!/bin/bash
cd "$(dirname "$0")"
...
<<<END>>>"""

EVAL_GEN_SYSTEM = """<<EVALUATOR_GEN>>
Design the evaluator for a research task that shipped none. Emit a single
<<<FILE: evaluate.py>>> ... <<<END>>> that:
- takes the solution dir as argv[1], loads/executes its `solution.json`,
- prints STRICT JSON {"score": <float>, "feedback": <str>} as its LAST line;
  higher score = better.
Resist reward hacking: verify the artifact actually computes what it claims
(re-run on held-out/random probes, time it, diff against a reference), never
trust declared metrics."""

EVAL_REFINE_SYSTEM = """<<EVAL_REFINE>>
Improve the evaluator of a research loop. Given the current evaluate.py and
the EB digest (scores, directions, failure logs), emit a NEW complete
evaluate.py via the <<<FILE>>> protocol. Priorities, in order:
(1) close reward-hacking holes the search may have exploited;
(2) finer scoring granularity (avoid plateaus and ties);
(3) efficiency (the evaluator runs per solution).
Same contract: argv[1] = solution dir; last stdout line =
{"score": float, "feedback": str}."""

SKIP_NAMES = {"run.log", "meta.json", "proposal.txt"}


def read_tree(path: Path, limit: int = 20000,
              skip_artifacts: bool = True) -> dict[str, str]:
    out = {}
    for p in sorted(path.rglob("*")):
        if not p.is_file() or p.name in SKIP_NAMES:
            continue
        if any(part.startswith((".", "run_")) for part in p.parts):
            continue
        if skip_artifacts and p.name == "solution.json":
            continue
        try:
            out[str(p.relative_to(path))] = \
                p.read_text(errors="replace")[:limit]
        except Exception:
            pass
    return out


def _base_params(sol_dir: Path) -> dict:
    f = sol_dir / "model.py"
    if f.exists():
        m = re.search(r"PARAMS\s*=\s*(\{.*?\})", f.read_text(), re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    sj = sol_dir / "solution.json"
    if sj.exists():
        try:
            d = json.loads(sj.read_text())
            if isinstance(d, dict):
                return d.get("params", d)
        except Exception:
            pass
    return {}


def _json_from_text(text: str):
    """Tolerant JSON extraction for LLM output: direct parse, fenced
    block, then first `[`..`]` / `{..}` substring."""
    for cand in (text.strip(),):
        try:
            return json.loads(cand)
        except Exception:
            pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    for a, b in (("[", "]"), ("{", "}")):
        i, j = text.find(a), text.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    return None


async def make_inspirations(llm: LLM, eb: ExperienceBank, task_md: str,
                            n: int, eval_version: int,
                            max_file_chars: int = 20000) -> list[dict]:
    """Context Agent turn: digest the EB, emit n diverse inspirations."""
    prompt = (f"TASK:\n{task_md}\n\nEB DIGEST:\n"
              f"{eb.summary(eval_version)}\n\n"
              f"Return ONLY a JSON array of {n} inspirations "
              f"(no prose, no fences).")
    try:
        items = _json_from_text(await llm.complete(CONTEXT_SYSTEM, prompt))
        if isinstance(items, dict):
            items = items.get("inspirations") or [items]
        if not isinstance(items, list):
            items = []
    except Exception as e:
        log.warning("context agent returned non-JSON: %s", e)
        items = []
    # fallback so the queue never starves on a weak model
    while len(items) < n:
        best = eb.best(eval_version)
        items.append({"direction": "exploit",
                      "base_ids": [best["id"]] if best else [],
                      "note": "fallback exploit on best"})
    inspirations = []
    for it in items[:n]:
        if not isinstance(it, dict):
            continue
        base_ids = [b for b in (it.get("base_ids") or [])
                    if eb.get(b)]
        inspirations.append({
            "direction": str(it.get("direction", "explore"))[:60],
            "note": str(it.get("note", ""))[:2000],
            "base_ids": base_ids[:2] or (
                [eb.best(eval_version)["id"]]
                if it.get("direction") != "fresh"
                and eb.best(eval_version) else []),
        })
    return inspirations


async def write_solution(llm: LLM, task_md: str, inspiration: dict,
                         eb: ExperienceBank, out_dir: Path,
                         max_file_chars: int = 20000,
                         total_base_chars: int = 60000) -> tuple[Path, str]:
    """Proposal Agent: emit a full solution dir; returns (dir, raw_text)."""
    base_sections, params = [], {}
    for bid in inspiration.get("base_ids", []):
        e = eb.get(bid)
        if not e:
            continue
        files = read_tree(Path(e["path"]), max_file_chars)
        base_sections.append(
            f"BASE SOLUTION {bid} (score={e['score']}):\n"
            f"{render_files(files)}")
        params = params or _base_params(Path(e["path"]))
    # bound the joined base material: Atria rejects oversized prompts with
    # 400s, and evolved assets can reach ~40KB each — two parents plus the
    # task spec overran the input window in run_v5 W3 (12/15 deaths).
    # A section that doesn't fit is cut at its last complete <<<END>>>
    # file boundary; a mid-file excerpt is closed and labeled so the model
    # never inherits a dangling <<<FILE>>> block. Too little room → drop.
    budget = total_base_chars
    for i, sec in enumerate(base_sections):
        if len(sec) > budget:
            if budget < 2500:
                del base_sections[i:]
                break
            keep = budget - 220
            excerpt = sec[:keep]
            last_end = excerpt.rfind("<<<END>>>")
            if last_end > 0:
                excerpt = excerpt[:last_end + 9]
                dropped = len(sec) - len(excerpt)
                base_sections[i] = (
                    excerpt +
                    f"\n[{dropped} chars of base material omitted "
                    "— file list truncated]")
            else:
                base_sections[i] = (
                    excerpt +
                    "\n<<<END>>>\n[partial file excerpt — "
                    f"{len(sec) - keep} chars omitted mid-file]")
        budget -= len(base_sections[i])
        if budget <= 0:
            del base_sections[i + 1:]
            break
    prompt = (
        f"TASK:\n{task_md}\n\n"
        f"<<<DIRECTION>>>{inspiration['direction']}<<<\n"
        f"NOTE: {inspiration.get('note', '')}\n\n"
        f"<<<BASE_PARAMS>>>\n{json.dumps(params)}\n<<<END_BASE>>>\n\n"
        + "\n\n".join(base_sections)
        + "\n\nOutput the new solution files now.")
    text = await llm.complete(PROPOSAL_SYSTEM, prompt)
    files = parse_files(text)
    if "solve.sh" not in files:
        raise ValueError("proposal produced no solve.sh")
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        rel = rel.strip().lstrip("/")
        if ".." in Path(rel).parts:
            continue
        fp = out_dir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    (out_dir / "solve.sh").chmod(0o755)
    return out_dir, text


async def generate_evaluator(llm: LLM, task_md: str,
                             task_dir: Path) -> bool:
    text = await llm.complete(EVAL_GEN_SYSTEM, f"TASK:\n{task_md}")
    files = parse_files(text)
    if "evaluate.py" not in files:
        return False
    (task_dir / "evaluate.py").write_text(files["evaluate.py"])
    return True


async def refine_evaluator(llm: LLM, task_md: str, task_dir: Path,
                           eb: ExperienceBank, eval_version: int) -> bool:
    cur = (task_dir / "evaluate.py").read_text()
    prompt = (f"TASK:\n{task_md}\n\nCURRENT EVALUATOR:\n{cur}\n\n"
              f"EB DIGEST:\n{eb.summary(eval_version)}\n\n"
              "Emit the improved evaluate.py.")
    files = parse_files(await llm.complete(EVAL_REFINE_SYSTEM, prompt))
    if "evaluate.py" not in files:
        return False
    versions = task_dir / "evaluator_versions"
    versions.mkdir(exist_ok=True)
    (versions / f"evaluate_v{eval_version}.py").write_text(cur)
    (task_dir / "evaluate.py").write_text(files["evaluate.py"])
    return True
