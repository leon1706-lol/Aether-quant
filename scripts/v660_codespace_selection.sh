#!/usr/bin/env bash
# V6.6.0 selection on the training Codespace: the model panel, m1-m5's walk-forwards on side A, scoring, placebos, gate, PBO and combination.
# Touches only the free cells. Writes under ml/evaluation/v660/ and logs to /tmp/aq_v660/. Run detached, poll /tmp/aq_v660/status.
set -u
OUT=/tmp/aq_v660
mkdir -p "${OUT}"
STATUS="${OUT}/status"
SCORES=ml/evaluation/v660/scores
PANEL=data_wide/reference/panel_TA.parquet
mkdir -p "${SCORES}"
mark() { echo "$(date -u +%FT%TZ) $1" >> "${STATUS}"; }
TRAIN=(python3 train_cross_sectional.py --panel "${PANEL}" --first-test-year 2011 --purge-days 31 --score-end 2018-12-31)

mark START
python3 scripts/v660_rescore_v650.py > "${OUT}/rescore.log" 2>&1; mark "RESCORE exit $?"
[ -f "${PANEL}" ] || { python3 scripts/v660_build_panel.py TA --out "${PANEL}" > "${OUT}/panel.log" 2>&1; mark "PANEL exit $?"; }
python3 scripts/v660_research.py vel > "${OUT}/vel.log" 2>&1; mark "VEL exit $?"

[ -f "${SCORES}/m1.csv" ] || { "${TRAIN[@]}" --model gbm --variant a --seeds 1 --feature-set price --out "${SCORES}/m1.csv" > "${OUT}/m1.log" 2>&1; mark "M1 exit $?"; }
[ -f "${SCORES}/m2.csv" ] || { "${TRAIN[@]}" --model gbm --variant a --seeds 1 --feature-set all --out "${SCORES}/m2.csv" > "${OUT}/m2.log" 2>&1; mark "M2 exit $?"; }
[ -f "${SCORES}/m4.csv" ] || { "${TRAIN[@]}" --model mlp_multitask --variant a --seeds 1,2,3 --feature-set all --out "${SCORES}/m4.csv" > "${OUT}/m4.log" 2>&1; mark "M4 exit $?"; }

# m3's compute bound, fixed in rules.json: time the first window with one seed.
if [ ! -f "${SCORES}/m3.csv" ]; then
  start=$(date +%s)
  "${TRAIN[@]}" --model set_transformer --variant a --seeds 1 --feature-set all --score-end 2011-12-31 --out "${OUT}/m3_probe.csv" > "${OUT}/m3_probe.log" 2>&1
  code=$?
  seconds=$(( $(date +%s) - start ))
  mark "M3_PROBE exit ${code} seconds ${seconds}"
  if [ "$(( seconds * 3 ))" -le 2400 ]; then
    timeout 21000 "${TRAIN[@]}" --model set_transformer --variant a --seeds 1,2,3 --feature-set all --out "${SCORES}/m3.csv" > "${OUT}/m3.log" 2>&1
    mark "M3 exit $? seeds 3"
  elif [ "$(( seconds * 8 / 20 ))" -le 5400 ]; then
    timeout 21000 "${TRAIN[@]}" --model set_transformer --variant a --seeds 1 --max-epochs 8 --feature-set all --out "${SCORES}/m3.csv" > "${OUT}/m3.log" 2>&1
    mark "M3 exit $? fallback: 1 seed, 8 epochs"
  else
    mark "M3 CLOSED one window over 90 minutes even at the fallback"
  fi
fi
python3 scripts/v660_research.py blend > "${OUT}/blend.log" 2>&1; mark "BLEND exit $?"

python3 scripts/v660_research.py score > "${OUT}/score.log" 2>&1; mark "SCORE exit $?"
python3 scripts/v660_research.py pbo > "${OUT}/pbo.log" 2>&1; mark "PBO exit $?"
python3 scripts/v660_research.py placebo --draws 100 > "${OUT}/placebo.log" 2>&1; mark "PLACEBO exit $?"
python3 scripts/v660_research.py gate > "${OUT}/gate.log" 2>&1; mark "GATE exit $?"
python3 scripts/v660_research.py combine > "${OUT}/combine.log" 2>&1; mark "COMBINE exit $?"
mark ALL_DONE
