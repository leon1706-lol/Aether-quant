#!/usr/bin/env bash
# Hold an ssh session open while any detached Codespace job runs (a Codespace idles out ~30 minutes after the last ssh
# session and takes its jobs with it). Run it through `gh codespace ssh` from the PC; it returns when no job is left.
#   bash scripts/codespace_keepalive.sh
PATTERN='codespace_session_|codespace_research_|codespace_run_tests|codespace_retrain_|pytest tests|train.py|train_multitask.py|train_sequence.py|v644_research.py|v650_|train_cross_sectional.py|build_holdout_dataset.py|codespace_lean_|lean backtest'
while pgrep -f "${PATTERN}" > /dev/null; do
  sleep 60
done
echo "no Codespace job left"
