#!/bin/bash
# Start Ollama, the API/admin UI and the DLP proxy; enable the system proxy; clean up on exit.
# Usage: scripts/run.sh            (add --no-system-proxy to keep the system proxy untouched)
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCRIPTS="$ROOT/scripts"
PIDS=()
cleanup() {
  [[ "${SYSPROXY:-1}" == 1 ]] && "$SCRIPTS/dlp-off.sh"
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
}
trap cleanup EXIT INT TERM
[[ "${1:-}" == "--no-system-proxy" ]] && SYSPROXY=0

if ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  ollama serve >"$ROOT/data/ollama.log" 2>&1 & PIDS+=($!)
  sleep 2
fi
[[ -f "$ROOT/frontend/dist/index.html" ]] || (cd "$ROOT/frontend" && npm run build)
cd "$ROOT/backend"
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 & PIDS+=($!)
uv run mitmdump -q -s proxy/guard.py --listen-host 127.0.0.1 -p 8080 --set termlog_verbosity=info & PIDS+=($!)
sleep 2
[[ "${SYSPROXY:-1}" == 1 ]] && "$SCRIPTS/dlp-on.sh"
echo "Admin UI: http://127.0.0.1:8000   (Ctrl+C to stop and restore network settings)"
wait
