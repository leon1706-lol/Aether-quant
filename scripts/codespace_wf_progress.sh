#!/usr/bin/env bash
# Walk-forward progress: uptime, window markers, liveness of the trainer.
cd "$(dirname "$0")/.."
uptime -p; date -u +%T
grep -E 'walk-forward window [0-9]+/[0-9]+ backtest MCC' ml/retrain_v580cs20261012_walk_forward.log | tail -3 | cut -c1-140
grep -E 'walk-forward window [0-9]+/[0-9]+:' ml/retrain_v580cs20261012_walk_forward.log | tail -1 | cut -c1-170
pgrep -f 'train.py' | head -2
free -m | sed -n 2p
