"""The Hyra loop: async producer-consumer harness.

Context Agent (producer) keeps the inspiration queue filled; N Proposal
Agents (consumers) pull inspirations, write solutions, run them in fresh
sandboxes, score, and commit to the EB. Semaphores bound LLM and sandbox
concurrency. Budgets: max committed solutions per inner loop and/or wall
clock. Two-level mode: if the task has no evaluator one is generated; after
each inner round the evaluator itself is refined from EB history.

Resumable: the EB persists every commit; `resume=True` continues a prior
run's EB in the same work dir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import tempfile
import time
from pathlib import Path

from .agents import (generate_evaluator, make_inspirations, refine_evaluator,
                     write_solution)
from .config import HyraConfig
from .eb import ExperienceBank
from .llm import LLM
from .sandbox import run_solution

log = logging.getLogger("hyra.harness")


class HyraHarness:
    def __init__(self, cfg: HyraConfig, llm: LLM):
        self.cfg = cfg
        self.llm = llm
        self.task_dir = Path(cfg.task_dir)
        self.task_md = (self.task_dir / "task.md").read_text()
        self.work = Path(cfg.work_dir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.eb = ExperienceBank(self.work / "eb")
        self.queue: asyncio.Queue = asyncio.Queue()
        self.sem_sandbox = asyncio.Semaphore(cfg.workers)
        self.sem_llm = asyncio.Semaphore(cfg.llm_concurrency)
        self.eval_version = 0
        self._committed = 0
        self._stop = asyncio.Event()
        self._rng = random.Random(cfg.seed)
        self._t0 = 0.0

    # ---------------- producer ----------------
    async def _context_agent(self):
        while not self._stop.is_set():
            try:
                if self.queue.qsize() < self.cfg.queue_target:
                    n = self.cfg.queue_target - self.queue.qsize()
                    async with self.sem_llm:
                        ins = await make_inspirations(
                            self.llm, self.eb, self.task_md, n,
                            self.eval_version, self.cfg.max_file_chars)
                    for it in ins:
                        await self.queue.put(it)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("context agent error: %s", e)
                await asyncio.sleep(2)

    # ---------------- consumers ----------------
    async def _proposal_worker(self, wid: int):
        while not self._stop.is_set():
            try:
                ins = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if self._budget_hit():
                    return
                continue
            if self._budget_hit():
                return
            await self._one_proposal(ins, wid)

    async def _one_proposal(self, ins: dict, wid: int):
        with tempfile.TemporaryDirectory(prefix="hyra_prop_") as td:
            out = Path(td) / "proposal"
            try:
                async with self.sem_llm:
                    out, raw = await write_solution(
                        self.llm, self.task_md, ins, self.eb, out,
                        self.cfg.max_file_chars)
            except Exception as e:
                self.eb.add(out if out.exists() else td, score=None,
                          direction=ins["direction"], parents=ins["base_ids"],
                          eval_version=self.eval_version,
                          error=f"proposal error: {e}")
                self._committed += 1
                return
            async with self.sem_sandbox:
                res = await asyncio.to_thread(
                    run_solution, out, self.task_dir,
                    timeout=self.cfg.sandbox_timeout,
                    eval_timeout=self.cfg.eval_timeout,
                    env=self.cfg.extra_env,
                    backend=self.cfg.sandbox_backend,
                    docker_image=self.cfg.docker_image)
            entry = self.eb.add(
                out, score=res["score"], feedback=res["feedback"],
                direction=ins["direction"], parents=ins["base_ids"],
                eval_version=self.eval_version, error=res["error"],
                proposal_text=raw)
            self._committed += 1
            tag = f"score={entry['score']:.6g}" if entry["score"] is not None \
                else f"ERR {entry['error']}"
            log.info("[%s] %s dir=%s parents=%s", entry["id"], tag,
                     entry["direction"], entry["parents"])

    # ---------------- control ----------------
    def _budget_hit(self) -> bool:
        if self._committed >= self.cfg.max_solutions:
            return True
        if self.cfg.wall_clock and (time.time() - self._t0) > \
                self.cfg.wall_clock:
            return True
        return False

    async def _commit_seed(self):
        """If the task ships seed_solution/ and the EB is empty, run+score it
        and commit it as the first entry — proposals then have a base to
        improve from, matching Hyra's 'same initial seed solution' setup."""
        seed = self.task_dir / "seed_solution"
        if not seed.is_dir() or not (seed / "solve.sh").exists():
            return
        if any(e["id"] == "seed" or e["direction"] == "seed"
               for e in self.eb.all()):
            return
        log.info("committing seed_solution into the EB ...")
        with tempfile.TemporaryDirectory(prefix="hyra_seed_") as td:
            work_seed = Path(td) / "seed"
            shutil.copytree(seed, work_seed)
            res = await asyncio.to_thread(
                run_solution, work_seed, self.task_dir,
                timeout=self.cfg.sandbox_timeout,
                eval_timeout=self.cfg.eval_timeout,
                env=self.cfg.extra_env, backend=self.cfg.sandbox_backend,
                docker_image=self.cfg.docker_image)
            self.eb.add(work_seed, score=res["score"],
                        feedback=res["feedback"], direction="seed",
                        eval_version=self.eval_version, error=res["error"])
        log.info("seed committed: score=%s err=%s", res["score"], res["error"])

    async def run(self) -> dict:
        self._t0 = time.time()
        if not (self.task_dir / "evaluate.py").exists():
            log.info("no evaluator in task; generating v0 evaluator")
            async with self.sem_llm:
                ok = await generate_evaluator(self.llm, self.task_md,
                                              self.task_dir)
            if not ok:
                raise RuntimeError(
                    "task has no evaluator and generation failed")

        await self._commit_seed()

        for rnd in range(self.cfg.eval_rounds):
            self.eval_version = rnd
            self._committed = 0
            self._stop.clear()
            log.info("=== eval v%d inner loop: budget=%d solutions ===",
                     rnd, self.cfg.max_solutions)
            producer = asyncio.create_task(self._context_agent())
            workers = [asyncio.create_task(self._proposal_worker(i))
                       for i in range(self.cfg.workers)]
            while not self._budget_hit():
                await asyncio.sleep(0.2)
            self._stop.set()
            producer.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            log.info("=== inner loop done: %d commits this round ===",
                     self._committed)
            if rnd + 1 < self.cfg.eval_rounds:
                log.info("refining evaluator from EB history ...")
                async with self.sem_llm:
                    ok = await refine_evaluator(self.llm, self.task_md,
                                                self.task_dir, self.eb,
                                                self.eval_version)
                if not ok:
                    log.warning("evaluator refinement failed; keeping v%d",
                                rnd)
                    break

        best = self.eb.best()
        report = {
            "best": best,
            "total_commits": self.eb.count(),
            "elapsed_sec": round(time.time() - self._t0, 1),
            "llm_usage": getattr(self.llm, "usage", {}),
            "eb_root": str(self.eb.root),
        }
        (self.work / "report.json").write_text(json.dumps(report, indent=2))
        return report
