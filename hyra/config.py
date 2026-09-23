"""Run configuration: file (JSON or YAML-if-pyyaml-present) + CLI overrides."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HyraConfig:
    task_dir: str = ""
    work_dir: str = "run_out"
    model: str | None = None           # OpenAI-compatible model id
    base_url: str | None = None        # OPENAI_BASE_URL
    api_key: str | None = None         # OPENAI_API_KEY
    mock: bool = False                 # offline scripted LLM
    workers: int = 4                   # concurrent proposal agents
    queue_target: int = 6              # inspirations to keep queued
    llm_concurrency: int = 4           # max simultaneous LLM calls
    max_solutions: int = 50            # commits per inner loop (budget)
    wall_clock: int | None = None      # seconds; None = unlimited
    sandbox_timeout: int = 300         # per-solve.sh seconds
    eval_timeout: int = 300            # per-evaluator seconds
    eval_rounds: int = 1               # outer loop (evaluator co-evolution)
    sandbox_backend: str = "local"     # local | docker
    docker_image: str = "python:3.12-slim"
    max_file_chars: int = 20000        # per-file cap shown to proposer
    seed: int = 0
    resume: bool = True                # reuse existing EB in work_dir
    extra_env: dict = field(default_factory=dict)


def load_config(path: str | None) -> HyraConfig:
    cfg = HyraConfig()
    if not path:
        return cfg
    p = Path(path)
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        import yaml  # optional dependency
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    for k, v in data.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
