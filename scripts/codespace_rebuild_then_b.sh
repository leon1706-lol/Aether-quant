#!/usr/bin/env bash
# Recovery after ml/ top-level files were overwritten mid-retrain: regenerate scaler / schema / manifest / baseline / experts
# with train.py, prove the dataset came out byte-identical (so the multitask fits under ml/versions still match the scaler),
# then continue stage B (RESUME=1 skips every artifact that already exists).
cd "$(dirname "$0")/.."
TAG="${1:?tag}"; WINNER="${2:-control}"
mkdir -p ml/evaluation
exec > >(tee -a "ml/rebuild_${TAG}.log") 2>&1
echo "=== $(date -u +%FT%TZ) checksum before"
( cd ml/datasets && md5sum full_dataset.csv train_dataset.csv validation_dataset.csv backtest_dataset.csv ) | tee ml/datasets_md5_before.txt
echo "=== $(date -u +%FT%TZ) train.py (dataset, scaler, manifest, baseline, experts)"
python train.py || { echo "ABORT: train.py failed"; exit 1; }
echo "=== $(date -u +%FT%TZ) checksum after"
( cd ml/datasets && md5sum full_dataset.csv train_dataset.csv validation_dataset.csv backtest_dataset.csv ) | tee ml/datasets_md5_after.txt
if diff -q ml/datasets_md5_before.txt ml/datasets_md5_after.txt > /dev/null; then
  echo "DATASET IDENTICAL: the multitask fits and the regenerated scaler belong together"
else
  echo "ABORT: dataset differs after the rebuild - the existing multitask fits no longer match the scaler"
  exit 2
fi
echo "=== $(date -u +%FT%TZ) continue with stage B"
RESUME=1 bash scripts/codespace_retrain_v580.sh b "${TAG}" "${WINNER}"
