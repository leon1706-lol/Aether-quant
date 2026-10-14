#!/usr/bin/env bash
# Where does the Codespace's memory go? (the external killer fires when MemAvailable gets low)
grep -E 'MemTotal|MemFree|MemAvailable|^Cached|Shmem:|Slab|SReclaimable|SUnreclaim|AnonPages|Mapped' /proc/meminfo
echo "--- tmpfs"; df -h /tmp /dev/shm 2> /dev/null | tail -n 3
echo "--- top rss (all visible)"; ps -eo pid,rss,comm --sort=-rss 2> /dev/null | head -8
echo "--- sum rss MB: $(ps -eo rss= | awk '{s+=$1} END {printf "%d", s/1024}')"
echo "--- uptime $(uptime -p)"
