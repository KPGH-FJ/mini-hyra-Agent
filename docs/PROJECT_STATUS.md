# Project status and canonical entry points

Status date: 2026-11-10. This is a repository integration record, not a live job monitor.

## One project, distinct responsibilities

| Concern | Canonical source / entry |
|---|---|
| Install metadata | `pyproject.toml` (`setup.py` delegates to it) |
| Research harness CLI | `hyra` = `python -m hyra` = `python -m hyra.cli` |
| Memory system API | `from lifemodel import LifeModel` |
| Synthetic evaluation | `tests/test_lifemodel_contract.py`, `tests/test_bench_sweep.py` |
| External dataset adapters | `tasks/life_model/external/lme.py`, `locomo.py` |
| Current dashboard progress | `research.json` → `current` |
| Historical research | `research.json` → timeline, `results/INDEX.md` |
| Run-specific execution state | `<work>/report.json`, `<work>/eb/index.json`, `<work>/hyra.log` |

The dashboard reads `<work>/research.json` first, then the current directory's
`research.json`. An old run may therefore intentionally display its own historical
research snapshot. Start from the repository root and use a fresh work directory
for the current repository overview. A progress label is not proof of a running job.

## Integration status

This consolidation is based on main `17bd657` plus source PRs #104
(typed records) and #105 (evaluation/control/temporal repairs). Neither PR's
historical acceptance claims replace independent verification of the final combined
code. Local integration validation is recorded in `docs/INTEGRATION_VALIDATION.md`.

Historical branches and results must be preserved before branch pruning. Do not
restore obsolete reader implementations merely to recover experiment artifacts.
`docs/BRANCH_INVENTORY.json`, when present, records pre-cleanup branch heads and
preservation decisions. Git history remains the record of earlier implementations.

## Evidence and comparison rules

- The old LifeStream v9/v9.1 tables remain historical. The later
  `record-grounded-v1` oracle changes gold and coverage: 78,551 and 79,289 probes
  are different denominators and must not be presented as a model improvement.
- LME/LoCoMo results use different datasets, slices, routes and judges. Read the
  linked report and saved per-question evidence before comparing percentages.
- The selected seven-question canonical-frame/spec experiment is diagnostic,
  not a held-out full-benchmark or production success rate.
- A successful deterministic test does not verify LLM extraction, untrusted
  candidate isolation, deployed persistence, privacy, or large legacy replay cost.
- Workspace-only later research is not implicitly published here. Import only
  reviewed, public-safe artifacts with provenance and applicable authorization.

## Run safely

Install with `python -m pip install -e .`. The wheel installs `hyra` and `lifemodel`;
tasks and saved experiments need a repository checkout. No external API is required
for the offline commands in README. External adapters and non-mock harness runs
can incur model charges and are not part of default verification.

`local` sandbox mode is not a security boundary. Do not run untrusted candidates
with credentials or personal data. Real personal-data validation requires separate
scope, purpose and retention authorization; see `P4_READINESS.md` for the planning
checklist, not a claim that readiness is established.
