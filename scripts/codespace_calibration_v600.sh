#!/usr/bin/env bash
# V6.0.0: R-CAL (scripts/lean_calibration.py) on the Codespace: the 4 GB dev PC cannot score the 90k-row backtest+holdout
# frame next to its own processes. Needs the two V5.8.0 Lean run folders and their book-history files unpacked first
# (tar of backtests/<run> without code/ + visualization/book_history/<id>.jsonl).
#
#   bash scripts/codespace_calibration_v600.sh [dataset]     default ml/datasets/v600_full_dataset.csv
set -uo pipefail
cd "$(dirname "$0")/.."
DATASET="${1:-ml/datasets/v600_full_dataset.csv}"
mkdir -p ml/evaluation/v600
exec > >(tee -a ml/evaluation/v600/calibration_codespace.log) 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
step "R-CAL on ${DATASET}"
python scripts/lean_calibration.py --dataset "${DATASET}" \
  --window "bt1=backtests/2026-10-13_17-54-47@2023-07-01..2025-06-30:backtest" \
  --window "bt2_backtest=backtests/2026-10-14_07-27-32@2023-07-01..2025-06-30:backtest+holdout" \
  --window "bt2_holdout=backtests/2026-10-14_07-27-32@2025-07-01..2026-09-30:backtest+holdout" \
  --out ml/evaluation/v600/calibration.json
step "DONE"
