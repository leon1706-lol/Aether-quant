#!/usr/bin/env bash
# Stage B of the V5.6.0 Codespace retrain, after stage A picked the multitask winner.
#
#   bash scripts/codespace_retrain_b.sh <tag> <winner_suffix>      e.g. v560cs20261008 v0_s1   (or v2_book_heads, ...)
#
# 1. installs the winning multitask candidate into the Codespace's active ml/ (gating and RL read it from there),
# 2. trains the sequence model with the winner's analogous change (v0_* = unchanged), gating, and RL sizing (penalty sweep),
# 3. installs sequence/gating always, RL only if it beats constant 1.0 on UNPENALISED backtest P&L,
# 4. runs the expanding walk-forward with per-window resume (a VM reboot costs one window).
# The strategy selector and learned topology need Postgres experience events and are not retrained here.
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?usage: codespace_retrain_b.sh <tag> <winner_suffix>}"
WINNER="${2:?winner suffix, e.g. v0_s1 or v2_book_heads}"
mkdir -p ml/evaluation
exec > >(tee -a "ml/retrain_${TAG}_b.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
install_files() { local dir="$1"; shift; for f in "$@"; do cp -f "ml/versions/${dir}/${f}" "ml/${f}" || return 1; done; }

step "install multitask winner ${TAG}_mt_${WINNER}"
install_files "${TAG}_mt_${WINNER}" multitask_model.json multitask_feature_schema.json multitask_training_metrics.json \
  || { echo "ABORT: winner artifacts missing"; exit 1; }

SEQ_ARGS=(--version-id "${TAG}_seq" --seed 1)
case "${WINNER}" in
  v1_gate_off|v2_book_heads|v3_listnet|v4_stop_rank5d)
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

step "RL sizing (penalty sweep from config)"
python train_rl_sizing.py --version-id "${TAG}_rl" || echo "RL sizing failed (continuing)"
python - "${TAG}_rl" <<'PYEOF'
import json, shutil, sys
from pathlib import Path
version_dir = Path("ml/versions") / sys.argv[1]
metrics_path = version_dir / "rl_sizing_training_metrics.json"
if not metrics_path.exists():
    print("RL: no artifacts written (skipped)")
else:
    metrics = json.loads(metrics_path.read_text())
    wins = metrics.get("policy_beats_constant_unpenalized")
    print("RL: policy beats constant 1.0 on unpenalised backtest P&L:", wins,
          "| policy", metrics.get("backtest_policy_expected_reward_unpenalized"),
          "| constant", metrics.get("backtest_constant_action_1_0_expected_reward_unpenalized"))
    if wins:
        for name in ("rl_sizing_model.json", "rl_sizing_feature_schema.json", "rl_sizing_training_metrics.json"):
            shutil.copy2(version_dir / name, Path("ml") / name)
        print("RL: installed into active ml/ (rl_sizing_enabled stays false until the owner-run backtest agrees)")
    else:
        print("RL: NOT installed - another honest negative")
PYEOF

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
