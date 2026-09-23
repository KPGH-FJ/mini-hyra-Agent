"""Fresh-sandbox execution of a solution.

Solution contract (mirroring hyra-results artifacts):
  * A solution is a directory whose entry point is `solve.sh`.
  * solve.sh runs with cwd = the solution dir, in a clean copy, with
    env-injected resources (SEED/CPUS/...), a wall-clock timeout, and
    (local backend) rlimits on CPU/memory/file size.
  * On success it must produce `solution.json` in that dir.
  * The task evaluator `evaluate.py` is then run as
        python3 evaluate.py <solution_dir>
    and must print {"score": <float>, "feedback": <str>} on its last line.
    Higher score is better.

Backends:
  * local  — plain subprocess + resource.setrlimit (default; no isolation
             beyond a fresh dir — solutions are model-generated code, run it
             on infrastructure you trust, or use the docker backend).
  * docker — `docker run --rm --network none` on a mounted copy (stronger
             isolation; requires docker and the configured image).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("hyra.sandbox")

MAX_LOG = 20000


def _limits(cpus: int, mem_mb: int) -> None:  # pragma: no cover - platform
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (cpus * 60, cpus * 60))
    resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 << 20, 256 << 20))


def _run_local(sol: Path, timeout: int, env: dict, cpus: int,
               mem_mb: int) -> dict:
    try:
        p = subprocess.run(
            ["bash", "solve.sh"], cwd=sol, env=env, capture_output=True,
            text=True, timeout=timeout,
            preexec_fn=lambda: _limits(cpus, mem_mb)
            if hasattr(os, "getuid") else None)
        return {"log": (p.stdout + p.stderr)[-MAX_LOG:],
                "error": None if p.returncode == 0
                else f"solve.sh exit {p.returncode}"}
    except subprocess.TimeoutExpired:
        return {"log": "", "error": f"solve.sh timeout >{timeout}s"}


def _run_docker(sol: Path, timeout: int, env: dict, image: str,
                mem_mb: int) -> dict:
    cmd = ["docker", "run", "--rm", "--network", "none",
           "-m", f"{mem_mb}m",
           "-v", f"{sol}:/work", "-w", "/work"]
    for k, v in env.items():
        if k.startswith(("SEED", "CPUS", "HYRA_")):
            cmd += ["-e", f"{k}={v}"]
    cmd += [image, "bash", "solve.sh"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 30)
        return {"log": (p.stdout + p.stderr)[-MAX_LOG:],
                "error": None if p.returncode == 0
                else f"docker run exit {p.returncode}"}
    except subprocess.TimeoutExpired:
        return {"log": "", "error": f"solve.sh (docker) timeout >{timeout}s"}
    except FileNotFoundError:
        return {"log": "", "error": "docker not installed"}


def run_solution(solution_dir: str | Path, task_dir: str | Path, *,
                 timeout: int = 300, eval_timeout: int = 300,
                 env: dict | None = None, backend: str = "local",
                 docker_image: str = "python:3.12-slim",
                 cpus: int = 8, mem_mb: int = 4096) -> dict:
    """Run solve.sh on a fresh copy, then evaluate; replaces solution_dir
    with the post-run directory (including run.log + solution.json)."""
    work = Path(tempfile.mkdtemp(prefix="hyra_sbx_"))
    sol = work / "solution"
    shutil.copytree(solution_dir, sol)
    run_env = dict(env or {})
    run_env.setdefault("SEED", "0")
    run_env.setdefault("CPUS", str(cpus))
    full_env = dict(os.environ)
    full_env.update(run_env)

    if backend == "docker":
        res = _run_docker(sol, timeout, run_env, docker_image, mem_mb)
    else:
        res = _run_local(sol, timeout, full_env, cpus, mem_mb)

    res.update({"score": None, "feedback": ""})
    (sol / "run.log").write_text(res["log"])

    evaluator = Path(task_dir) / "evaluate.py"
    if res["error"] is None and evaluator.exists():
        try:
            q = subprocess.run(["python3", str(evaluator), str(sol)],
                               capture_output=True, text=True,
                               timeout=eval_timeout)
            lines = q.stdout.strip().splitlines()
            verdict = json.loads(lines[-1]) if lines else {}
            res["score"] = float(verdict["score"])
            res["feedback"] = str(verdict.get("feedback", ""))[:4000]
            res["log"] += ("\n=== evaluator stderr ===\n" + q.stderr[-2000:]
                           if q.stderr else "")
        except Exception as e:
            res["error"] = f"evaluator error: {e}"
            res["log"] += "\n=== evaluator output ===\n" + (
                (q.stdout + q.stderr)[-4000:] if "q" in locals() else "n/a")
    elif res["error"] is None:
        res["error"] = "no evaluator (task/evaluate.py missing)"

    back = Path(solution_dir)
    shutil.rmtree(back, ignore_errors=True)
    shutil.copytree(sol, back)
    shutil.rmtree(work, ignore_errors=True)
    return res
