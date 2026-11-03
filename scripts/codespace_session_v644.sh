#!/usr/bin/env bash
# V6.4.4 training-Codespace session, ONE lifetime (AGENTS.md rule 13). Resumable: RESUME=1 skips every finished step.
#
#   bash scripts/codespace_start_bg.sh scripts/codespace_session_v644.sh ml/session_v644.out /tmp/aq_v644.pid \
#       ml/evaluation/v644/expected_manifest.txt
#
# S0 hygiene: installed-model manifest, the append-only data guard, config dates, the rule file's sha (rules first)
# S1 ml/datasets/v644_full_dataset.csv with the as-of labels (base_asof.json; the active scaler, never refit)
# S2 R-MODEL12 stage 1: seed 1 of every grid ID (M0-M6)
# S3 priors + stage-1 clauses -> survivors; seeds 2 and 3 of each survivor
# S4 the research chain: a smoke pass first, then stage 2, the ensemble, as-live, PBO, spanning, R-TREND1, the pick
# S5 walk-forward of the finalist (clause C6; the next candidate takes it if the first fails, at most two)
# S6 the single holdout read and the verdict; the trial registry
# S7 the full suite on Python 3.11 (CI's interpreter), then the pack for the PC
set -u
cd "$(dirname "$0")/.."
EXPECTED="${1:?path of the expected local manifest}"
OUT=ml/evaluation/v644
DATASET=ml/datasets/v644_full_dataset.csv
HOLDOUT_END=2026-11-02
mkdir -p "${OUT}"
exec > >(tee -a "ml/session_v644.log") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
marker() { [ "${RESUME:-0}" = "1" ] && [ -f "${OUT}/s_$1.done" ]; }
finish() { touch "${OUT}/s_$1.done"; }
RESEARCH="python scripts/v644_research.py --dataset ${DATASET} --out ${OUT}/research.json"

step "S0 hygiene"
python scripts/ml_manifest.py > /tmp/remote_manifest_now.txt
tr -d '\r' < "${EXPECTED}" > /tmp/expected_manifest.txt
if ! diff -q /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt > /dev/null; then
  echo "MANIFEST MISMATCH - the installed models differ from the local ones; stopping"
  diff /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt | head -20
  exit 1
fi
python -c "import json; c=json.load(open('config.json')); assert c['phase1']['windows']['holdout']['end']=='${HOLDOUT_END}'" \
  || { echo "ABORT: config.json is not the V6.4.4 one (holdout end)"; exit 1; }
[ "$(sha256sum "${OUT}/rules.json" | cut -d' ' -f1)" = "$(tr -d '\r\n ' < "${OUT}/rules.sha256")" ] \
  || { echo "ABORT: rules.json does not match rules.sha256 (rules are written before any score)"; exit 1; }
python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }
python scripts/data_append_guard.py verify --before "${OUT}/data_before.json" --out "${OUT}/data_append_guard_codespace.json" \
  || { echo "ABORT: this machine's data differs from the PC's pre-refresh rows"; exit 1; }
[ -f "${OUT}/session_start" ] || { touch "${OUT}/session_start"; cp config.json "${OUT}/config_base.json"; }

if ! marker dataset; then
  step "S1 full-split dataset with the as-of labels (active scaler, no refit)"
  python scripts/build_holdout_dataset.py --full-splits --write-split-files --config-path "${OUT}/configs/base_asof.json" \
    --output "${DATASET}" || { echo "ABORT: dataset failed"; exit 1; }
  python scripts/ml_manifest.py | diff -q - /tmp/expected_manifest.txt > /dev/null \
    || { echo "ABORT: the dataset build changed the installed models"; exit 1; }
  finish dataset
fi
cmp -s "${DATASET}" ml/datasets/full_dataset.csv || cp "${DATASET}" ml/datasets/full_dataset.csv

fit() {  # fit <grid id> <seed>
  local id="v644_$1_s$2"
  if [ -f "ml/versions/${id}/multitask_model.json" ]; then return; fi
  step "fit ${id}"
  python train_multitask.py --version-id "${id}" --seed "$2" --config-path "${OUT}/configs/$1.json" \
    --dataset-path "${DATASET}" || echo "${id} failed (continuing)"
}

step "S2 stage 1: seed 1 of every grid ID"
for grid_id in M0 M1 M2 M3 M4 M5 M6; do fit "${grid_id}" 1; done

if ! marker stage1; then
  step "S3 priors and stage-1 clauses"
  ${RESEARCH} --stages priors stage1 || { echo "ABORT: stage 1 failed"; exit 1; }
  finish stage1
