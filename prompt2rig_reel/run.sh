#!/usr/bin/env bash
# Starts the web app and (if set up) the HQ worker; Ctrl+C stops both.
#   ./run.sh          app + HQ worker
#   ./run.sh --live   app only (Tier 0)
cd "$(dirname "$0")" && source ./config.sh
cd "$REPO"
pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
  # mintty does not always forward the signal to native Windows processes
  [ -n "$wpid" ] && taskkill //F //T //PID "$wpid" >/dev/null 2>&1; exit; }
trap cleanup INT TERM EXIT
node server.mjs & pids+=($!)
if [ "$1" != --live ] && [ -f hq/.venv/Scripts/python.exe ]; then
  PYTHONUNBUFFERED=1 hq/.venv/Scripts/python hq/worker.py & pids+=($!)
  wpid=$(cat /proc/$!/winpid 2>/dev/null)
  echo "HQ worker starting (first load takes a while; the hq pill turns green when ready)"
fi
sleep 1; echo "open http://localhost:5177"
cmd //c start "" http://localhost:5177 2>/dev/null || true
wait
