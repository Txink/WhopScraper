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
GREEN=$'\033[32m'; YELLOW=$'\033[33m'; CYAN=$'\033[36m'; DIM=$'\033[2m'; RESET=$'\033[0m'

# Render PID as `<pid> <truncated-command>`. Falls back gracefully if ps fails.
describe_pid() {
  local pid=$1
  # macOS ps: -o pid=,command= → no header; truncate command for readability.
  local row
  row=$(ps -p "${pid}" -o pid=,command= 2>/dev/null | sed -E 's/^[[:space:]]+//') || row=""
  if [[ -z "${row}" ]]; then
    echo "  • ${pid}  ${DIM}(already gone)${RESET}"
    return
  fi
  # Trim any duplicate pid prefix the ps already added
  local cmd="${row#${pid} }"
  # Limit command width so output stays readable
  local max=110
  if [[ ${#cmd} -gt ${max} ]]; then
    cmd="${cmd:0:max}…"
  fi
  echo "  • ${CYAN}${pid}${RESET}  ${cmd}"
}

stop_port() {
  local port=$1
  local label=$2
  local pids
  pids=$(lsof -ti ":${port}" 2>/dev/null || true)
  if [[ -z "${pids}" ]]; then
    echo "${DIM}[${label}] no process on :${port}${RESET}"
    return 0
  fi
  local count
  count=$(echo "${pids}" | wc -l | tr -d ' ')
  echo "${YELLOW}[${label}] :${port} → killing ${count} process(es):${RESET}"
  for pid in ${pids}; do
    describe_pid "${pid}"
  done
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  # Wait up to 3s for graceful shutdown
  for _ in 1 2 3; do
    sleep 1
    pids=$(lsof -ti ":${port}" 2>/dev/null || true)
    [[ -z "${pids}" ]] && break
  done
  if [[ -n "${pids}" ]]; then
    echo "${YELLOW}[${label}] still alive, escalating to SIGKILL:${RESET}"
    for pid in ${pids}; do
      describe_pid "${pid}"
    done
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
    count=$(echo "${pids}" | wc -l | tr -d ' ')
    echo "${YELLOW}[chromium] killing ${count} Playwright chromium process(es):${RESET}"
    for pid in ${pids}; do
      describe_pid "${pid}"
    done
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
