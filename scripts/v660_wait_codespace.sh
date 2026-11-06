#!/usr/bin/env bash
# Polls the Codespace job from the PC every 9 minutes (each poll also keeps the idle timeout away) until it finishes or stops.
# usage: bash scripts/v660_wait_codespace.sh <codespace> [pattern, default ALL_DONE]
CODESPACE="$1"
PATTERN="${2:-ALL_DONE}"
while true; do
  status="$(gh codespace ssh -c "${CODESPACE}" "cat /tmp/aq_v660/status 2>/dev/null; pgrep -f 'v660_codespace_' > /dev/null && echo RUNNING || echo STOPPED" 2>/dev/null | tr -d '\r')"
  if echo "${status}" | grep -q "${PATTERN}"; then
    echo "${status}"
    exit 0
  fi
  if echo "${status}" | grep -q "^STOPPED"; then
    echo "${status}"
    exit 1
  fi
  python -c "import time; time.sleep(540)"
done
