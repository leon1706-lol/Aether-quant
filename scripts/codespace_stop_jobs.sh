#!/usr/bin/env bash
# Stop the detached retrain side-cars (resume script, cleaner, memwatch) and any trainer they started; keeps all disk state.
cd "$(dirname "$0")/.."
for f in ml/stage_b_resume.pid ml/wf_cleaner.pid ml/memwatch.pid; do
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null
done
sleep 1
for pid in $(pgrep -f 'train.py|train_sequence|codespace_stage_b_resume|codespace_wf_cleaner|codespace_memwatch'); do
  [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
done
sleep 3
echo "remaining trainer processes: $(pgrep -f 'train.py|train_sequence' | wc -l)"
ls ml/versions/walk-forward-633816f4-8736-4724-9c4f-b69b3ccc0a61
grep -E 'walk-forward window [0-9]+/[0-9]+ backtest MCC' ml/retrain_v580cs20261012_walk_forward.log | tail -2 | cut -c1-120
df -h /workspaces | tail -1
