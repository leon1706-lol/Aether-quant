#!/usr/bin/env bash
# V6.0.0 Codespace session S1 (resumable; launch with scripts/codespace_start_bg.sh, stop the Codespace when it is done).
#
#   bash scripts/codespace_session_v600.sh <tag>          RESUME=1 skips every step whose output already exists
#
# 1. data hygiene: data_holdout/ is gone on both sides, factor files clean, the ETH/LTC zips' digests for the local check
# 2. ml/datasets/v600_full_dataset.csv: train / validation / backtest / holdout with the ACTIVE scaler (never refit),
#    plus the per-split files the trainers read; compared row by row with V5.8.0's full_dataset.csv (built by train.py
#    with the same scaler) on train / validation / backtest
# 3. the 60-day variant (v8_rank60): its own dataset (same features and scaler, target_rank_60d, 60-day label purge) and
#    the multitask model with a rank_60d head, seeds 1-3, into ml/versions/<tag>_mt_v8_rank60_s<seed>; nothing is installed
# 4. the full test suite on Python 3.11 (CI's interpreter)
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?tag, e.g. v600cs20261015}"
mkdir -p ml/evaluation/v600
exec > >(tee -a "ml/session_${TAG}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }
rss() { python - <<'PYEOF'
import train
train.log_resident_memory("session step")
PYEOF
}

step "data hygiene"
rm -rf data_holdout
python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }
sha256sum data/crypto/coinbase/daily/ethusd_trade.zip data/crypto/coinbase/daily/ltcusd_trade.zip \
  data/crypto/coinbase/daily/ethusd_quote.zip data/crypto/coinbase/daily/ltcusd_quote.zip | tee ml/evaluation/v600/eth_ltc_digests.txt
python scripts/ml_manifest.py > ml/evaluation/v600/manifest_codespace.txt

if ! done_marker ml/datasets/v600_full_dataset.csv; then
  step "full-split dataset with the active scaler"
  python scripts/build_holdout_dataset.py --full-splits --write-split-files --output ml/datasets/v600_full_dataset.csv \
    || { echo "ABORT: full-split dataset failed"; exit 1; }
fi

if ! done_marker ml/evaluation/v600/dataset_compare.json; then
  step "compare with V5.8.0's full_dataset.csv (train / validation / backtest rows)"
  python - <<'PYEOF'
import json
from pathlib import Path

import numpy as np
import pandas as pd

old_path = Path("ml/datasets/full_dataset.csv")
report = {"reference": str(old_path), "reference_present": old_path.exists()}
if old_path.exists():
    def load(path):
        parts = [chunk[chunk["split"].isin(["train", "validation", "backtest"])] for chunk in pd.read_csv(path, chunksize=40_000)]
        return pd.concat(parts, ignore_index=True).set_index(["date", "ticker"]).sort_index()
    new, old = load("ml/datasets/v600_full_dataset.csv"), load(old_path)
    report["rows_new"], report["rows_old"] = len(new), len(old)
    report["only_new"] = [list(key) for key in new.index.difference(old.index)[:50]]
    report["only_old"] = [list(key) for key in old.index.difference(new.index)[:50]]
    common = new.index.intersection(old.index)
    numeric = [c for c in old.columns if c in new.columns and pd.api.types.is_numeric_dtype(old[c])]
    diffs = {}
    for column in numeric:
        delta = np.abs(new.loc[common, column].to_numpy(dtype=float) - old.loc[common, column].to_numpy(dtype=float))
        delta = delta[~np.isnan(delta)]
        if len(delta) and delta.max() > 1e-6:
            diffs[column] = {"max": float(delta.max()), "rows_over_1e-6": int((delta > 1e-6).sum())}
    report["columns_differing"] = diffs
    report["split_mismatch_rows"] = int((new.loc[common, "split"] != old.loc[common, "split"]).sum())
    tickers = sorted({key[1] for key in common})
    by_ticker = {}
    for column, entry in diffs.items():
        delta = (new.loc[common, column] - old.loc[common, column]).abs()
        hit = delta[delta > 1e-6]
        for ticker, count in hit.groupby(level="ticker").size().items():
            by_ticker.setdefault(ticker, 0)
            by_ticker[ticker] += int(count)
    report["differing_cells_by_ticker"] = dict(sorted(by_ticker.items(), key=lambda item: -item[1])[:30])
    report["num_tickers"] = len(tickers)
Path("ml/evaluation/v600/dataset_compare.json").write_text(json.dumps(report, indent=1))
print(json.dumps({k: v for k, v in report.items() if k != "columns_differing"}, indent=1))
print("columns differing:", len(report.get("columns_differing", {})))
PYEOF
fi

step "variant configs (v8_rank60)"
python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model multitask
VARIANT_CONFIG="ml/variant_configs_${TAG}/cfg_multitask_v8_rank60.json"

if ! done_marker ml/datasets/v600_rank60_dataset.csv; then
  step "60-day variant dataset (same features, active scaler, target_rank_60d)"
  python scripts/build_holdout_dataset.py --full-splits --config-path "${VARIANT_CONFIG}" \
    --output ml/datasets/v600_rank60_dataset.csv || { echo "ABORT: variant dataset failed"; exit 1; }
fi
rss

for seed in 1 2 3; do
  id="${TAG}_mt_v8_rank60_s${seed}"
  if ! done_marker "ml/versions/${id}/multitask_model.json"; then
    step "multitask v8_rank60 seed ${seed}"
    python train_multitask.py --version-id "${id}" --seed "${seed}" --config-path "${VARIANT_CONFIG}" \
      --dataset-path ml/datasets/v600_rank60_dataset.csv || echo "seed ${seed} failed (continuing)"
  fi
done

if ! done_marker ml/evaluation/v600/codespace_tests.txt; then
  step "full test suite (Python 3.11)"
  bash scripts/codespace_run_tests.sh ml/evaluation/v600/codespace_tests.txt || true
  tail -5 ml/evaluation/v600/codespace_tests.txt
fi

step "artifacts"
python scripts/ml_manifest.py | diff - ml/evaluation/v600/manifest_codespace.txt && echo "installed models untouched"
ls -la ml/datasets/ ml/versions/ | tail -40
md5sum ml/datasets/v600_full_dataset.csv ml/datasets/v600_rank60_dataset.csv ml/datasets/train_dataset.csv \
  ml/datasets/validation_dataset.csv ml/datasets/backtest_dataset.csv
step "SESSION DONE"
