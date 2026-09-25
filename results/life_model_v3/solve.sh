#!/bin/bash
cd "$(dirname "$0")"
mkdir -p .run
# evaluator-driven protocol: asset.py is imported by evaluate.py;
# solve.sh only sanity-checks that it imports.
python3 -c "import asset; print('asset ok')" > .run/check.log 2>&1 || true
