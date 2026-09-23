"""hyra CLI.

    hyra run --task tasks/symbolic_fit --mock --solutions 40 --workers 4
    hyra run --task tasks/my_task --config config.json
    hyra status --work run_out
    hyra best  --work run_out
    hyra eval  --task tasks/my_task --solution path/to/solution_dir
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import HyraConfig, load_config
from .eb import ExperienceBank
from .harness import HyraHarness
from .llm import OpenAICompatLLM, ScriptedLLM
from .sandbox import run_solution


def _setup_logging(work_dir: str) -> None:
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(Path(work_dir) / "hyra.log")])


def _apply_overrides(cfg: HyraConfig, a: argparse.Namespace) -> HyraConfig:
    for k in ("task_dir", "work_dir", "model", "base_url", "api_key",
              "workers", "queue_target", "llm_concurrency", "max_solutions",
              "wall_clock", "sandbox_timeout", "eval_timeout", "eval_rounds",
              "sandbox_backend", "docker_image", "seed", "mock"):
        v = getattr(a, k, None)
        if v is not None:
            setattr(cfg, k, v)
    return cfg


def cmd_run(a: argparse.Namespace) -> int:
    cfg = _apply_overrides(load_config(a.config), a)
    if not cfg.task_dir:
        print("--task is required", file=sys.stderr)
        return 2
    _setup_logging(cfg.work_dir)
    llm = (ScriptedLLM(seed=cfg.seed) if cfg.mock
           else OpenAICompatLLM(model=cfg.model, base_url=cfg.base_url,
                                api_key=cfg.api_key))
    report = asyncio.run(HyraHarness(cfg, llm).run())
    print("\n=== RESULT ===")
    print(json.dumps({k: v for k, v in report.items() if k != "eb_root"},
                     indent=2)[:6000])
    print(f"EB at: {report['eb_root']}")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    eb = ExperienceBank(Path(a.work) / "eb")
    xs = eb.all()
    scored = eb.scored()
    print(f"commits={len(xs)} scored={len(scored)} "
          f"failed={len(xs) - len(scored)}")
    print(eb.summary())
    return 0


def cmd_best(a: argparse.Namespace) -> int:
    eb = ExperienceBank(Path(a.work) / "eb")
    best = eb.best()
    if not best:
        print("no scored solutions")
        return 1
    print(json.dumps(best, indent=2))
    return 0


def cmd_eval(a: argparse.Namespace) -> int:
    import tempfile
    sol = Path(a.solution)
    with tempfile.TemporaryDirectory() as td:
        res = run_solution(sol, a.task,
                           env={},
                           backend="local")
        print(json.dumps({k: res[k] for k in ("score", "feedback", "error")},
                         indent=2))
    return 0 if res["score"] is not None else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="hyra",
        description="Hyra-style research-agent harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the research loop")
    r.add_argument("--task", dest="task_dir")
    r.add_argument("--work", dest="work_dir")
    r.add_argument("--config")
    r.add_argument("--model")
    r.add_argument("--base-url", dest="base_url")
    r.add_argument("--api-key", dest="api_key")
    r.add_argument("--workers", type=int)
    r.add_argument("--queue-target", dest="queue_target", type=int)
    r.add_argument("--llm-concurrency", dest="llm_concurrency", type=int)
    r.add_argument("--solutions", dest="max_solutions", type=int)
    r.add_argument("--wall-clock", dest="wall_clock", type=int)
    r.add_argument("--sandbox-timeout", dest="sandbox_timeout", type=int)
    r.add_argument("--eval-timeout", dest="eval_timeout", type=int)
    r.add_argument("--eval-rounds", dest="eval_rounds", type=int)
    r.add_argument("--sandbox", dest="sandbox_backend",
                   choices=["local", "docker"])
    r.add_argument("--docker-image", dest="docker_image")
    r.add_argument("--seed", type=int)
    r.add_argument("--mock", action="store_true", default=None)
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="EB digest")
    s.add_argument("--work", dest="work", default="run_out")
    s.set_defaults(fn=cmd_status)

    b = sub.add_parser("best", help="print best solution entry")
    b.add_argument("--work", dest="work", default="run_out")
    b.set_defaults(fn=cmd_best)

    e = sub.add_parser("eval", help="run+score one solution dir")
    e.add_argument("--task", required=True)
    e.add_argument("--solution", required=True)
    e.set_defaults(fn=cmd_eval)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
