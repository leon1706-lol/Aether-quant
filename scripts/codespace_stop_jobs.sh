#!/usr/bin/env bash
# Stop the detached Codespace jobs (session / research scripts, side-cars and the trainers they started); keeps all disk state.
#   bash scripts/codespace_stop_jobs.sh [tag]   # tag only selects which session log to tail
cd "$(dirname "$0")/.."
TAG="${1:-}"
PATTERN='train_multitask.py|train_sequence.py|train.py|codespace_session_|codespace_research_|codespace_stage_b_resume|codespace_wf_cleaner|codespace_memwatch'
for f in ml/*.pid; do
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null
done
sleep 1
for pid in $(pgrep -f "$PATTERN"); do
  [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
done
sleep 3
echo "remaining job processes: $(pgrep -f "$PATTERN" | wc -l)"
if [ -n "$TAG" ]; then
  for log in ml/*"${TAG}"*.log; do
    [ -f "$log" ] && { echo "== $log"; tail -2 "$log" | cut -c1-160; }
  done
fi
df -h /workspaces | tail -1
