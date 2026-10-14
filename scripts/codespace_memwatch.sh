#!/usr/bin/env bash
# Samples machine memory and the biggest process every 3 s into ml/memwatch.log until ml/memwatch.stop exists - the trace to
# read when a trainer is SIGTERM'd (the kill leaves no OOM line).
cd "$(dirname "$0")/.."
rm -f ml/memwatch.stop
while [ ! -f ml/memwatch.stop ]; do
  avail=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
  top=$(ps -eo rss=,comm= --sort=-rss | head -1 | awk '{printf "%dMB %s", $1/1024, $2}')
  echo "$(date -u +%T) avail=${avail}MB top=${top}"
  sleep 3
done
