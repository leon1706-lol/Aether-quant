#!/usr/bin/env bash
# V6.1.0 Codespace session S3: every offline block of the README performance section, recomputed on the final
# configuration and the installed models (resumable; launch with scripts/codespace_start_bg.sh).
#
#   bash scripts/codespace_readme_v610.sh <expected manifest>      RESUME=1 skips finished steps; WF=1 adds the walk-forward
#
# The expected manifest is the LOCAL `python scripts/ml_manifest.py` output: the session stops if the installed models
# on this machine differ. Validation runs before backtest and the multitask column before the final sequence `--all`,
# because the Monte Carlo and benchmark blocks describe the last split run. Order follows the README's own blocks.
set -u
cd "$(dirname "$0")/.."
EXPECTED="${1:?path of the expected local manifest}"
OUT=ml/evaluation/v610
mkdir -p "${OUT}"
exec > >(tee -a "ml/readme_session.log") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
marker() { [ "${RESUME:-0}" = "1" ] && [ -f "${OUT}/s3_$1.done" ]; }
finish() { touch "${OUT}/s3_$1.done"; }

python scripts/ml_manifest.py > /tmp/remote_manifest_now.txt
tr -d '\r' < "${EXPECTED}" > /tmp/expected_manifest.txt
if ! diff -q /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt > /dev/null; then
  echo "MANIFEST MISMATCH - the installed models differ from the local ones; not evaluating"
  diff /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt | head -20
  exit 1
fi
echo "manifest identical to local ($(wc -l < /tmp/remote_manifest_now.txt) files)"

# The final four-split dataset is the one every evaluation reads by default.
if [ ! -f "${OUT}/s3_dataset.done" ]; then
  step "install the V6.1.0 dataset family as full_dataset.csv and the split files"
  cp ml/datasets/v610_full_dataset.csv ml/datasets/full_dataset.csv && touch "${OUT}/s3_dataset.done"
fi

AQ="python aq_cli.py"
run() { local name="$1"; shift; if marker "${name}"; then return; fi; step "$*"; "$@" 2>&1 | tail -n 14 | cut -c1-230; finish "${name}"; }

run asl_val $AQ evaluate --rank-book --as-live --split validation
run mt_bt $AQ evaluate --rank-book --capacity --stress --model multitask --split backtest
run all_bt $AQ evaluate --all --as-live --split backtest --mc-runs 1000
run killswitch $AQ evaluate --replay-kill-switch
run factor $AQ evaluate --rank-book --factor-exposure
run ic_val $AQ evaluate --ic-by-class --split validation
run ic_bt $AQ evaluate --ic-by-class --split backtest
run gate_val $AQ evaluate --audit-gates --split validation
run gate_bt $AQ evaluate --audit-gates --split backtest
run heads $AQ evaluate --audit-heads
run features $AQ evaluate --audit-features --permutation
run holdout python scripts/holdout_report.py --models multitask sequence --book
run bond python scripts/class_sleeve_research.py --asset-class bond
run topology python scripts/topology_sizing_research.py
run rl python scripts/rl_sizing_research.py --rl-model ml/rl_sizing_model.json

if [ "${WF:-0}" = "1" ] && ! marker walkforward; then
  step "walk-forward (expanding, multitask + sequence; one seed per window even when an ensemble is installed), resumable"
  WF_LOG="ml/readme_walk_forward.log"
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
  finish walkforward
fi

step "pack the reports"
bash scripts/codespace_pack_eval.sh
step "S3 DONE"
