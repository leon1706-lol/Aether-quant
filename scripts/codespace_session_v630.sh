#!/usr/bin/env bash
# V6.3.0 Codespace session, one lifetime (AGENTS.md rule 13): R-CAL3, the pre-registered rule chain, the adopted config,
# then every offline block of the README's Backtest Statistics on that config (resumable; scripts/codespace_start_bg.sh).
#
#   bash scripts/codespace_session_v630.sh <expected manifest>     RESUME=1 skips finished steps
#
# Needs the V6.2.0 BT2 run folder, its book history and its frozen config uploaded first (R-CAL3 and the reconciliation
# read them). The expected manifest is the LOCAL `python scripts/ml_manifest.py` output: models must be identical.
set -u
cd "$(dirname "$0")/.."
EXPECTED="${1:?path of the expected local manifest}"
OUT=ml/evaluation/v630
DATASET=ml/datasets/v610_full_dataset.csv
LEGACY=ml/datasets/legacy_probability.csv
BT2=backtests/2026-10-17_21-39-55
BT2_HISTORY=visualization/book_history/20261017T214005Z.jsonl
mkdir -p "${OUT}"
exec > >(tee -a "ml/session_v630.log") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
marker() { [ "${RESUME:-0}" = "1" ] && [ -f "${OUT}/s_$1.done" ]; }
finish() { touch "${OUT}/s_$1.done"; }
AQ="python aq_cli.py"
run() { local name="$1"; shift; if marker "${name}"; then return; fi; step "$*"; "$@" 2>&1 | tail -n 16 | cut -c1-230; finish "${name}"; }

python scripts/ml_manifest.py > /tmp/remote_manifest_now.txt
tr -d '\r' < "${EXPECTED}" > /tmp/expected_manifest.txt
if ! diff -q /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt > /dev/null; then
  echo "MANIFEST MISMATCH - the installed models differ from the local ones; stopping"
  diff /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt | head -20
  exit 1
fi
for needed in "${DATASET}" "${LEGACY}" "${BT2}/log.txt" "${BT2_HISTORY}" "ml/evaluation/run_configs/2026-10-17_21-39-55.json"; do
  [ -e "${needed}" ] || { echo "ABORT: ${needed} missing"; exit 1; }
done
cmp -s "${DATASET}" ml/datasets/full_dataset.csv || cp "${DATASET}" ml/datasets/full_dataset.csv
[ -f "${OUT}/session_start" ] || { touch "${OUT}/session_start"; cp config.json "${OUT}/config_base.json"; }

run rcal3 python scripts/lean_calibration.py --rcal3 --dataset "${DATASET}" --legacy-probability "${LEGACY}" \
  --gate-warmup-days 400 --out "${OUT}/calibration.json"
run research python scripts/v630_research.py --dataset "${DATASET}" --legacy-probability "${LEGACY}" \
  --calibration "${OUT}/calibration.json" --max-phases 10 --workers 2 --out "${OUT}/research.json" \
  --adopted-config-out "${OUT}/adopted_changes.json"
[ -f "${OUT}/adopted_changes.json" ] || { echo "ABORT: the rule chain wrote no adopted_changes.json"; exit 1; }

if ! marker apply; then
  step "apply the rule-adopted changes to config.json (tranches > 1 needs the live tranche path: stop for it)"
  python - <<'PYEOF'
import json, sys
sys.path.insert(0, "scripts")
from v610_research import apply_dotted
adopted = json.load(open("ml/evaluation/v630/adopted_changes.json"))
config = apply_dotted(json.load(open("ml/evaluation/v630/config_base.json")), adopted["config"])
json.dump(config, open("ml/evaluation/v630/config_adopted.json", "w"), indent=4)
json.dump(config, open("config.json", "w"), indent=4)
print("adopted:", adopted)
if int(adopted.get("tranches", 1)) > 1:
    print("TRANCHES ADOPTED: build the live tranche path before the offline blocks"); sys.exit(3)
PYEOF
  [ $? -eq 0 ] || exit 3
  finish apply
fi

run asl_val $AQ evaluate --rank-book --as-live --split validation
run mt_bt $AQ evaluate --rank-book --capacity --stress --classification --model multitask --split backtest
run all_bt $AQ evaluate --all --as-live --split backtest --mc-runs 1000
run killswitch $AQ evaluate --replay-kill-switch
run factor $AQ evaluate --rank-book --factor-exposure
run ic_val $AQ evaluate --ic-by-class --split validation
run ic_bt $AQ evaluate --ic-by-class --split backtest
run gate_val $AQ evaluate --audit-gates --split validation
run gate_bt $AQ evaluate --audit-gates --split backtest
run heads $AQ evaluate --audit-heads
run features $AQ evaluate --audit-features --permutation
run reconcile $AQ evaluate --reconcile-book-history --book-history-path "${BT2_HISTORY}" --replay-hysteresis --hysteresis-survives-veto
run holdout python scripts/holdout_report.py --models multitask sequence --book
run bond python scripts/class_sleeve_research.py --asset-class bond
run topology python scripts/topology_sizing_research.py
run rl python scripts/rl_sizing_research.py --rl-model ml/rl_sizing_model.json
run registry python scripts/build_trial_registry.py

step "pack the reports this session wrote (older Codespace copies must not overwrite newer local ones)"
find ml/evaluation -maxdepth 1 \( -name '*.json' -o -name '*.npz' \) -newer "${OUT}/session_start" > /tmp/eval_pack.list
echo "${OUT}" >> /tmp/eval_pack.list
echo ml/session_v630.log >> /tmp/eval_pack.list
tar czf /tmp/eval_pack.tgz -T /tmp/eval_pack.list
ls -la /tmp/eval_pack.tgz; wc -l < /tmp/eval_pack.list
step "SESSION DONE"
