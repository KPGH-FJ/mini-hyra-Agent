# Historical branch review

Baseline: main `17bd65751708f2d1509d72ff280db68b87fb3d03`, checked 2026-11-10.
No branch was deleted or synthetically merged to manufacture ancestry. Full names
and original heads are recorded in `BRANCH_INVENTORY.json`.

## Ten non-ancestor historical branches (excluding PRs #104/#105)

| Branch | Content disposition | Residual risk |
|---|---|---|
| `devin/1790738840-assist-param` | Unique merge commit only; no net changes from merge base | Author/activity not established |
| `results/lifemodel-locomo-fixstack` | Unique merge commit only; no net changes from merge base | Author/activity not established |
| `devin/1791334815-stage3-spec-gen` | Sole commit patch-equivalent in main; ten files identical, four evolved later | Preserve original commit provenance |
| `devin/1790858592-research-v12` | v12 research object already exactly in main | Do not duplicate timeline |
| `devin/1791013887-grounded-cal` | Corrected v14 object already exactly in main | Do not restore unsupported earlier projection |
| `devin/1790614556-reader-personal` | Gate-all patch equivalent; strict premise code superseded by relaxed/synthesis evolution | Do not silently reinstate older gate semantics |
| `results/lifemodel-reexam-150` | 334 exact files; seven missing artifacts restored; three code files evolved | Preserve original code history, not old code in current tree |
| `results/m4-agg-refine` | 40 exact files; 59 missing artifacts restored; three code files evolved | Partial outputs must not become full-run claims |
| `results/m4-answering-agg` | 361 exact files; 59 missing artifacts restored; three code files evolved | Same partial-evidence limitation |
| `results/m4-retrieval-completeness` | 13 exact files; seven missing artifacts restored; three code files evolved | Same provenance/history limitation |

The missing artifact sets overlap: there are 59 distinct paths, not 132. All
were recovered from `f416f535d7407cff7d185095b9d468e5cdb55bbf`, with exact blob
and mode identities in `results/HISTORICAL_RECOVERY.json`. Public-safety and
upstream provenance checks are in `results/HISTORICAL_RECOVERY_REVIEW.json`.

The 90 remaining non-main historical heads are ancestors of baseline main.
That establishes content/history recovery through main, not that collaborators
have ceased work. No blanket branch deletion is justified by this check alone.
