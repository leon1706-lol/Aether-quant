#!/usr/bin/env bash
# V5.8.0 Codespace retrain, in two resumable stages (run under nohup; stop the Codespace the moment it finishes).
#
#   bash scripts/codespace_retrain_v580.sh a <tag>                 stage A: active-model baseline dataset, then the new
#                                                                  dataset + experts, control (3 seeds) + variants (2 seeds)
#   bash scripts/codespace_retrain_v580.sh b <tag> <winner_group>  stage B: install winner, sequence, gating, RL (main + forex),
#                                                                  learned topology (dataset source), walk-forward, holdout dataset
#
# Differences from V5.7.0: the data window runs to 2026-09-30 (splits train 2014-12..2021-12, validation 2022-01..2023-06,
# backtest 2023-07..2025-06, holdout 2025-07..2026-09), bonds and forex are separate rank groups, the bond duration beta is
# point-in-time, the label purge and fx_carry_3m are on (all from config.json). Stage A first builds the baseline dataset
# that scores the SHIPPED models on the new splits (their own pre-V5.8.0 feature config ml/config_v560_models.json and the
# active scaler), because train.py overwrites that scaler. The holdout dataset is built LAST so no trainer can read it (the
# book-level RL trainer judges on a holdout_dataset.csv when one exists); its report is run once, locally, after the choice.
set -uo pipefail
cd "$(dirname "$0")/.."
STAGE="${1:?usage: codespace_retrain_v580.sh a|b <tag> [winner_group]}"
TAG="${2:?tag, e.g. v580cs20261013}"
mkdir -p ml/evaluation
exec > >(tee -a "ml/retrain_${TAG}_${STAGE}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
install_files() { local dir="$1"; shift; for f in "$@"; do cp -f "ml/versions/${dir}/${f}" "ml/${f}" || return 1; done; }
VARIANTS=(v2_book_heads v3_listnet v5_wd_x4 v7_small_net)

if [ "${STAGE}" = "a" ]; then
  fit_done() { [ "${RESUME:-0}" = "1" ] && [ -f "ml/versions/$1/multitask_model.json" ]; }
  if [ "${RESUME:-0}" != "1" ]; then
    step "factor-file audit (must report zero double-adjusted files)"
    python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }

    if [ ! -f ml/datasets/v580_active_dataset.csv ]; then
      step "baseline dataset for the SHIPPED models (pre-V5.8.0 features, active scaler, new splits)"
      python scripts/build_holdout_dataset.py --config-path ml/config_v560_models.json --windows-config config.json \
        --start 2023-07-01 --end 2025-06-30 --output ml/datasets/v580_active_dataset.csv \
        || { echo "ABORT: baseline dataset failed"; exit 1; }
    fi

    step "dataset + scaler + baseline + experts (train.py, V5.8.0 config)"
    python train.py || { echo "ABORT: train.py failed"; exit 1; }

    step "feature parity audit"
    python scripts/feature_parity_audit.py || echo "feature parity audit reported failures (continuing; read ml/evaluation/feature_parity_report.json)"
  fi

  step "variant configs"
  python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model multitask

  step "multitask control, seeds 1 2 3"
  for seed in 1 2 3; do
    fit_done "${TAG}_mt_v0_s${seed}" || python train_multitask.py --version-id "${TAG}_mt_v0_s${seed}" --seed "${seed}"
  done

  GROUPS_ARGS=("control=${TAG}_mt_v0_s1,${TAG}_mt_v0_s2,${TAG}_mt_v0_s3")
  for variant in "${VARIANTS[@]}"; do
    step "multitask variant ${variant} (seeds 1 2)"
    ids=()
    for seed in 1 2; do
      { fit_done "${TAG}_mt_${variant}_s${seed}" || python train_multitask.py --version-id "${TAG}_mt_${variant}_s${seed}" --seed "${seed}" \
        --config-path "ml/variant_configs_${TAG}/cfg_multitask_${variant}.json"; } \
        && ids+=("${TAG}_mt_${variant}_s${seed}") || echo "variant ${variant} seed ${seed} failed (continuing)"
    done
    [ "${#ids[@]}" -gt 0 ] && GROUPS_ARGS+=("${variant}=$(IFS=,; echo "${ids[*]}")")
  done

  step "compare variants (R-MODEL8 selection: mean full-daily validation IC vs the control's seed spread)"
  python scripts/compare_training_variants.py --reference control --groups "${GROUPS_ARGS[@]}"
  step "STAGE A DONE"
  exit 0
fi

WINNER="${3:?winner group, e.g. control or v5_wd_x4}"
# LEGACY (V5.8.0): installs seed 1 of the winning group whatever its seeds scored; seed 1 of the V5.8.0 control was its
# weakest (validation IC 0.005 against 0.047 / 0.017). V6.1.0 selects by validation IC (scripts/model_candidate_research.py).
SEED="${WINNER_SEED:-1}"
if [ "${WINNER}" = "control" ]; then WINNER_DIR="${TAG}_mt_v0_s${SEED}"; else WINNER_DIR="${TAG}_mt_${WINNER}_s${SEED}"; fi
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }

