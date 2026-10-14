#!/usr/bin/env bash
# Is the V5.8.0 walk-forward finished, and what did the stage-B script leave behind?
cd "$(dirname "$0")/.."
RUN=ml/versions/walk-forward-633816f4-8736-4724-9c4f-b69b3ccc0a61
date -u +%FT%TZ
ls -la --time-style=+%F_%T "$RUN" | grep -v '^total' | grep -v 'window_' | cut -c1-120
echo "--- datasets"; ls -la --time-style=+%F_%T ml/datasets | grep -v '^total' | cut -c1-120
echo "--- trainers running: $(pgrep -f 'train.py|build_holdout_dataset' | wc -l)"
echo "--- stage B log tail"; grep -v 'PerformanceWarning\|dataset\[column_name\]' ml/retrain_v580cs20261012_walk_forward.log | tail -n 5 | cut -c1-200
echo "--- stage_b_resume.log tail"; grep -v 'PerformanceWarning\|dataset\[column_name\]' ml/stage_b_resume.log | tail -n 5 | cut -c1-200
