#!/usr/bin/env bash
# Stop running Signal Station backend + frontend.
# Tries graceful SIGTERM first, then SIGKILL if process still alive after 3s.
#
# Usage:
#   bash scripts/stop.sh           # stop default ports 8000/5173
#   bash scripts/stop.sh -p 8001   # stop backend on alternate port
#   bash scripts/stop.sh --all     # also kill orphan chromium processes
#
set -u

BACKEND_PORT=8000
FRONTEND_PORT=5173
KILL_CHROMIUM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port)
      BACKEND_PORT="$2"; shift 2 ;;
    -fp|--frontend-port)
      FRONTEND_PORT="$2"; shift 2 ;;
    --all)
      KILL_CHROMIUM=1; shift ;;
    -h|--help)
      sed -n '1,15p' "$0"; exit 0 ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ANSI colors
GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'

stop_port() {
  local port=$1
  local label=$2
  local pids
  pids=$(lsof -ti ":${port}" 2>/dev/null || true)
  if [[ -z "${pids}" ]]; then
    echo "${DIM}[${label}] no process on :${port}${RESET}"
    return 0
  fi
  echo "${YELLOW}[${label}] sending SIGTERM to ${pids} (port ${port})${RESET}"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  # Wait up to 3s for graceful shutdown
  for _ in 1 2 3; do
    sleep 1
    pids=$(lsof -ti ":${port}" 2>/dev/null || true)
    [[ -z "${pids}" ]] && break
  done
  if [[ -n "${pids}" ]]; then
    echo "${YELLOW}[${label}] still alive, sending SIGKILL${RESET}"
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
  echo "${GREEN}[${label}] stopped${RESET}"
}

stop_port "${BACKEND_PORT}" "backend"
stop_port "${FRONTEND_PORT}" "frontend"

if [[ "${KILL_CHROMIUM}" -eq 1 ]]; then
  # Only kill chromium spawned by Playwright (path contains 'playwright')
  pids=$(pgrep -f 'playwright.*chromium' 2>/dev/null || true)
  if [[ -n "${pids}" ]]; then
    echo "${YELLOW}[chromium] killing Playwright chromium pids: ${pids}${RESET}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
    echo "${GREEN}[chromium] stopped${RESET}"
  else
    echo "${DIM}[chromium] no playwright chromium process found${RESET}"
  fi
fi

echo "${GREEN}Done.${RESET}"
