#!/usr/bin/env bash
# V6.6.1, second half: round 3 on free cell S, from its hashed rule file. Each stage resumes after the VM's hourly reboot: rerun this script. Run detached, poll /tmp/aq_v661/status.
set -u
OUT=/tmp/aq_v661
mkdir -p "${OUT}"
STATUS="${OUT}/status"
ROUND=ml/evaluation/v661/round3.json
SCORES=ml/evaluation/v661/scores
PANEL=data_wide/reference/panel_TA.parquet
mkdir -p "${SCORES}"
mark() { echo "$(date -u +%FT%TZ) $1" >> "${STATUS}"; }
stage() { python3 aq_cli.py cycle research "$1" --round "${ROUND}" "${@:2}"; }
TRAIN=(python3 train_cross_sectional.py --panel "${PANEL}" --feature-set fundamental --train-start 2011-07-01 --first-test-year 2013 --purge-days 31 --score-end 2018-12-31)

mark ROUND3_START
[ -f "${PANEL}" ] || { python3 scripts/v660_build_panel.py TA --out "${PANEL}" > "${OUT}/panel.log" 2>&1; mark "PANEL exit $?"; }

stage score --only k01 k02 k03 k04 k05 k09 k10 > "${OUT}/score1.log" 2>&1
mark "SCORE1 exit $?"

[ -f "${SCORES}/k06.csv" ] || { "${TRAIN[@]}" --model gbm_monotone --variant a --seeds 1,2,3 --out "${SCORES}/k06.csv" > "${OUT}/k06.log" 2>&1; mark "K06 exit $?"; }

K05_IC=$(python3 -c "import json; print(json.load(open('ml/evaluation/v661/selection_scores_round3.json'))['k05']['ic']['mean_ic'])" 2>/dev/null || echo none)
mark "K05_IC ${K05_IC}"
if python3 -c "import sys; sys.exit(0 if float('${K05_IC}') > 0.0 else 1)" 2>/dev/null; then
  [ -f "${SCORES}/k07.csv" ] || { "${TRAIN[@]}" --model mlp_multitask --variant a --seeds 1,2,3,4,5 --out "${SCORES}/k07.csv" > "${OUT}/k07.log" 2>&1; mark "K07 exit $?"; }
else
  mark "K07 NOT_RUN k05's mean IC is not above 0: the model track closes on evidence, and k07 still counts in N"
fi

stage score > "${OUT}/score2.log" 2>&1
mark "SCORE2 exit $?"
stage placebo --draws 100 > "${OUT}/placebo.log" 2>&1
mark "PLACEBO exit $?"
stage gate > "${OUT}/gate.log" 2>&1
mark "GATE exit $?"
stage pbo > "${OUT}/pbo.log" 2>&1
mark "PBO exit $?"
stage report > "${OUT}/report.log" 2>&1
mark "REPORT exit $?"
python3 scripts/v661_sanity.py > "${OUT}/sanity.log" 2>&1
mark "SANITY exit $?"
mark ROUND3_DONE
