#!/usr/bin/env bash
# Stage A of the V5.6.0 Codespace retrain: regenerate the dataset on the repaired factor files and the live-aligned
# cross-asset features, train the baseline + experts, then train the multitask variants (control x2 seeds + 4 changes)
# so the winner is chosen on VALIDATION IC against the control's seed spread (scripts/compare_training_variants.py).
#
#   bash scripts/codespace_retrain_a.sh <tag>        e.g. v560cs20261008
#
# Writes ml/versions/<tag>_mt_*/ and ml/evaluation/training_variant_comparison.json; the log is ml/retrain_<tag>_a.log.
# Run under nohup so a dropped ssh session does not kill it; stop the Codespace the moment it finishes.
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?usage: codespace_retrain_a.sh <tag>}"
mkdir -p ml/evaluation
exec > >(tee -a "ml/retrain_${TAG}_a.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }

step "factor-file audit (must report zero double-adjusted files)"
python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }

step "dataset + scaler + baseline + experts (train.py)"
python train.py || { echo "ABORT: train.py failed"; exit 1; }

step "feature parity audit"
python scripts/feature_parity_audit.py || echo "feature parity audit reported failures (continuing; read ml/evaluation/feature_parity_report.json)"

step "variant configs"
python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model multitask

step "multitask control, seeds 1 and 2"
python train_multitask.py --version-id "${TAG}_mt_v0_s1" --seed 1
python train_multitask.py --version-id "${TAG}_mt_v0_s2" --seed 2

for variant in v1_gate_off v2_book_heads v3_listnet v4_stop_rank5d; do
  step "multitask variant ${variant}"
  python train_multitask.py --version-id "${TAG}_mt_${variant}" --seed 1 \
    --config-path "ml/variant_configs_${TAG}/cfg_multitask_${variant}.json" \
    || echo "variant ${variant} failed (continuing)"
done

step "compare variants (selection on validation IC)"
python scripts/compare_training_variants.py \
  --reference "${TAG}_mt_v0_s1" \
  --noise "${TAG}_mt_v0_s1" "${TAG}_mt_v0_s2" \
  --variants "${TAG}_mt_v1_gate_off" "${TAG}_mt_v2_book_heads" "${TAG}_mt_v3_listnet" "${TAG}_mt_v4_stop_rank5d"

step "STAGE A DONE"
