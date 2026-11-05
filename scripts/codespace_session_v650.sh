#!/usr/bin/env bash
# V6.5.0 training-Codespace session, one lifetime (AGENTS.md rule 13). Resumable: RESUME=1 skips every finished step.
#
#   bash scripts/codespace_start_bg.sh scripts/codespace_session_v650.sh ml/session_v650.out /tmp/aq_v650.pid
#
# S0 hygiene: the rule file's hash
# S1 the full-split dataset (as-of labels), for T5
# S2 T5: gradient-boosted rankers, then the set transformers alongside the T1/T2 walk-forward
# S3 T1/T2: walk-forward windows ending before the verification data; score tables up to the selection end
set -u
cd "$(dirname "$0")/.."
OUT=ml/evaluation/v650
SCORES="${OUT}/scores"
DATASET=ml/datasets/full_dataset.csv
SELECTION_END=2023-06-30
mkdir -p "${SCORES}" "${OUT}/logs"
exec > >(tee -a "${OUT}/logs/session_v650.log") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
marker() { [ "${RESUME:-0}" = "1" ] && [ -f "${OUT}/s_$1.done" ]; }
finish() { touch "${OUT}/s_$1.done"; }

step "S0 hygiene"
[ "$(sha256sum "${OUT}/rules.json" | cut -d' ' -f1)" = "$(tr -d '\r\n ' < "${OUT}/rules.sha256")" ] \
  || { echo "ABORT: rules.json does not match rules.sha256"; exit 1; }
python scripts/v650_make_recipe.py || { echo "ABORT: recipe"; exit 1; }

if ! marker dataset; then
  step "S1 full-split dataset (as-of labels, active scaler)"
  python scripts/build_holdout_dataset.py --full-splits --write-split-files --config-path "${OUT}/configs/recipe.json" \
    --output "${DATASET}" || { echo "ABORT: dataset failed"; exit 1; }
  finish dataset
fi

t5() {  # t5 <model> <short> <variant> <seeds>
  local file="${SCORES}/t5_$2_$3.csv"
  [ -f "${file}" ] && return
  step "T5 $1 $3"
  python train_cross_sectional.py --dataset "${DATASET}" --model "$1" --variant "$3" --seeds "$4" --out "${file}" \
    --score-end "${SELECTION_END}" || echo "T5 $1 $3 failed"
}

step "S2 T5 gradient boosting"
t5 gbm gbm a 1
t5 gbm gbm b 1

(
  step "S2 T5 set transformers"
  t5 set_transformer st a 1,2,3
  t5 set_transformer st b 1,2,3
  echo "T5 DONE"
) > "${OUT}/logs/t5_set_transformer.log" 2>&1 &
T5_PID=$!

if ! marker walkforward; then
  step "S3 walk-forward (windows up to the selection end)"
  cp config.json "${OUT}/config_before_session.json"
  cp "${OUT}/configs/recipe.json" config.json
  run_id=""
  [ -f "${OUT}/walkforward_run_id" ] && run_id="$(cat "${OUT}/walkforward_run_id")"
  if [ -z "${run_id}" ]; then
    before=$(ls -1d ml/versions/walk-forward-* 2>/dev/null | sort)
    python train.py --walk-forward --include-multitask --include-sequence --mode expanding --step-days 365 \
      > "${OUT}/logs/walkforward.log" 2>&1
    after=$(ls -1d ml/versions/walk-forward-* 2>/dev/null | sort)
    run_id=$(comm -13 <(echo "${before}") <(echo "${after}") | tail -n 1 | xargs -r basename)
    echo "${run_id}" > "${OUT}/walkforward_run_id"
  else
    python train.py --walk-forward --include-multitask --include-sequence --mode expanding --step-days 365 \
      --resume-run-id "${run_id}" >> "${OUT}/logs/walkforward.log" 2>&1
  fi
  cp "${OUT}/config_before_session.json" config.json
  [ -n "${run_id}" ] && [ -f "ml/versions/${run_id}/walk_forward_summary.json" ] || { echo "ABORT: walk-forward gave no summary"; exit 1; }
  finish walkforward
fi

if ! marker scores; then
  step "S3 score tables"
  python scripts/v650_ml_scores.py --run-id "$(cat "${OUT}/walkforward_run_id")" --end "${SELECTION_END}" || { echo "ABORT: scores"; exit 1; }
  finish scores
fi

wait "${T5_PID}"
step "session done"
touch "${OUT}/ALL_DONE"
