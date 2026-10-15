#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
if [[ "$ACTION" == "start" || "$ACTION" == "stop" || "$ACTION" == "restart" || "$ACTION" == "status" ]]; then
  shift || true
else
  ACTION="status"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

read_env_value() {
  local key="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi
  awk -F= -v key="$key" '
    $0 ~ /^[[:space:]]*#/ { next }
    index($0, key "=") == 1 {
      sub(/^[^=]*=/, "")
      sub(/\r$/, "")
      print
      exit
    }
  ' "$ENV_FILE"
}

HOST_ADDRESS="${HOST:-$(read_env_value HOST)}"
HOST_ADDRESS="${HOST_ADDRESS:-127.0.0.1}"
PORT_NUMBER="${PORT:-$(read_env_value PORT)}"
PORT_NUMBER="${PORT_NUMBER:-5050}"
DATA_DIR_VALUE="${DATA_DIR:-$(read_env_value DATA_DIR)}"
DATA_DIR_VALUE="${DATA_DIR_VALUE:-./data}"

case "$DATA_DIR_VALUE" in
  /*) DATA_DIR="$DATA_DIR_VALUE" ;;
  *) DATA_DIR="$PROJECT_ROOT/$DATA_DIR_VALUE" ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST_ADDRESS="$2"
      shift 2
      ;;
    --port)
      PORT_NUMBER="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

PYTHON_EXE="$PROJECT_ROOT/.venv/bin/python"
PID_FILE="$DATA_DIR/selfindex-service.pid"
MODE_FILE="$DATA_DIR/selfindex-service.mode"
STDOUT_LOG_FILE="$DATA_DIR/selfindex-service.out.log"
STDERR_LOG_FILE="$DATA_DIR/selfindex-service.err.log"

ensure_data_dir() {
  mkdir -p "$DATA_DIR"
}

managed_pid() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '\r\n[:space:]' < "$PID_FILE"
  fi
}

is_running_pid() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

is_managed_pid() {
  local pid="$1"
  if ! is_running_pid "$pid"; then
    return 1
  fi
  local command_line
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command_line" == *"$PYTHON_EXE"* && "$command_line" == *"-m app.service_main"* ]]
}

clear_stale_files() {
  rm -f "$PID_FILE" "$MODE_FILE"
}

port_listeners() {
  lsof -nP -iTCP:"$PORT_NUMBER" -sTCP:LISTEN 2>/dev/null || true
}

start_selfindex() {
  ensure_data_dir

  if [[ ! -x "$PYTHON_EXE" ]]; then
    echo "Python executable not found: $PYTHON_EXE" >&2
    echo "Create the virtual environment first, then run uv sync." >&2
    exit 1
  fi

  local pid
  pid="$(managed_pid || true)"
  if is_managed_pid "$pid"; then
    echo "SelfIndex already running on PID $pid."
    return
  fi
  if is_running_pid "$pid"; then
    echo "PID file points to another process ($pid); it will not be stopped." >&2
  fi
  clear_stale_files

  local listeners
  listeners="$(port_listeners)"
  if [[ -n "$listeners" ]]; then
    echo "Port $PORT_NUMBER already has listener(s):"
    echo "$listeners"
    echo "Stop the existing listener or choose another port with --port." >&2
    exit 1
  fi

  export PYTHONUNBUFFERED=1
  export PYTHONIOENCODING=utf-8
  export PYTHONUTF8=1
  export DEBUG="${DEBUG:-false}"
  export HOST="$HOST_ADDRESS"
  export PORT="$PORT_NUMBER"

  cd "$PROJECT_ROOT"
  nohup "$PYTHON_EXE" -m app.service_main >"$STDOUT_LOG_FILE" 2>"$STDERR_LOG_FILE" &
  local new_pid="$!"
  echo "$new_pid" > "$PID_FILE"
  echo "service" > "$MODE_FILE"

  echo "SelfIndex web service started on PID $new_pid."
  echo "Web: http://$HOST_ADDRESS:$PORT_NUMBER/"
  echo "Ingest: http://$HOST_ADDRESS:$PORT_NUMBER/api/ingest/browser-conversation"
  echo "Stdout log: $STDOUT_LOG_FILE"
  echo "Stderr log: $STDERR_LOG_FILE"
}

stop_selfindex() {
  local pid
  pid="$(managed_pid || true)"
  if is_running_pid "$pid" && ! is_managed_pid "$pid"; then
    echo "PID file points to another process ($pid); refusing to stop it." >&2
    exit 1
  fi
  if ! is_managed_pid "$pid"; then
    clear_stale_files
    echo "No managed SelfIndex service was running."
    return
  fi

  echo "Stopping SelfIndex PID $pid..."
  kill "$pid"
  for _ in {1..30}; do
    if ! is_running_pid "$pid"; then
      clear_stale_files
      echo "SelfIndex stopped."
      return
    fi
    sleep 0.2
  done

  echo "SelfIndex did not stop in time; no forced kill was sent. Inspect the process before retrying." >&2
  exit 1
}

show_status() {
  ensure_data_dir

  local pid
  pid="$(managed_pid || true)"
  if is_managed_pid "$pid"; then
    echo "Managed SelfIndex is running."
    echo "PID: $pid"
    if [[ -f "$MODE_FILE" ]]; then
      echo "Mode: $(head -n 1 "$MODE_FILE")"
    fi
  else
    if is_running_pid "$pid"; then
      echo "Stale PID file points to another process ($pid); no signal was sent." >&2
    fi
    clear_stale_files
    echo "Managed SelfIndex is not running."
  fi

  local listeners
  listeners="$(port_listeners)"
  if [[ -n "$listeners" ]]; then
    echo "Port $PORT_NUMBER listeners:"
    echo "$listeners"
  else
    echo "Port $PORT_NUMBER has no listeners."
  fi

  echo "Expected web URL: http://$HOST_ADDRESS:$PORT_NUMBER/"
  echo "Expected ingest URL: http://$HOST_ADDRESS:$PORT_NUMBER/api/ingest/browser-conversation"
  echo "Stdout log: $STDOUT_LOG_FILE"
  echo "Stderr log: $STDERR_LOG_FILE"
}

case "$ACTION" in
  start)
    start_selfindex
    ;;
  stop)
    stop_selfindex
    ;;
  restart)
    stop_selfindex
    sleep 0.7
    start_selfindex
    ;;
  status)
    show_status
    ;;
esac
