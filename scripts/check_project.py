"""Offline, read-only consistency checks. Run from any working directory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path = ROOT) -> list[str]:
    errors = []
    status = json.loads((root / "research.json").read_text())
    metadata = status.get("status_metadata", {})
    for key in ("status_document", "results_index"):
        path = metadata.get(key)
        if not path or not (root / path).is_file():
            errors.append(f"missing {key}: {path}")
    if metadata.get("current_is_live_monitor") is not False:
        errors.append("repository progress must not claim live-job monitoring")
    index = json.loads((root / "results/catalog.json").read_text())
    expected = sorted(str(p.relative_to(root)) for p in (root / "results").rglob("*.md")
                      if "report" in p.name.lower() or "summary" in p.name.lower())
    actual = [row["path"] for row in index["reports"]]
    if actual != expected:
        errors.append("report catalog differs from files; regenerate with scripts/index_results.py")
    for row in index["reports"]:
        path = root / row["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            errors.append(f"report content changed: {row['path']}")
    inventory = json.loads((root / "docs/BRANCH_INVENTORY.json").read_text())
    names = [row["branch"] for row in inventory["branches"]]
    if not all(names) or len(names) != len(set(names)) or "main" in names:
        errors.append("branch inventory must contain distinct nonempty non-main names")
    recovery = json.loads((root / "results/HISTORICAL_RECOVERY.json").read_text())
    for row in recovery["files"]:
        path = root / row["path"]
        if not path.exists() and not path.is_symlink():
            errors.append(f"missing historical artifact: {row['path']}")
            continue
        data = str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
        mode = "120000" if path.is_symlink() else ("100755" if path.stat().st_mode & 0o111 else "100644")
        digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if digest != row["blob_sha"] or mode != row["mode"]:
            errors.append(f"historical artifact differs from provenance: {row['path']}")
    return errors


if __name__ == "__main__":
    errors = check()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Project consistency: {'FAILED' if errors else 'passed'}")
    raise SystemExit(bool(errors))
