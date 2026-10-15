#!/usr/bin/env bash
# V6.0.0: the calibrated simulator's prediction of the final config over the Lean window, written BEFORE BT1 runs (R-CAL's
# out-of-sample check). Runs on the Codespace (the 90k-row backtest + holdout frame does not fit the 4 GB dev PC).
#
#   bash scripts/codespace_predict_v600.sh [dataset]       default ml/datasets/v600_full_dataset.csv
set -uo pipefail
cd "$(dirname "$0")/.."
DATASET="${1:-ml/datasets/v600_full_dataset.csv}"
mkdir -p ml/evaluation/v600
exec > >(tee -a ml/evaluation/v600/predict_codespace.log) 2>&1
echo "=== $(date -u +%FT%TZ) config sha256 $(sha256sum config.json | cut -d' ' -f1)"
python scripts/lean_calibration.py --predict --dataset "${DATASET}" \
  --window "bt1=@2023-07-01..2026-09-30:backtest+holdout" --out ml/evaluation/v600/bt1_prediction.json
echo "=== $(date -u +%FT%TZ) DONE"
