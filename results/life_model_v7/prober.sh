#!/bin/bash
# Spaced single-call prober: one small completion every 20 min.
# Logs ts, http_code, total_time to run_v6/prober.log
cd /home/ubuntu/repos/mini-hyra-Agent
while true; do
  line=$(curl -s -o /tmp/probe_body.json -w "%{http_code} %{time_total}s" -X POST \
    "https://api.atria-asi.ai/v1/chat/completions" \
    -H "Authorization: Bearer $ATRIA_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"Atria-Dawn-Preview","messages":[{"role":"user","content":"Reply with the single word: ok"}],"max_tokens":16}')
  echo "$(date -u +%H:%M:%S) code=${line}" >> run_v6/prober.log
  sleep 1200
done
