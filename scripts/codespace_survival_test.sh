#!/usr/bin/env bash
# Control experiment for "why do long background jobs die with SIGTERM": a sleeper and a CPU burner, started detached like the
# real jobs, each logging when it ends and how (exit status 143 = SIGTERM).
cd "$(dirname "$0")/.."
LOG=ml/survival.log
date -u +"%T start" > "${LOG}"
( sleep 1500; echo "$(date -u +%T) sleeper finished normally" >> "${LOG}" ) &
SLEEPER=$!
( python - <<'PY'
import time
end = time.time() + 1500
x = 0
while time.time() < end:
    x += 1
PY
echo "$(date -u +%T) burner finished normally status=$?" >> "${LOG}" ) &
BURNER=$!
wait ${SLEEPER}; echo "$(date -u +%T) sleeper wait status=$?" >> "${LOG}"
wait ${BURNER}; echo "$(date -u +%T) burner wait status=$?" >> "${LOG}"
