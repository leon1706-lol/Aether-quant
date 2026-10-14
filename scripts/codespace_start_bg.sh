#!/usr/bin/env bash
# (Re)start a background helper on the Codespace with a pid file, so it can be replaced without pkill -f matching ssh itself.
#   bash scripts/codespace_start_bg.sh <script path> <log path> <pid file> [script args...]
cd "$(dirname "$0")/.."
SCRIPT="${1:?script}"; LOG="${2:?log}"; PIDFILE="${3:?pid file}"
[ -f "${PIDFILE}" ] && kill "$(cat "${PIDFILE}")" 2> /dev/null
setsid nohup bash "${SCRIPT}" "${@:4}" > "${LOG}" 2>&1 &
echo $! > "${PIDFILE}"
echo "started ${SCRIPT} as pid $(cat "${PIDFILE}")"
