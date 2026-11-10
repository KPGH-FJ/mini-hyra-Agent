# Historical result recovery (2026-11-10)

59 missing paths restored byte-for-byte from public repository commit
`f416f535d7407cff7d185095b9d468e5cdb55bbf`, including their original file modes
and three internal relative symlinks. Exact provenance is in
`HISTORICAL_RECOVERY.json`. This restores historical/partial outputs, not a new
experiment or validated leaderboard. No old reader or benchmark implementation
was restored. No model API was called.

The three input datasets match official public LongMemEval oracle records exactly
(25/25, 13/13, 12/12). Hypothesis IDs and cache identities map to the same public
benchmark. A credential/private-data pattern scan found no secrets; such a scan
is not a general proof about arbitrary data. These are public benchmark-derived
artifacts, not user personal-memory records.

Some logs and hypotheses are partial. Do not infer complete run totals from them.
See each original experiment report and denominator before using its result.

## Upstream attribution

LongMemEval: https://github.com/xiaowu0162/LongMemEval

Public dataset: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned

Upstream MIT notice is preserved in `LONGMEMEVAL_LICENSE.txt` (copyright
2024 Di Wu). Benchmark records are public evaluation data; this is not a claim
that every story is synthetic. Model-generated cache/hypothesis contents are
experimental outputs, not independently verified facts.
