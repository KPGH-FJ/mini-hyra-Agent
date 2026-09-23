# hyra — clean-room reimplementation of Tencent Hunyuan's Hyra harness

An **unofficial** reimplementation of the Hyra (Hunyuan Research Agent) loop,
rebuilt only from public materials: the Hyra-1.0 launch post
(hy.tencent.com/research/hyra, 2026-07-21) and the solution conventions in
`Tencent-Hunyuan/hyra-results`. No Tencent code or internals are used.

Built for real automated-research use: point it at a task, give it an LLM,
and it runs a producer–consumer search that keeps improving solutions until
the budget is spent.

## Architecture

```
 Experience Bank (append-only: solution src + run.log + score + eval_version)
      ^                                          |
      | commit                                   | distill inspirations
 Context Agent  ---> inspiration queue ---> Proposal Agents (N concurrent)
                                               | write solution/ (solve.sh entry)
                                               v
                              fresh sandbox: solve.sh -> solution.json
                                               | evaluate.py scores -> back to EB
Termination: budget spent / wall clock -> best-scored solution returned.
Two-level loop: --eval-rounds N > 1 refines the evaluator itself between
rounds from EB history (anti reward-hacking, finer granularity). If the task
has no evaluator, one is generated first.
```

- **Inspiration portfolio**: exploit / explore / hybrid(2 parents) / repair /
  fresh — the Context Agent must ground every note in the EB digest.
- **Lineage**: every commit records parents, direction, score, evaluator
  version, and the raw proposal text.
- **Resumable**: re-run with the same `--work` dir and the EB continues.
- **Defensive contract**: solutions are directories with a `solve.sh` entry
  that must write `solution.json` — exactly the convention Hyra's published
  artifacts follow.

## Install & run

```bash
pip install -e .            # or run in place: python3 -m hyra.cli ...

# offline smoke test (ScriptedLLM exercises the whole pipeline, no API key):
hyra run --task tasks/symbolic_fit --mock --solutions 40 --workers 4
hyra run --task tasks/circle_packing --mock --solutions 30 --workers 4

# real run — any OpenAI-compatible endpoint (OpenAI, vLLM, DeepSeek,
# Qwen, Hunyuan, one-api/ LiteLLM gateways, ...):
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1   # or your gateway
export OPENAI_MODEL=gpt-4o
hyra run --task tasks/circle_packing --solutions 60 --workers 4 \
    --eval-rounds 2 --wall-clock 7200

# inspect
hyra status --work run_out
hyra best   --work run_out
hyra eval   --task tasks/circle_packing --solution run_out/eb/solutions/s0042
```

## Defining a task

Create `tasks/<name>/` with:

| file | required | purpose |
|---|---|---|
| `task.md` | yes | task description shown to the agents (contract, constraints, what improves) |
| `evaluate.py` | yes* | `python3 evaluate.py <solution_dir>` → last stdout line `{"score": float, "feedback": str}`; higher score = better |
| `seed_solution/` | no | starting `solve.sh` dir, committed to the EB first |
| `data/` etc. | no | read-only task assets the evaluator can use |

\* If absent, the system generates `evaluate.py` itself (two-level mode).

**Writing a good evaluator is the whole game.** It must resist reward
hacking: recompute everything, verify the artifact does what it claims on
held-out probes, never trust declared metrics. `circle_packing/evaluate.py`
shows the pattern (re-checks all geometric constraints).

## Config file

```json
{ "task_dir": "tasks/circle_packing", "work_dir": "run_out",
  "model": "gpt-4o", "workers": 4, "max_solutions": 60,
  "eval_rounds": 2, "wall_clock": 7200, "sandbox_timeout": 600 }
```

`hyra run --config config.json` (`.yaml` also accepted if pyyaml is
installed); CLI flags override file values.

## Options

| flag | default | meaning |
|---|---|---|
| `--workers` | 4 | concurrent proposal agents |
| `--queue-target` | 6 | inspirations to keep queued |
| `--llm-concurrency` | 4 | max simultaneous LLM calls |
| `--solutions` | 50 | commits per inner loop (budget) |
| `--wall-clock` | ∞ | seconds per run |
| `--sandbox-timeout` | 300 | per `solve.sh` seconds |
| `--eval-timeout` | 300 | per evaluator seconds |
| `--eval-rounds` | 1 | outer evaluator co-evolution loops |
| `--sandbox` | local | `local` or `docker` backend |
| `--docker-image` | python:3.12-slim | for `--sandbox docker` |

## Layout of a run

```
run_out/
  hyra.log                    # structured run log
  report.json                 # best + stats + llm usage
  eb/index.json               # every committed solution
  eb/solutions/s0007/         # solution dir + run.log + meta.json + proposal.txt
```

## Honest limitations

- `local` sandbox is a fresh dir + rlimits, **not** a security boundary —
  solutions are model-generated code; use `--sandbox docker` (network off)
  or trusted infra for real runs.
- What Hyra's real prompts, EB internals, model choice and scale parameters
  are is NOT public — this reimplements the *described* architecture, not the
  proprietary system. Expect results to differ from Tencent's numbers.
