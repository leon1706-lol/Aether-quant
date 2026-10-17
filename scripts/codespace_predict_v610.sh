#!/usr/bin/env bash
# V6.1.0: the V6.1 simulator's prediction for BT1 (whole span, the FINAL config pushed with -Mode push -CodeOnly), written BEFORE
# the Lean run so R-CAL2's out-of-sample check cannot be fitted after the fact.
#   bash scripts/codespace_predict_v610.sh [legacy probability csv]
set -uo pipefail
cd "$(dirname "$0")/.."
LEGACY="${1:-ml/datasets/legacy_probability.csv}"
mkdir -p ml/evaluation/v610
python scripts/lean_calibration.py --predict --dataset ml/datasets/v610_full_dataset.csv --legacy-probability "${LEGACY}" \
  --gate-warmup-days 400 --window "bt1=@2023-07-01..2026-09-30:backtest+holdout" --out ml/evaluation/v610/bt1_prediction.json
