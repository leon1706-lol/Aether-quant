#!/usr/bin/env bash
# V6.4.4 R-MODEL13 continuation, in the SAME training-Codespace lifetime as codespace_session_v644.sh (run after it).
# R-MODEL13 (ml/evaluation/v644/r_model13_rule.json) = R-MODEL12 with C1 / C3 on group-centred labels; the grid, the
# seed-1 fits, the as-live memo and every other clause are shared. Resumable: RESUME=1 skips every finished step.
#
#   bash scripts/codespace_start_bg.sh scripts/codespace_session_v644b.sh ml/session_v644b.out /tmp/aq_v644b.pid
set -u
cd "$(dirname "$0")/.."
OUT=ml/evaluation/v644
DATASET=ml/datasets/v644_full_dataset.csv
mkdir -p "${OUT}"
exec > >(tee -a "ml/session_v644b.log") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
marker() { [ "${RESUME:-0}" = "1" ] && [ -f "${OUT}/r13_$1.done" ]; }
finish() { touch "${OUT}/r13_$1.done"; }
R13="python scripts/v644_research.py --dataset ${DATASET} --out ${OUT}/research_r13.json --memo ${OUT}/research.memo.json --centred"

[ -f "${OUT}/r_model13_rule.json" ] || { echo "ABORT: no r_model13_rule.json (the rule comes first)"; exit 1; }
[ -f "${OUT}/ALL_DONE" ] || { echo "ABORT: the R-MODEL12 session has not finished"; exit 1; }
[ -f "${DATASET}" ] || { echo "ABORT: ${DATASET} missing"; exit 1; }

fit() {  # fit <grid id> <seed>
  local id="v644_$1_s$2"
  if [ -f "ml/versions/${id}/multitask_model.json" ]; then return; fi
  step "fit ${id}"
  python train_multitask.py --version-id "${id}" --seed "$2" --config-path "${OUT}/configs/$1.json" \
    --dataset-path "${DATASET}" || echo "${id} failed (continuing)"
}

if ! marker stage1; then
  step "R13-S1 centred priors and stage-1 clauses"
  ${R13} --stages priors stage1 || { echo "ABORT: R-MODEL13 stage 1 failed"; exit 1; }
  finish stage1
fi
for grid_id in $(python -c "import json; print(' '.join(json.load(open('${OUT}/stage1_r13.json'))['survivors']))"); do
  fit "${grid_id}" 2
  fit "${grid_id}" 3
done

if ! marker research; then
  step "R13-S2 stage 2, ensemble, as-live, PBO, spanning, the pick"
  ${R13} --stages stage2 ensemble aslive pbo spanning walkforward_pick --max-phases 10 \
    || { echo "ABORT: the R-MODEL13 chain failed - RESUME=1 continues from the memo"; exit 1; }
  finish research
fi

if ! marker walkforward; then
  step "R13-S3 walk-forward of the finalist (C6)"
  cp config.json /tmp/aq_v644b_config.json.orig
  for candidate in $(python -c "import json; print(' '.join(json.load(open('${OUT}/walkforward_pick_r13.json'))['order']))"); do
    candidate_config=$(python -c "import json; print(json.load(open('${OUT}/walkforward_pick_r13.json'))['configs']['${candidate}'])")
    cp "${candidate_config}" config.json
    before=$(ls -1d ml/versions/walk-forward-* 2>/dev/null | sort)
    run_id=""
    for attempt in 1 2 3 4; do
      if [ -z "${run_id}" ]; then
        python train.py --walk-forward --include-multitask --mode expanding > "${OUT}/walkforward_r13_${candidate}.log" 2>&1
      else
        python train.py --walk-forward --include-multitask --mode expanding --resume-run-id "${run_id}" >> "${OUT}/walkforward_r13_${candidate}.log" 2>&1
      fi
      after=$(ls -1d ml/versions/walk-forward-* 2>/dev/null | sort)
      run_id=$(comm -13 <(echo "${before}") <(echo "${after}") | tail -n 1 | xargs -r basename)
      [ -n "${run_id}" ] && [ -f "ml/versions/${run_id}/walk_forward_summary.json" ] && break
    done
    cp /tmp/aq_v644b_config.json.orig config.json
    if [ -z "${run_id}" ] || [ ! -f "ml/versions/${run_id}/walk_forward_summary.json" ]; then
      echo "walk-forward of ${candidate} produced no summary (C6 fails)"
      continue
    fi
    echo "${candidate} ${run_id}" >> "${OUT}/walkforward_runs_r13.txt"
    cp "ml/versions/${run_id}/walk_forward_summary.json" "${OUT}/walkforward_summary_r13_${candidate}.json"
    find "ml/versions/${run_id}" -name '*.csv' -size +10M -delete
    if ${R13} --stages c6 --wf-candidate "${candidate}" --wf-summary "${OUT}/walkforward_summary_r13_${candidate}.json"; then
      break
    fi
  done
  cmp -s config.json /tmp/aq_v644b_config.json.orig || { echo "ABORT: config.json was not restored"; exit 1; }
  finish walkforward
fi

if ! marker holdout; then
  step "R13-S4 the holdout read and the verdict"
  ${R13} --stages holdout verdict || { echo "ABORT: verdict failed"; exit 1; }
  python scripts/build_trial_registry.py || echo "registry failed"
  finish holdout
fi

step "pack what this continuation wrote"
{
  echo "${OUT}"
  echo ml/session_v644b.log
  echo ml/evaluation/trial_registry.json
  for dir in ml/versions/v644_*; do [ -d "${dir}" ] && echo "${dir}"; done
  [ -f "${OUT}/walkforward_runs_r13.txt" ] && cut -d' ' -f2 "${OUT}/walkforward_runs_r13.txt" | sed 's|^|ml/versions/|'
} > /tmp/eval_pack_v644b.list
tar czf /tmp/eval_pack_v644b.tgz --exclude='*/scores/*' --exclude='*/cand_ml/*' --exclude='*full_dataset.csv' \
  --exclude='*_dataset.csv' -T /tmp/eval_pack_v644b.list
ls -la /tmp/eval_pack_v644b.tgz
touch "${OUT}/R13_DONE"
step "R-MODEL13 CONTINUATION DONE"
