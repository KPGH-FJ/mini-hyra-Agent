"""Experience Bank (EB): append-only store of every committed solution.

    work_dir/eb/
      index.json                  # one entry per committed solution
      solutions/<id>/             # full solution dir + run artifacts
        <solution files>
        solution.json             # structured result from solve.sh
        run.log                   # solve.sh + evaluator output
        meta.json                 # score, eval_version, parents, direction
        proposal.txt              # raw LLM output that produced this solution

Score convention: higher is better. Entries with score=None are failures —
kept in the bank because failure history is itself experience for the agents.
"""
from __future__ import annotations

import json
import random
import shutil
import threading
import time
from pathlib import Path


class ExperienceBank:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "solutions").mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"
        self._lock = threading.Lock()
        if not self._index_path.exists():
            self._index_path.write_text("[]")

    # ---------------- persistence ----------------
    def _load(self) -> list[dict]:
        try:
            return json.loads(self._index_path.read_text())
        except Exception:
            return []

    def _save(self, idx: list[dict]) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, indent=2))
        tmp.replace(self._index_path)

    # ---------------- write ----------------
    def add(self, solution_dir: str | Path, *, score: float | None,
            feedback: str = "", direction: str = "",
            parents: list[str] | None = None, eval_version: int = 0,
            error: str | None = None, proposal_text: str | None = None) -> dict:
        src = Path(solution_dir)
        with self._lock:
            idx = self._load()
            sid = f"s{len(idx):04d}"
            dst = self.root / "solutions" / sid
            shutil.copytree(src, dst, dirs_exist_ok=True)
            if proposal_text is not None:
                (dst / "proposal.txt").write_text(proposal_text[:200000])
            entry = {
                "id": sid, "score": score, "direction": direction,
                "parents": parents or [], "eval_version": eval_version,
                "created": time.time(), "feedback": feedback[:4000],
                "error": error, "path": str(dst),
            }
            (dst / "meta.json").write_text(json.dumps(entry, indent=2))
            idx.append(entry)
            self._save(idx)
            return entry

    # ---------------- read ----------------
    def all(self) -> list[dict]:
        return self._load()

    def get(self, sid: str) -> dict | None:
        return next((e for e in self._load() if e["id"] == sid), None)

    def scored(self, eval_version: int | None = None) -> list[dict]:
        xs = [e for e in self._load() if e["score"] is not None]
        if eval_version is not None:
            xs = [e for e in xs if e["eval_version"] == eval_version]
        return sorted(xs, key=lambda e: e["score"], reverse=True)

    def best(self, eval_version: int | None = None) -> dict | None:
        xs = self.scored(eval_version)
        return xs[0] if xs else None

    def sample(self, n: int, rng: random.Random,
             eval_version: int | None = None) -> list[dict]:
        xs = self._load() if eval_version is None else [
            e for e in self._load() if e["eval_version"] == eval_version]
        return rng.sample(xs, min(n, len(xs))) if xs else []

    def count(self) -> int:
        return len(self._load())

    def summary(self, eval_version: int | None = None, top_k: int = 5,
                worst_k: int = 3, fail_k: int = 5) -> str:
        """Compact digest of the EB for the Context Agent prompt."""
        xs = self._load()
        lines = [f"total_commits={len(xs)} eval_version={eval_version}"]
        scored = self.scored(eval_version)
        if scored:
            lines.append("TOP (best first):")
            for e in scored[:top_k]:
                lines.append(
                    f"  {e['id']} score={e['score']:.6g} "
                    f"dir={e['direction']} parents={e['parents']} "
                    f"feedback={e['feedback'][:160]!r}")
            if len(scored) > top_k + worst_k:
                lines.append("BOTTOM (avoid repeating):")
                for e in scored[-worst_k:]:
                    lines.append(
                        f"  {e['id']} score={e['score']:.6g} "
                        f"dir={e['direction']}")
        fails = [e for e in xs if e["error"]][-fail_k:]
        if fails:
            lines.append("RECENT FAILURES (diagnose, don't repeat):")
            for e in fails:
                lines.append(f"  {e['id']} err={e['error'][:160]}")
        return "\n".join(lines)