fi
for grid_id in $(python -c "import json; print(' '.join(json.load(open('${OUT}/stage1.json'))['survivors']))"); do
  fit "${grid_id}" 2
  fit "${grid_id}" 3
done

if ! marker smoke; then
  step "S4a smoke pass (every stage, 2 phases)"
  python scripts/v644_research.py --dataset "${DATASET}" --out "${OUT}/smoke.json" --smoke \
    --stages priors stage1 stage2 ensemble aslive pbo trend trend_main walkforward_pick \
    || { echo "ABORT: the smoke pass failed - fix the script, push -CodeOnly, RESUME=1"; exit 1; }
  finish smoke
fi
if ! marker research; then
  step "S4b the research chain"
  ${RESEARCH} --stages stage2 ensemble aslive pbo spanning trend trend_main walkforward_pick --max-phases 10 \
    || { echo "ABORT: the research chain failed - RESUME=1 continues from the memo"; exit 1; }
  finish research
fi

if ! marker walkforward; then
  step "S5 walk-forward of the finalist (C6)"
  cp config.json /tmp/aq_v644_config.json.orig
  for candidate in $(python -c "import json; print(' '.join(json.load(open('${OUT}/walkforward_pick.json'))['order']))"); do
    candidate_config=$(python -c "import json; print(json.load(open('${OUT}/walkforward_pick.json'))['configs']['${candidate}'])")
    cp "${candidate_config}" config.json
    before=$(ls -1d ml/versions/walk-forward-* 2>/dev/null | sort)
    run_id=""
    for attempt in 1 2 3 4; do
      if [ -z "${run_id}" ]; then
        python train.py --walk-forward --include-multitask --mode expanding > "${OUT}/walkforward_${candidate}.log" 2>&1
      else
        python train.py --walk-forward --include-multitask --mode expanding --resume-run-id "${run_id}" >> "${OUT}/walkforward_${candidate}.log" 2>&1
      fi
      after=$(ls -1d ml/versions/walk-forward-* 2>/dev/null | sort)
      run_id=$(comm -13 <(echo "${before}") <(echo "${after}") | tail -n 1 | xargs -r basename)
      [ -n "${run_id}" ] && [ -f "ml/versions/${run_id}/walk_forward_summary.json" ] && break
    done
    cp /tmp/aq_v644_config.json.orig config.json
    if [ -z "${run_id}" ] || [ ! -f "ml/versions/${run_id}/walk_forward_summary.json" ]; then
      echo "walk-forward of ${candidate} produced no summary (C6 fails)"
      continue
    fi
    echo "${candidate} ${run_id}" >> "${OUT}/walkforward_runs.txt"
    cp "ml/versions/${run_id}/walk_forward_summary.json" "${OUT}/walkforward_summary_${candidate}.json"
    # free disk: only this run's per-window datasets (`aq clean ml --apply` would also prune older version folders)
    find "ml/versions/${run_id}" -name '*.csv' -size +10M -delete
    if ${RESEARCH} --stages c6 --wf-candidate "${candidate}" --wf-summary "${OUT}/walkforward_summary_${candidate}.json"; then
      break
    fi
  done
  cmp -s config.json /tmp/aq_v644_config.json.orig || { echo "ABORT: config.json was not restored"; exit 1; }
  finish walkforward
fi

if ! marker holdout; then
  step "S6 the holdout read and the verdict"
  ${RESEARCH} --stages holdout verdict || { echo "ABORT: verdict failed"; exit 1; }
  python scripts/build_trial_registry.py || echo "registry failed"
  finish holdout
fi

if ! marker tests; then
  step "S7 full suite (Python 3.11, CI's interpreter)"
  bash scripts/codespace_run_tests.sh ml/test_run_v644.log
  tail -n 6 ml/test_run_v644.log
  finish tests
fi

step "pack what this session wrote"
{
  echo "${OUT}"
  echo ml/session_v644.log
  echo ml/test_run_v644.log
  echo ml/evaluation/trial_registry.json
  for dir in ml/versions/v644_*; do [ -d "${dir}" ] && echo "${dir}"; done
  [ -f "${OUT}/walkforward_runs.txt" ] && cut -d' ' -f2 "${OUT}/walkforward_runs.txt" | sed 's|^|ml/versions/|'
} > /tmp/eval_pack_v644.list
tar czf /tmp/eval_pack_v644.tgz --exclude='*/scores/*' --exclude='*/cand_ml/*' --exclude='*full_dataset.csv' \
  --exclude='*_dataset.csv' -T /tmp/eval_pack_v644.list
ls -la /tmp/eval_pack_v644.tgz
touch "${OUT}/ALL_DONE"
step "SESSION DONE"
