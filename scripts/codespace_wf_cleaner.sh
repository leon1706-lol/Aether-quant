#!/usr/bin/env bash
# Side-car for a running stage B: once a walk-forward window has its window_result.json (resume skips it), its per-window
# dataset CSVs are regenerable bulk (~1-2 GB each on the extended data window); delete them so 11 windows fit on the
# 32 GB disk. Models, metrics and the summary are never touched. Runs until the stage B log says "STAGE B DONE".
cd "$(dirname "$0")/.."
while ! grep -qs 'STAGE B DONE' ml/retrain_*_b.log; do
  for result in ml/versions/walk-forward-*/window_*/window_result.json; do
    [ -f "${result}" ] || continue
    dir="$(dirname "${result}")"
    for name in full_dataset.csv train_dataset.csv validation_dataset.csv backtest_dataset.csv; do
      [ -f "${dir}/${name}" ] && rm -f "${dir}/${name}" && echo "$(date -u +%T) removed ${dir}/${name}"
    done
  done
  sleep 120
done
