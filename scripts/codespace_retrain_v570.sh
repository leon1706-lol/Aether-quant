#!/usr/bin/env bash
# V5.7.0 Codespace retrain, in two resumable stages (run under nohup; stop the Codespace the moment it finishes).
#
#   bash scripts/codespace_retrain_v570.sh a <tag>                 stage A: dataset + control (3 seeds) + variants (2 seeds)
#   bash scripts/codespace_retrain_v570.sh b <tag> <winner_group>  stage B: install winner, sequence, gating, RL, walk-forward, holdout
#
# Differences from the V5.6.0 scripts: the dataset is built with the label purge, the forex class one-hot, the FX carry
# feature and the separate forex rank group (all from config.json); the control runs 3 seeds and every variant 2, selection
# is on the MEAN full-daily validation IC against the control's single-seed spread (R-MODEL, scripts/compare_training_variants.py
# --groups), never on the backtest split; stage B also builds the out-of-window holdout dataset with the ACTIVE scaler.
# The holdout REPORT is not run here: it is looked at once, locally, after the choice (scripts/holdout_report.py).
set -uo pipefail
cd "$(dirname "$0")/.."
STAGE="${1:?usage: codespace_retrain_v570.sh a|b <tag> [winner_group]}"
TAG="${2:?tag, e.g. v570cs20261012}"
mkdir -p ml/evaluation
exec > >(tee -a "ml/retrain_${TAG}_${STAGE}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
install_files() { local dir="$1"; shift; for f in "$@"; do cp -f "ml/versions/${dir}/${f}" "ml/${f}" || return 1; done; }

if [ "${STAGE}" = "a" ]; then
  # RESUME=1: a VM reboot kills a nohup run; skip the dataset build and every multitask fit whose artifacts already exist
  fit_done() { [ "${RESUME:-0}" = "1" ] && [ -f "ml/versions/$1/multitask_model.json" ]; }
  if [ "${RESUME:-0}" != "1" ]; then
    step "factor-file audit (must report zero double-adjusted files)"
    python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }

    step "dataset + scaler + baseline + experts (train.py)"
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
  for variant in v1_gate_off v2_book_heads v3_listnet v4_stop_rank5d v5_wd_x4 v6_dropout_35 v7_small_net; do
    step "multitask variant ${variant} (seeds 1 2)"
    ids=()
    for seed in 1 2; do
      { fit_done "${TAG}_mt_${variant}_s${seed}" || python train_multitask.py --version-id "${TAG}_mt_${variant}_s${seed}" --seed "${seed}" \
        --config-path "ml/variant_configs_${TAG}/cfg_multitask_${variant}.json"; } \
        && ids+=("${TAG}_mt_${variant}_s${seed}") || echo "variant ${variant} seed ${seed} failed (continuing)"
    done
    [ "${#ids[@]}" -gt 0 ] && GROUPS_ARGS+=("${variant}=$(IFS=,; echo "${ids[*]}")")
  done

  step "compare variants (R-MODEL selection: mean full-daily validation IC vs the control's seed spread)"
  python scripts/compare_training_variants.py --reference control --groups "${GROUPS_ARGS[@]}"
  step "STAGE A DONE"
  exit 0
fi

WINNER="${3:?winner group, e.g. control or v5_wd_x4}"
# a group's first seed carries the artifacts that get installed (the others only fed the mean)
if [ "${WINNER}" = "control" ]; then WINNER_DIR="${TAG}_mt_v0_s1"; else WINNER_DIR="${TAG}_mt_${WINNER}_s1"; fi

step "install multitask winner ${WINNER_DIR}"
install_files "${WINNER_DIR}" multitask_model.json multitask_feature_schema.json multitask_training_metrics.json \
  || { echo "ABORT: winner artifacts missing"; exit 1; }

SEQ_ARGS=(--version-id "${TAG}_seq" --seed 1)
case "${WINNER}" in
  v1_gate_off|v2_book_heads|v3_listnet|v4_stop_rank5d|v5_wd_x4|v6_dropout_35|v7_small_net)
    python scripts/make_variant_configs.py "ml/variant_configs_${TAG}" --model sequence
    SEQ_ARGS+=(--config-path "ml/variant_configs_${TAG}/cfg_sequence_${WINNER}.json")
    ;;
esac
step "sequence model (${WINNER})"
python train_sequence.py "${SEQ_ARGS[@]}" || { echo "ABORT: sequence training failed"; exit 1; }
install_files "${TAG}_seq" sequence_model.json sequence_feature_schema.json sequence_training_metrics.json

step "gating"
python train_gating.py --version-id "${TAG}_gating" \
  && install_files "${TAG}_gating" gating_model.json gating_feature_schema.json gating_training_metrics.json \
  || echo "gating failed or skipped (continuing)"

step "RL sizing (book-level reward, penalty sweep from config)"
python train_rl_sizing.py --version-id "${TAG}_rl" || echo "RL sizing failed (continuing)"
python - "${TAG}_rl" <<'PYEOF'
import json, sys
from pathlib import Path
metrics_path = Path("ml/versions") / sys.argv[1] / "rl_sizing_training_metrics.json"
if not metrics_path.exists():
    print("RL: no artifacts written (skipped)")
else:
    metrics = json.loads(metrics_path.read_text())
    print("RL: policy beats constant 1.0 on unpenalised P&L (backtest):", metrics.get("policy_beats_constant_unpenalized"),
          "| policy", metrics.get("backtest_policy_expected_reward_unpenalized"),
          "| constant", metrics.get("backtest_constant_action_1_0_expected_reward_unpenalized"))
    print("RL: NOT installed here; R-RL (both splits, offline book) decides locally.")
PYEOF

step "RL sizing, forex policy (book-level 20-day reward over the forex pool, skip/size actions, per-order dollar minimum)"
python - <<'PYEOF'
import json
from pathlib import Path
config = json.loads(Path("config.json").read_text())
training = config["phase_v2"]["rl_sizing"]["training"]
training.update(reward_mode="book_member_20d", book_pool_classes=["forex"], action_set=[0.0, 0.6, 1.0, 1.25, 1.5])
Path("ml/rl_forex_config.json").write_text(json.dumps(config, indent=2))
PYEOF
python train_rl_sizing.py --version-id "${TAG}_rl_forex" --config-path ml/rl_forex_config.json \
  || echo "forex RL training failed (continuing)"
if [ -f "ml/versions/${TAG}_rl_forex/rl_sizing_forex_training_metrics.json" ]; then
  python - "${TAG}_rl_forex" <<'PYEOF'
import json, sys
from pathlib import Path
metrics = json.loads((Path("ml/versions") / sys.argv[1] / "rl_sizing_forex_training_metrics.json").read_text())
print("forex RL: beats constant 1.0 on every judged split:", metrics.get("policy_beats_constant_unpenalized"))
for name, entry in (metrics.get("judged") or {}).items():
    print("  ", name, entry)
PYEOF
fi

step "holdout dataset with the active scaler (needs data_holdout/ pushed from the dev PC)"
if [ -d data_holdout ]; then
  python scripts/build_holdout_dataset.py || echo "holdout dataset build failed (continuing)"
else
  echo "data_holdout/ missing - skipped"
fi

step "walk-forward (expanding, multitask + sequence), resumable"
WF_LOG="ml/retrain_${TAG}_walk_forward.log"
RUN_ID=""
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

step "STAGE B DONE"
