#!/usr/bin/env bash
# V6.1.0 Codespace session S1 (resumable; launch with scripts/codespace_start_bg.sh, stop the Codespace when it is done).
#
#   bash scripts/codespace_session_v610.sh <tag>          RESUME=1 skips every step whose output already exists
#
# 1. data hygiene and the installed-model manifest
# 2. ml/datasets/v610_full_dataset.csv: all four splits with the ACTIVE scaler (never refit) and Lean's forex holiday
#    calendar (phase1.features.forex_lean_holidays); compared with V6.0.0's full_dataset.csv cell by cell
# 3. the rolling-window dataset (train rows from 2017-01-01 only) for v10_rolling
# 4. R-MODEL9 candidates: multitask x 5 seeds (control, v9_reg, v10_rolling, v11_snr20), sequence x 3 seeds (control,
#    v9_reg, v11_snr20), into ml/versions/v610_<model>_<variant>_s<seed>; nothing is installed
# 5. rank IC of every candidate, ensembles and single seeds (scripts/model_candidate_research.py)
# 6. the full test suite on Python 3.11 (CI's interpreter)
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?tag, e.g. v610cs20261016}"
OUT=ml/evaluation/v610
mkdir -p "${OUT}"
exec > >(tee -a "ml/session_${TAG}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }
rss() { python -c "import train; train.log_resident_memory('session step')"; }

step "data hygiene"
python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }
python scripts/ml_manifest.py > "${OUT}/manifest_codespace.txt"
python -c "import json; c=json.load(open('config.json')); assert c['phase1']['features']['forex_lean_holidays'] is True" \
  || { echo "ABORT: config.json is not the V6.1.0 one (forex_lean_holidays)"; exit 1; }

if ! done_marker ml/datasets/v610_full_dataset.csv; then
  step "full-split dataset with the active scaler and the forex holiday calendar"
  python scripts/build_holdout_dataset.py --full-splits --write-split-files --output ml/datasets/v610_full_dataset.csv \
    || { echo "ABORT: full-split dataset failed"; exit 1; }
fi

if ! done_marker "${OUT}/dataset_compare.json"; then
  step "compare with V6.0.0's full-split dataset (v600_full_dataset.csv = the local full_dataset.csv, every split)"
  python scripts/compare_datasets.py ml/datasets/v600_full_dataset.csv ml/datasets/v610_full_dataset.csv \
    --out "${OUT}/dataset_compare.json" || echo "compare failed (continuing)"
fi

if ! done_marker ml/datasets/v610_rolling_dataset.csv; then
  step "rolling-window dataset (train rows from 2017-01-01)"
  python - <<'PYEOF'
import pandas as pd
parts = []
for chunk in pd.read_csv("ml/datasets/v610_full_dataset.csv", chunksize=40_000):
    parts.append(chunk[~((chunk["split"] == "train") & (chunk["date"].astype(str) < "2017-01-01"))])
pd.concat(parts, ignore_index=True).to_csv("ml/datasets/v610_rolling_dataset.csv", index=False)
print("written ml/datasets/v610_rolling_dataset.csv")
PYEOF
fi
rss

step "variant configs"
python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model multitask
python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model sequence
CFG="ml/variant_configs_${TAG}"

train_mt() {  # variant config dataset seed
  local id="v610_mt_$1_s$4"
  if ! done_marker "ml/versions/${id}/multitask_model.json"; then
    step "multitask $1 seed $4"
    python train_multitask.py --version-id "${id}" --seed "$4" --config-path "$2" --dataset-path "$3" || echo "${id} failed (continuing)"
  fi
}
train_seq() {  # variant config seed
  local id="v610_seq_$1_s$3"
  if ! done_marker "ml/versions/${id}/sequence_model.json"; then
    step "sequence $1 seed $3"
    python train_sequence.py --version-id "${id}" --seed "$3" --config-path "$2" --dataset-path ml/datasets/v610_full_dataset.csv \
      || echo "${id} failed (continuing)"
  fi
}

for seed in 1 2 3 4 5; do
  train_mt ctl config.json ml/datasets/v610_full_dataset.csv "${seed}"
  train_mt v9_reg "${CFG}/cfg_multitask_v9_reg.json" ml/datasets/v610_full_dataset.csv "${seed}"
  train_mt v10_rolling config.json ml/datasets/v610_rolling_dataset.csv "${seed}"
  train_mt v11_snr20 "${CFG}/cfg_multitask_v11_snr20.json" ml/datasets/v610_full_dataset.csv "${seed}"
done
for seed in 1 2 3; do
  train_seq ctl config.json "${seed}"
  train_seq v9_reg "${CFG}/cfg_sequence_v9_reg.json" "${seed}"
  train_seq v11_snr20 "${CFG}/cfg_sequence_v11_snr20.json" "${seed}"
done
rss

members() {  # prefix count -> comma list of the version dirs that exist
  local out=""
  for seed in $(seq 1 "$2"); do
    [ -f "ml/versions/$1_s${seed}/$3" ] && out="${out:+${out},}ml/versions/$1_s${seed}"
  done
  echo "${out}"
}
if ! done_marker "${OUT}/model_ic.json"; then
  step "rank IC of every candidate (ensembles and single seeds)"
  SEQ_CTL=$(members v610_seq_ctl 3 sequence_model.json)
  python scripts/model_candidate_research.py --dataset ml/datasets/v610_full_dataset.csv --each-member \
    --candidate "installed=multitask:ml;sequence:ml" \
    --candidate "ctl=multitask:$(members v610_mt_ctl 5 multitask_model.json);sequence:${SEQ_CTL}" \
    --candidate "v9_reg=multitask:$(members v610_mt_v9_reg 5 multitask_model.json);sequence:$(members v610_seq_v9_reg 3 sequence_model.json)" \
    --candidate "v10_rolling=multitask:$(members v610_mt_v10_rolling 5 multitask_model.json);sequence:${SEQ_CTL}" \
    --candidate "v11_snr20=multitask:$(members v610_mt_v11_snr20 5 multitask_model.json);sequence:$(members v610_seq_v11_snr20 3 sequence_model.json)" \
    --out "${OUT}/model_ic.json" || echo "model IC failed (continuing)"
fi

if ! done_marker "${OUT}/codespace_tests.txt"; then
  step "full test suite (Python 3.11)"
  bash scripts/codespace_run_tests.sh "${OUT}/codespace_tests.txt" || true
  tail -5 "${OUT}/codespace_tests.txt"
fi

step "artifacts"
python scripts/ml_manifest.py | diff - "${OUT}/manifest_codespace.txt" && echo "installed models untouched"
ls -la ml/datasets/ | tail -12
ls -d ml/versions/v610_* 2> /dev/null
step "SESSION DONE"
