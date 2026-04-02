#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"

stop_by_pid_file() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "${pid_file}" ]]; then
    echo "${name}: not running (pid file missing)."
    return
  fi

  local pid
  pid="$(cat "${pid_file}")"
  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    echo "${name}: stopped PID ${pid}."
  else
    echo "${name}: stale pid file (PID ${pid} not found)."
  fi
  rm -f "${pid_file}"
}

stop_by_pid_file "Backend" "${BACKEND_PID_FILE}"
stop_by_pid_file "Frontend" "${FRONTEND_PID_FILE}"
