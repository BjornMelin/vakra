#!/usr/bin/env bash
# Start a local Arize Phoenix collector + UI in a detached tmux session.
#
#   capstone/observability/start_phoenix.sh          # start (idempotent)
#   capstone/observability/start_phoenix.sh status
#   capstone/observability/start_phoenix.sh stop
#
# Phoenix binds to 127.0.0.1 only; view it from your laptop with an SSH tunnel:
#   ssh -N -L 6006:127.0.0.1:6006 <user>@<droplet>   then open http://localhost:6006
#
# Environment (all optional):
#   PHOENIX_VENV          venv for the server        (default /scratch/phoenix/.venv)
#   PHOENIX_WORKING_DIR   sqlite db + artifacts      (default /scratch/phoenix/data)
#   PHOENIX_PORT          HTTP UI + OTLP/HTTP port   (default 6006)
#   PHOENIX_GRPC_PORT     OTLP/gRPC port             (default 4317)
#   PHOENIX_SESSION       tmux session name          (default phoenix)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PHOENIX_VENV=${PHOENIX_VENV:-/scratch/phoenix/.venv}
export PHOENIX_WORKING_DIR=${PHOENIX_WORKING_DIR:-/scratch/phoenix/data}
export PHOENIX_HOST=127.0.0.1
export PHOENIX_PORT=${PHOENIX_PORT:-6006}
export PHOENIX_GRPC_PORT=${PHOENIX_GRPC_PORT:-4317}
SESSION=${PHOENIX_SESSION:-phoenix}
LOG="$PHOENIX_WORKING_DIR/phoenix.log"

is_up() { curl -fsS -o /dev/null "http://127.0.0.1:$PHOENIX_PORT/healthz" 2>/dev/null; }

case "${1:-start}" in
  status)
    if is_up; then echo "phoenix up on 127.0.0.1:$PHOENIX_PORT"; else echo "phoenix down"; exit 1; fi
    exit 0 ;;
  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "stopped" || echo "not running"
    exit 0 ;;
  start) ;;
  *) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

command -v tmux >/dev/null || { echo "tmux is required" >&2; exit 1; }
if is_up; then echo "phoenix already up on 127.0.0.1:$PHOENIX_PORT"; exit 0; fi

mkdir -p "$PHOENIX_WORKING_DIR"
if [[ ! -x "$PHOENIX_VENV/bin/phoenix" ]]; then
  echo "creating $PHOENIX_VENV"
  if command -v uv >/dev/null; then
    uv venv -q -p 3.12 "$PHOENIX_VENV"
    uv pip install -q --python "$PHOENIX_VENV/bin/python" -r "$HERE/requirements-phoenix-server.txt"
  else
    python3 -m venv "$PHOENIX_VENV"
    "$PHOENIX_VENV/bin/pip" install -q -r "$HERE/requirements-phoenix-server.txt"
  fi
fi

tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"
tmux new-session -d -s "$SESSION" \
  "PHOENIX_WORKING_DIR='$PHOENIX_WORKING_DIR' PHOENIX_HOST=$PHOENIX_HOST PHOENIX_PORT=$PHOENIX_PORT \
   PHOENIX_GRPC_PORT=$PHOENIX_GRPC_PORT '$PHOENIX_VENV/bin/phoenix' serve 2>&1 | tee -a '$LOG'"

for _ in $(seq 1 60); do
  if is_up; then
    echo "phoenix up: UI + OTLP/HTTP at http://127.0.0.1:$PHOENIX_PORT (traces: /v1/traces), log $LOG"
    echo "tunnel: ssh -N -L $PHOENIX_PORT:127.0.0.1:$PHOENIX_PORT <user>@<droplet>"
    exit 0
  fi
  sleep 1
done
echo "phoenix did not become healthy in 60s; see $LOG or: tmux attach -t $SESSION" >&2
exit 1
