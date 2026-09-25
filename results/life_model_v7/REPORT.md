# LifeModel P3 round 5 — M5 control evolution (run_v6) — report

- **Run**: `hyra run --task tasks/life_model --work run_v6 --solutions 100 --workers 4 --wall-clock 21600` (same EB across restarts; see "Run history" below)
- **Model**: Atria-Dawn-Preview via `https://api.atria-asi.ai/v1` (OpenAI-compatible, reasoning model)
- **Scored on**: HEAD `1969c09` (v8g bench — 22 probe types incl. isconf — plus streaming-LLM transport fix). All candidate scores below are from evals run on this HEAD.
- **Wall clock**: ~6 h active evolution (10:42–16:42 UTC) after transport fix; ~7 h dead time before it (see below).

## Headline

| entry | score | quality | cost_how | direction | parents |
|---|---|---|---|---|---|
| **s0045** | **140.900** | 141.00 | **measured** | exploit | s0035 |
| s0035 | 132.771 | 132.83 | measured | exploit | s0000 |
| s0043 | 88.949 | 89.17 | measured | fresh | — |
| s0000 (seed) | 42.571 | ~95.5 (v7 epoch) | reported | seed | — |
| s0021, s0040 | −1e9 | — | — | exploit / repair | malformed output |

**Best honest solution: s0045, score 140.900 — BEATS the v1 frontier (139.97).**
cost_how = `measured` (asset implements `state()` + `probe_bytes()`); cost = 14.2 KB asset + 370 KB probe bytes ≈ 0.1 pts deducted from quality 141.00.

## s0045 strategy (which control family won)

s0045 is an exploit on s0035's winning idea — **query-time indexing + a first-class operation journal** — pushed to full M5 control coverage:

- op journal (forget / forget_range / correct / revoke_purpose) embedded in `state()` so it **survives export→import** → `ops` 0.6→**1.0**, `expdeny` 1.0
- `revoke_purpose()` withdraws the consent view (data kept, view answers 已撤回) → `revoked` **1.0**, `purpose` **1.0**
- range/slot/about erasure **rebuilds live state from surviving edges** (rollback, not tombstones) → `cascade` **1.0**
- `correct()` as read-time self-assertion that supersedes live value + starves derived premises → `derive` 1.0, post-correction `state` .974
- premise fixpoint purging dead derived facts transitively; alias-canonicalised multi-entity hearsay; budgeted packing; honest byte metering.

Quality by probe type (s0045, quality=141.00):

| family | probe types | s0045 | s0035 | s0043 |
|---|---|---|---|---|
| **consent / export control** | revoked, purpose, expdeny, cascade | **1.0 / 1.0 / 1.0 / 1.0** | 1.0 / .979 / 1.0 / 1.0 | 1.0 / .354 / 1.0 / .5 |
| provenance / budget | prov, prov2, budget | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 | 1.0 / .2 / .167 |
| correction / retraction | correct→state, retract | 1.0 | 1.0 | 0.0 |
| op journal | ops | **1.0** | 0.6 | 0.6 |
| scoped export doc | partial | **0.0** | 0.0 | 0.0 |
| duration / change-count | duration, nchange | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / .333 |
| derived / conflict | derive, drvprov, isconf, conf | 1.0 / 0.0 / 0.0 / .429 | 1.0 / 0.0 / 0.0 / .143 | 1.0 / 0.0 / 0.0 / .429 |
| classic memory | state, stale, unans, as_of, subject, transfer | .974 / .963 / 1.0 / 1.0 / .062 / 1.0 | .842 / .926 / 1.0 / 1.0 / .188 / 1.0 | .513 / .352 / 1.0 / .111 / .5 / 0.0 |

**Read**: the winning family is **consent-scoped export/revocation + journaled control ops** — every consent/export/journal probe (revoked, purpose, expdeny, cascade, ops, prov2, budget, retract, derive) is at or near 1.0. The unsolved M5 remainder, consistent across ALL scored candidates: `partial` (scoped export **document** — 0.0 everywhere), `duration` leases (0.0), `nchange` audits (0.0), `drvprov` (0.0), `isconf` non-self conflict detection (0.0, new in v8g). Classic weak spot: `subject` (hearsay/alias answers) degraded to .062 on s0045 — the only regression vs s0035.

## EB stats (final)

- **Commits**: 46 total (1 seed + 45 proposals).
- **Scored**: 6 — s0045 **140.90**, s0035 132.77, s0043 88.95, s0000 42.57 (stale v7-epoch number), s0021/s0040 −1e9 (malformed assets).
- **Dead by cause** (40 total):
  - `HTTP 502` (pre-streaming era, non-streamed calls killed at ~4–5 min gateway timeout): 32
  - `HTTP 400` at max_tokens=131072 (cap-bound reasoning escalates 16k→32k→65k→131k, Atria rejects 131k): 3
  - `no solve.sh` (malformed proposal): 3
  - truncation-exhausted retries / evaluator error: 2
- **Throughput post-fix**: 14 commits in 6 h on 4 workers (~1 score/h). Bottleneck is now generation duration + cap-bound reasoning, not transport.

## Run history (why so few commits)

1. **03:42–10:30 — dead era**: Atria 502 wave killed every long non-streamed proposal generation (~4–5 min in-flight → 502); 32 dead commits, only the seed scored. workers=1 + a spaced prober proved it was call *duration*, not concurrency: isolated small calls passed all day while serialized big calls still 502'd (prober log: `run_v6/prober.log`).
2. **10:42 — transport fix shipped** (commit `1969c09`: `stream:true` + SSE aggregation in `hyra/llm.py`). Zero 502s after restart; streamed calls run 15–30 min cleanly.
3. **Post-fix failure mode**: the reasoning model burns the whole token cap on reasoning — `finish_reason=length` → cap doubles → "empty completion" (cap-bound reasoning-only output) or HTTP 400 at 131072. This is what limits the round to ~6 scored entries.

## Recommendation for the PI

- **M5 control semantics are evolvable and the frontier is beat**: consent/export/journal control family is at ~1.0. Next round should target the consistent zeros: `partial` (scoped export document — spec wants `state(scope={'slots':[...]})` returning an in-scope-only doc), `duration`, `nchange`, `drvprov`, `isconf`; plus the `subject` regression (.062).
- Harness tuning for this model: start `max_tokens` at 65536 (skip the doubling chain — a fix shipped mid-round would have doubled throughput) and cap below 131072 to avoid the 400 kills; consider a reasoning-effort param if the API supports one.
- Dashboard: `hyra serve --work run_v6 --port 8000` live throughout; preview URL reported to parent session.
