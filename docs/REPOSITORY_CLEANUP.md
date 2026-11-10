# Repository cleanup and historical recovery

Completed 2026-11-10. `main` is the only ongoing branch. PRs #104, #105 and #106
are merged; source histories remain available through main where applicable.
The final status-document PR uses a temporary branch that will be removed after merge.

## What was preserved

- 93 refs (including the integration branch) were exact ancestors of main and
  had no associated unmerged PR or explicit active-work evidence at cleanup.
  Their commits remain recoverable from main.
- Ten other historical heads had equivalent/incorporated content or superseded
  implementations. All formerly missing 59 artifact paths had already been
  recovered with exact blobs/modes. Their original commit identities and full
  histories were additionally saved to the owner's Space before deleting refs.
- No `ours` history merge, force-push, release publication, paid experiment,
  deployment or deletion of the separate research workspace was performed.

Original branch names/heads: `BRANCH_INVENTORY.json`.
Per-branch differences: `HISTORICAL_BRANCH_REVIEW.md`.
Public artifact provenance: `../results/HISTORICAL_RECOVERY.json`.

## Space archive

Filename: `hyra-historical-ten-heads-20261110.bundle`

Size: 12,938,674 bytes.

SHA-256: `061ee669a58ea96409723cf7a4a544ec21b4a50686d7ba222e7071f11afb4095`

The file was saved to the owner's Space, downloaded again through the supported
file flow, and independently restored into a new bare repository. Verification
covered all ten exact commit/tree identities and recursive entries, 1,896 unique
blobs rehashed and byte-compared, and full strict Git fsck. All current remote
heads were rechecked against the archive before deletion. Keep the Space file;
the historical non-ancestor heads are intentionally no longer branch refs.

The archive is private to its owner; this public document does not grant access
or expose a private download link. It contains complete histories, with no
prerequisite repository required.

## Restore when needed

Download the file from the owner's Space. Replace the example path below with
its actual path, and use a new empty destination directory:

```sh
sha256sum /path/to/hyra-historical-ten-heads-20261110.bundle
git init --bare restored-hyra.git
git -C restored-hyra.git bundle verify /path/to/hyra-historical-ten-heads-20261110.bundle
git -C restored-hyra.git fetch /path/to/hyra-historical-ten-heads-20261110.bundle \
  '+refs/remotes/origin/*:refs/heads/*'
git -C restored-hyra.git fsck --full --strict
```

This restores the original ten branch histories locally. Do not blindly restore
old implementations over current main; use the audit to select the historical
experiment or code state you need. The archive does not authorize new model
spending or use of real personal data.
