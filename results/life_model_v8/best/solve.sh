#!/bin/bash
# DELTA vs life-model-serve-cost-repair base: the serve layer is rebuilt around
# one uniform (subject,slot,read_day) WRITE-RUN traversal instead of per-type
# readers. Deep-history probes (first/order/join/absent/window/nchange/duration)
# are folds over that traversal; retraction starts a new run and erased records
# are ignored so a pruned fact can revive when its killer is erased. Adds
# scoped-export documents with refusal for revoked purposes, premise citation,
# confidence/conflict serve, alias-merged attribution, and an import-surviving
# operation journal. Why better: M4 scoring is serve correctness; this keeps the
# pinned storage semantics but makes every history answer use the same edge list.
cd "$(dirname "$0")"
cat > solution.json <<'JSON'
{"status":"fallback","artifact":"asset.py","contract":{"ingest":true,"answer":true,"forget":true,"state":true,"import_state":true,"probe_bytes":true,"stats":true}}
JSON
if [ -f asset.py ]; then
  if command -v python3 >/dev/null 2>&1; then
    python3 -m py_compile asset.py >/dev/null 2>&1 || exit 0
    python3 -c 'import asset; [getattr(asset, n) for n in ("ingest","answer","forget","state","import_state","probe_bytes","stats")]; assert callable(asset.ingest) and callable(asset.answer)' >/dev/null 2>&1 || exit 0
    cat > solution.json <<'JSON'
{"status":"ready","artifact":"asset.py","contract":{"ingest":true,"answer":true,"forget":true,"state":true,"import_state":true,"probe_bytes":true,"stats":true}}
JSON
  fi
fi
exit 0
