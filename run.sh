#!/usr/bin/env bash
# One-command OpenGirGit (Linux/macOS): create a virtualenv, install both
# requirement sets, start the API server and launch the overlay client.
#
#   ./run.sh                 # full stack (default)
#   ./run.sh --check         # validate prerequisites only (no installs, no start)
#   ./run.sh --no-server     # client only (uses OPENGIRGIT_SERVER_URL or client/.env)
#   ./run.sh --no-client     # server only
#
# Environment overrides: PYTHON, HOST, PORT, OPENGIRGIT_SERVER_URL, OPENGIRGIT_VENV.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${OPENGIRGIT_VENV:-$ROOT/.venv}"
PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
SERVER_URL="${OPENGIRGIT_SERVER_URL:-http://$HOST:$PORT}"

CHECK_ONLY=0
WITH_SERVER=1
WITH_CLIENT=1

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --no-server) WITH_SERVER=0 ;;
    --no-client) WITH_CLIENT=0 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "error: '$PYTHON' not found; install Python 3.10+ or set PYTHON=/path/to/python" >&2
  exit 1
}
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "error: Python 3.10+ is required (found $("$PYTHON" -V 2>&1))" >&2
  exit 1
}

echo "python:  $("$PYTHON" -V 2>&1)"
echo "venv:    $VENV"
[ "$WITH_SERVER" = 1 ] && echo "server:  $SERVER_URL"
[ "$WITH_CLIENT" = 1 ] && echo "client:  overlay"

if [ "$CHECK_ONLY" = 1 ]; then
  echo "check: OK"
  exit 0
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "creating virtualenv…"
  "$PYTHON" -m venv "$VENV"
fi
PY="$VENV/bin/python"
"$PY" -m pip install --quiet --upgrade pip

STAMP="$VENV/.requirements.sha256"
WANT="$(cat "$ROOT/server/requirements.txt" "$ROOT/client/requirements.txt" | { sha256sum 2>/dev/null || shasum -a 256; } | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  echo "installing dependencies (first run also fetches the faster-whisper wheel)…"
  "$PY" -m pip install --quiet -r "$ROOT/server/requirements.txt" -r "$ROOT/client/requirements.txt"
  printf '%s' "$WANT" > "$STAMP"
fi

SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "stopping server…"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [ "$WITH_SERVER" = 1 ]; then
  echo "starting API server…"
  (cd "$ROOT/server" && HOST="$HOST" PORT="$PORT" exec "$PY" run.py) &
  SERVER_PID=$!
  healthy=0
  for _ in $(seq 1 60); do
    if "$PY" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2).read()' \
        "$SERVER_URL/api/health" >/dev/null 2>&1; then
      healthy=1
      break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "error: the server exited during startup — see the output above" >&2
      exit 1
    fi
    sleep 0.5
  done
  if [ "$healthy" != 1 ]; then
    echo "error: server did not answer on $SERVER_URL/api/health" >&2
    exit 1
  fi
  echo "server ready: $SERVER_URL"
fi

if [ "$WITH_CLIENT" = 1 ]; then
  if [ ! -f "$ROOT/client/.env" ]; then
    printf 'OPENGIRGIT_SERVER_URL=%s\n' "$SERVER_URL" > "$ROOT/client/.env"
    echo "wrote client/.env (OPENGIRGIT_SERVER_URL=$SERVER_URL)"
  fi
  echo "starting client overlay…"
  (cd "$ROOT/client" && exec "$PY" main.py)
fi
