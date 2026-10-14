#!/usr/bin/env bash
# One-shot diagnosis of a dead Codespace job: uptime (a VM restart kills nohup jobs), memory, kernel OOM lines, helpers, log tail.
cd "$(dirname "$0")/.."
echo "uptime: $(uptime -p) (since $(uptime -s))"; date -u +%FT%TZ
free -m | sed -n 1,2p; df -h /workspaces | tail -1
echo "--- oom / killed lines"; (dmesg 2> /dev/null | grep -i 'killed process\|out of memory' | tail -5) || true
echo "--- processes"; pgrep -af 'python|retrain|cleaner' | cut -c1-120
echo "--- log tail"; tail -n 12 "$(ls -t ml/retrain_*_b.log | head -1)" | cut -c1-200
