#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_LOG="${RUN_DIR}/backend.log"
FRONTEND_LOG="${RUN_DIR}/frontend.log"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-4173}"
BACKEND_RELOAD="${BACKEND_RELOAD:-1}"

mkdir -p "${RUN_DIR}"

if [[ -f "${BACKEND_PID_FILE}" ]] && kill -0 "$(cat "${BACKEND_PID_FILE}")" 2>/dev/null; then
  echo "Backend already running (PID $(cat "${BACKEND_PID_FILE}"))."
else
  (
    cd "${ROOT_DIR}/backend"
    if [[ ! -f ".venv/bin/activate" ]]; then
      echo "ERROR: backend/.venv not found. Please create venv and install dependencies first."
      exit 1
    fi
    source .venv/bin/activate
    reload_args=()
    if [[ "${BACKEND_RELOAD}" == "1" ]]; then
      reload_args+=(--reload)
    fi
    nohup uvicorn main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" "${reload_args[@]}" >"${BACKEND_LOG}" 2>&1 &
    echo $! >"${BACKEND_PID_FILE}"
  )
  sleep 1
  if kill -0 "$(cat "${BACKEND_PID_FILE}")" 2>/dev/null; then
    echo "Backend started on http://${BACKEND_HOST}:${BACKEND_PORT} (PID $(cat "${BACKEND_PID_FILE}"))."
  else
    echo "Backend failed to start. Check log: ${BACKEND_LOG}"
    tail -n 20 "${BACKEND_LOG}" || true
    rm -f "${BACKEND_PID_FILE}"
  fi
fi

if [[ -f "${FRONTEND_PID_FILE}" ]] && kill -0 "$(cat "${FRONTEND_PID_FILE}")" 2>/dev/null; then
  echo "Frontend already running (PID $(cat "${FRONTEND_PID_FILE}"))."
else
  (
    cd "${ROOT_DIR}/frontend"
    nohup python3 -m http.server "${FRONTEND_PORT}" >"${FRONTEND_LOG}" 2>&1 &
    echo $! >"${FRONTEND_PID_FILE}"
  )
  sleep 1
  if kill -0 "$(cat "${FRONTEND_PID_FILE}")" 2>/dev/null; then
    echo "Frontend started on http://127.0.0.1:${FRONTEND_PORT} (PID $(cat "${FRONTEND_PID_FILE}"))."
  else
    echo "Frontend failed to start. Check log: ${FRONTEND_LOG}"
    tail -n 20 "${FRONTEND_LOG}" || true
    rm -f "${FRONTEND_PID_FILE}"
  fi
fi

echo ""
echo "Logs:"
echo "  backend : ${BACKEND_LOG}"
echo "  frontend: ${FRONTEND_LOG}"
echo ""
echo "Open: http://127.0.0.1:${FRONTEND_PORT}"
