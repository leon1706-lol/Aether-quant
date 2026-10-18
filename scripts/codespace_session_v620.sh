#!/usr/bin/env bash
# V6.2.0 Codespace session (lead 2, regularised retrain; resumable; launch with scripts/codespace_start_bg.sh).
#
#   bash scripts/codespace_session_v620.sh <tag>          RESUME=1 skips every step whose output already exists
#
# 1. data hygiene, the installed-model manifest, config checks
# 2. the train-split feature subset (scripts/select_feature_subset.py; validation and backtest never read)
# 3. multitask x 5 seeds (v12_reg_noise, v13_reg_subset, v14_reg_noise_subset), sequence x 3 seeds (v12, v14) into
#    ml/versions/v620_<model>_<variant>_s<seed>; nothing is installed
# 4. rank IC of every candidate against the installed models and V6.1's control / v9_reg members (model_candidate_research)
# 5. the full test suite on Python 3.11 (CI's interpreter)
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?tag, e.g. v620cs20261017}"
OUT=ml/evaluation/v620
DATASET=ml/datasets/v610_full_dataset.csv
mkdir -p "${OUT}"
exec > >(tee -a "ml/session_${TAG}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }

step "data hygiene"
python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }
python scripts/ml_manifest.py > "${OUT}/manifest_codespace.txt"
[ -f "${DATASET}" ] || { echo "ABORT: ${DATASET} missing (the V6.1 full-split build)"; exit 1; }
python -c "import json; c=json.load(open('config.json')); assert 'label_noise_std' in c['phase_v2']['retraining']['multitask_training']" \
  || { echo "ABORT: config.json is not the V6.2.0 one (label_noise_std)"; exit 1; }

if ! done_marker "${OUT}/feature_schema_subset.json"; then
  step "feature subset on the train split"
  python scripts/select_feature_subset.py --dataset "${DATASET}" --out-dir "${OUT}" || { echo "ABORT: subset failed"; exit 1; }
fi
SUBSET="${OUT}/feature_schema_subset.json"
N_KEPT=$(python -c "import json; print(len(json.load(open('${SUBSET}'))['model_input_names']))")
echo "feature subset: ${N_KEPT} features"

step "variant configs"
python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model multitask
python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model sequence
CFG="ml/variant_configs_${TAG}"

train_mt() {  # variant seed [schema]
  local id="v620_mt_$1_s$2" schema=()
  [ -n "${3:-}" ] && schema=(--feature-schema-path "$3")
  if ! done_marker "ml/versions/${id}/multitask_model.json"; then
    step "multitask $1 seed $2"
    python train_multitask.py --version-id "${id}" --seed "$2" --config-path "${CFG}/cfg_multitask_$1.json" \
      --dataset-path "${DATASET}" "${schema[@]}" || echo "${id} failed (continuing)"
  fi
}
train_seq() {  # variant seed [schema]
  local id="v620_seq_$1_s$2" schema=()
  [ -n "${3:-}" ] && schema=(--feature-schema-path "$3")
  if ! done_marker "ml/versions/${id}/sequence_model.json"; then
    step "sequence $1 seed $2"
    python train_sequence.py --version-id "${id}" --seed "$2" --config-path "${CFG}/cfg_sequence_$1.json" \
      --dataset-path "${DATASET}" "${schema[@]}" || echo "${id} failed (continuing)"
  fi
}

for seed in 1 2 3 4 5; do
  train_mt v12_reg_noise "${seed}"
  # fewer than 10 surviving features would be a different model class, not a regularised one: the subset variants skip
  if [ "${N_KEPT}" -ge 10 ]; then
    train_mt v13_reg_subset "${seed}" "${SUBSET}"
    train_mt v14_reg_noise_subset "${seed}" "${SUBSET}"
  fi
done
for seed in 1 2 3; do
  train_seq v12_reg_noise "${seed}"
  [ "${N_KEPT}" -ge 10 ] && train_seq v14_reg_noise_subset "${seed}" "${SUBSET}"
done

members() {  # prefix count file -> comma list of the version dirs that exist
  local out=""
  for seed in $(seq 1 "$2"); do
    [ -f "ml/versions/$1_s${seed}/$3" ] && out="${out:+${out},}ml/versions/$1_s${seed}"
  done
  echo "${out}"
}
if ! done_marker "${OUT}/model_ic.json"; then
  step "rank IC of every candidate (ensembles and single seeds)"
  SEQ_CTL=$(members v610_seq_ctl 3 sequence_model.json)
  SEQ_V12=$(members v620_seq_v12_reg_noise 3 sequence_model.json)
  SEQ_V14=$(members v620_seq_v14_reg_noise_subset 3 sequence_model.json)
  ARGS=(--candidate "installed=multitask:ml;sequence:ml"
        --candidate "ctl=multitask:$(members v610_mt_ctl 5 multitask_model.json);sequence:${SEQ_CTL}"
        --candidate "v9_reg=multitask:$(members v610_mt_v9_reg 5 multitask_model.json);sequence:$(members v610_seq_v9_reg 3 sequence_model.json)"
        --candidate "v12_reg_noise=multitask:$(members v620_mt_v12_reg_noise 5 multitask_model.json);sequence:${SEQ_V12}")
  if [ "${N_KEPT}" -ge 10 ]; then
    ARGS+=(--candidate "v13_reg_subset=multitask:$(members v620_mt_v13_reg_subset 5 multitask_model.json);sequence:${SEQ_CTL}"
           --candidate "v14_reg_noise_subset=multitask:$(members v620_mt_v14_reg_noise_subset 5 multitask_model.json);sequence:${SEQ_V14}")
  fi
  python scripts/model_candidate_research.py --dataset "${DATASET}" --each-member "${ARGS[@]}" --out "${OUT}/model_ic.json" \
    || echo "model IC failed (continuing)"
fi

if ! done_marker "${OUT}/codespace_tests.txt"; then
  step "full test suite (Python 3.11)"
  bash scripts/codespace_run_tests.sh "${OUT}/codespace_tests.txt" || true
  tail -5 "${OUT}/codespace_tests.txt"
fi

step "artifacts"
python scripts/ml_manifest.py | diff - "${OUT}/manifest_codespace.txt" && echo "installed models untouched"
ls -d ml/versions/v620_* 2> /dev/null
step "SESSION DONE"