step "install multitask winner ${WINNER_DIR}"
install_files "${WINNER_DIR}" multitask_model.json multitask_feature_schema.json multitask_training_metrics.json \
  || { echo "ABORT: winner artifacts missing"; exit 1; }

SEQ_ARGS=(--version-id "${TAG}_seq" --seed 1)
case " ${VARIANTS[*]} " in
  *" ${WINNER} "*)
    python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model sequence
    SEQ_ARGS+=(--config-path "ml/variant_configs_${TAG}/cfg_sequence_${WINNER}.json")
    ;;
esac
if ! done_marker "ml/versions/${TAG}_seq/sequence_model.json"; then
  step "sequence model (${WINNER})"
  python train_sequence.py "${SEQ_ARGS[@]}" || { echo "ABORT: sequence training failed"; exit 1; }
fi
install_files "${TAG}_seq" sequence_model.json sequence_feature_schema.json sequence_training_metrics.json

if ! done_marker "ml/versions/${TAG}_gating/gating_model.json"; then
  step "gating"
  python train_gating.py --version-id "${TAG}_gating" || echo "gating failed or skipped (continuing)"
fi
install_files "${TAG}_gating" gating_model.json gating_feature_schema.json gating_training_metrics.json \
  || echo "gating artifacts missing (continuing)"

step "RL sizing, main book (book-level 20-day reward over the main pool, actions up to 1.2)"
python - <<'PYEOF'
import json
from pathlib import Path
config = json.loads(Path("config.json").read_text())
training = config["phase_v2"]["rl_sizing"]["training"]
training.update(reward_mode="book_member_20d", book_pool_classes=["equity", "crypto"], action_set=[0.6, 0.8, 1.0, 1.2])
Path("ml/rl_main_config.json").write_text(json.dumps(config, indent=2))
config = json.loads(Path("config.json").read_text())
training = config["phase_v2"]["rl_sizing"]["training"]
training.update(reward_mode="book_member_20d", book_pool_classes=["forex"], action_set=[0.0, 0.6, 1.0, 1.25, 1.5])
Path("ml/rl_forex_config.json").write_text(json.dumps(config, indent=2))
PYEOF
done_marker "ml/versions/${TAG}_rl/rl_sizing_model.json" || python train_rl_sizing.py --version-id "${TAG}_rl" --config-path ml/rl_main_config.json \
  || echo "main RL training failed (continuing)"
step "RL sizing, forex sleeve policy"
done_marker "ml/versions/${TAG}_rl_forex/rl_sizing_forex_model.json" || python train_rl_sizing.py --version-id "${TAG}_rl_forex" --config-path ml/rl_forex_config.json \
  || echo "forex RL training failed (continuing)"
for run in "${TAG}_rl:rl_sizing" "${TAG}_rl_forex:rl_sizing_forex"; do
  dir="${run%%:*}"; prefix="${run##*:}"
  if [ -f "ml/versions/${dir}/${prefix}_training_metrics.json" ]; then
    python - "ml/versions/${dir}/${prefix}_training_metrics.json" <<'PYEOF'
import json, sys
metrics = json.loads(open(sys.argv[1]).read())
print(sys.argv[1], "beats constant 1.0:", metrics.get("policy_beats_constant_unpenalized"))
for name, entry in (metrics.get("judged") or {}).items():
    print("  ", name, entry)
PYEOF
  fi
done
echo "RL policies are NOT installed here; R-SLEEVE decides locally."

if ! done_marker "ml/versions/${TAG}_topology/topology_model.json"; then
  step "learned topology (dataset source)"
  python train_topology.py --version-id "${TAG}_topology" --source dataset || echo "topology training failed (continuing)"
fi

step "walk-forward (expanding, multitask + sequence), resumable"
WF_LOG="ml/retrain_${TAG}_walk_forward.log"
RUN_ID="$(grep -o 'walk-forward run id: walk-forward-[0-9a-f-]*' "${WF_LOG}" 2>/dev/null | tail -1 | sed 's/.*: //')"
for attempt in 1 2 3 4; do
  if [ -z "${RUN_ID}" ]; then
    python train.py --walk-forward --include-multitask --include-sequence --mode expanding 2>&1 | tee -a "${WF_LOG}"
  else
    python train.py --walk-forward --include-multitask --include-sequence --mode expanding --resume-run-id "${RUN_ID}" 2>&1 | tee -a "${WF_LOG}"
  fi
  STATUS=${PIPESTATUS[0]}
  RUN_ID="$(grep -o 'walk-forward run id: walk-forward-[0-9a-f-]*' "${WF_LOG}" | tail -1 | sed 's/.*: //')"
  [ "${STATUS}" -eq 0 ] && break
  echo "walk-forward attempt ${attempt} exited ${STATUS}; resuming run ${RUN_ID:-<unknown>}"
done

step "holdout dataset with the NEW scaler (built last; report run locally once)"
python scripts/build_holdout_dataset.py || echo "holdout dataset build failed (continuing)"

step "STAGE B DONE"
