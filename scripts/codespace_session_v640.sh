#!/usr/bin/env bash
# V6.4.0 training-Codespace session, ONE lifetime (AGENTS.md rule 13). Resumable: RESUME=1 skips every finished step.
#
#   bash scripts/codespace_session_v640.sh <expected manifest>        (launch with scripts/codespace_start_bg.sh)
#
# S0 hygiene: installed-model manifest, the append-only data guard against the PC's pre-refresh snapshot
# S1 ml/datasets/v640_full_dataset.csv (the active scaler, never refit), compared with V6.1's
# S2 the legacy signal for every split + its gating components (lead L8) and the lagged legacy input (lead L3b)
# S3 the controlled retrain: multitask x 5 seeds with the previous day's legacy probability as an input (candidate v640_leg)
# S4 candidate IC (yardstick fixed at the owner's 0.034) and the candidate directory for the book
# S5 the research chain: a smoke pass first (every code path, minutes), then the real chain
# S6 the adopted config-only changes applied to config.json, then every offline block of the README on that config
# S7 the full suite and CI's clean-checkout view (the PC's memory guard cannot hold them)
set -u
cd "$(dirname "$0")/.."
EXPECTED="${1:?path of the expected local manifest}"
OUT=ml/evaluation/v640
BT4=backtests/2026-10-18_12-55-00
BT4_HISTORY=visualization/book_history/20261018T125514Z.jsonl
mkdir -p "${OUT}"
exec > >(tee -a "ml/session_v640.log") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
marker() { [ "${RESUME:-0}" = "1" ] && [ -f "${OUT}/s_$1.done" ]; }
finish() { touch "${OUT}/s_$1.done"; }
AQ="python aq_cli.py"
run() { local name="$1"; shift; if marker "${name}"; then return; fi; step "$*"; "$@" 2>&1 | tail -n 16 | cut -c1-230; finish "${name}"; }

step "S0 hygiene"
python scripts/ml_manifest.py > /tmp/remote_manifest_now.txt
tr -d '\r' < "${EXPECTED}" > /tmp/expected_manifest.txt
if ! diff -q /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt > /dev/null; then
  echo "MANIFEST MISMATCH - the installed models differ from the local ones; stopping"
  diff /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt | head -20
  exit 1
fi
for needed in "${BT4}/log.txt" "${BT4_HISTORY}" "ml/evaluation/run_configs/2026-10-18_12-55-00.json" "${OUT}/data_before.json" \
  ml/datasets/v610_full_dataset.csv ml/expert_training_metrics.json; do
  [ -e "${needed}" ] || { echo "ABORT: ${needed} missing"; exit 1; }
done
python -c "import json; c=json.load(open('config.json')); assert c['phase1']['windows']['holdout']['end']=='2026-10-16', 'config.json is not the V6.4.0 one'" \
  || { echo "ABORT: config.json is not the V6.4.0 one (holdout end)"; exit 1; }
python -m data_pipeline.factor_file_backfill --audit || { echo "ABORT: double-adjusted factor files on this machine"; exit 1; }
python scripts/data_append_guard.py verify --before "${OUT}/data_before.json" --out "${OUT}/data_append_guard_codespace.json" \
  || { echo "ABORT: this machine's data differs from the PC's pre-refresh rows"; exit 1; }
[ -f "${OUT}/session_start" ] || { touch "${OUT}/session_start"; cp config.json "${OUT}/config_base.json"; }

DATASET=ml/datasets/v640_full_dataset.csv
if ! marker dataset; then
  step "S1 full-split dataset (active scaler, no refit)"
  python scripts/build_holdout_dataset.py --full-splits --write-split-files --output "${DATASET}" || { echo "ABORT: dataset failed"; exit 1; }
  python scripts/compare_datasets.py ml/datasets/v610_full_dataset.csv "${DATASET}" --out "${OUT}/dataset_diff.json" || echo "compare failed"
  python - <<'PYEOF'
import json, sys
report = json.load(open("ml/evaluation/v640/dataset_diff.json"))
drift = sorted(c for c in report.get("columns_differing", {}) if not c.startswith("target_"))
print("rows only in the old file:", report.get("num_only_reference"), "| only in the new file:", report.get("num_only_candidate"))
print("non-label columns that differ on shared rows:", drift or "none")
if (drift or report.get("num_only_reference")) and not __import__("os").environ.get("ALLOW_FEATURE_DRIFT"):
    print("ABORT: a refresh may only add rows and resolve labels; ALLOW_FEATURE_DRIFT=1 overrides after a look")
    sys.exit(1)
PYEOF
  [ $? -eq 0 ] || exit 1
  python scripts/ml_manifest.py | diff -q - /tmp/expected_manifest.txt > /dev/null || { echo "ABORT: the dataset build changed the installed models"; exit 1; }
  finish dataset
fi
cmp -s "${DATASET}" ml/datasets/full_dataset.csv || cp "${DATASET}" ml/datasets/full_dataset.csv

LEGACY=ml/datasets/legacy_probability.csv
COMPONENTS=ml/datasets/legacy_components.csv
if ! marker legacy; then
  step "S2 legacy probability (every split) and gating components"
  python scripts/build_legacy_probability.py --dataset "${DATASET}" --splits train validation backtest holdout --out "${LEGACY}" \
    --emit-components "${COMPONENTS}" || { echo "ABORT: legacy probability failed"; exit 1; }
  python - <<'PYEOF'
import json
import pandas as pd

legacy = pd.read_csv("ml/datasets/legacy_probability.csv")
legacy["date"] = legacy["date"].astype(str).str[:10]
legacy = legacy.sort_values(["ticker", "date"])
legacy["lag1"] = legacy.groupby("ticker")["final_probability_up"].shift(1)
splits = pd.concat([c[["date", "ticker", "split"]] for c in pd.read_csv("ml/datasets/v640_full_dataset.csv", usecols=["date", "ticker", "split"], chunksize=100000)])
splits["date"] = splits["date"].astype(str).str[:10]
train = legacy.merge(splits, on=["date", "ticker"])
train = train[train["split"] == "train"]
mean, std = float(train["lag1"].mean()), float(train["lag1"].std())
legacy["legacy_probability_lag1"] = ((legacy["lag1"].fillna(mean) - mean) / std).astype("float64")
json.dump({"mean": mean, "std": std, "fill": "train mean (z = 0)"}, open("ml/evaluation/v640/legacy_input_scaler.json", "w"), indent=1)
lag = legacy.set_index(["date", "ticker"])["legacy_probability_lag1"]
parts = []
for chunk in pd.read_csv("ml/datasets/v640_full_dataset.csv", chunksize=40000):
    keys = pd.MultiIndex.from_arrays([chunk["date"].astype(str).str[:10], chunk["ticker"]])
    chunk["legacy_probability_lag1"] = lag.reindex(keys).fillna(0.0).to_numpy()
    parts.append(chunk)
pd.concat(parts, ignore_index=True).to_csv("ml/datasets/v640_legacy_dataset.csv", index=False)
schema = json.load(open("ml/feature_schema.json"))
names = list(schema["model_input_names"]) + ["legacy_probability_lag1"]
json.dump({"model_input_names": names}, open("ml/evaluation/v640/schema_mt_leg.json", "w"), indent=1)
print("legacy input: mean %.4f std %.4f; schema inputs %d" % (mean, std, len(names)))
PYEOF
  [ $? -eq 0 ] || exit 1
  finish legacy
fi

for seed in 1 2 3 4 5; do
  id="v640_mt_leg_s${seed}"
  if ! { [ "${RESUME:-0}" = "1" ] && [ -f "ml/versions/${id}/multitask_model.json" ]; }; then
    step "S3 multitask with the legacy input, seed ${seed}"
    python train_multitask.py --version-id "${id}" --seed "${seed}" --config-path config.json \
      --dataset-path ml/datasets/v640_legacy_dataset.csv --feature-schema-path "${OUT}/schema_mt_leg.json" || echo "${id} failed (continuing)"
  fi
done

if ! marker candidates; then
  step "S4 candidate IC and directory"
  MEMBERS="ml/versions/v640_mt_leg_s1,ml/versions/v640_mt_leg_s2,ml/versions/v640_mt_leg_s3,ml/versions/v640_mt_leg_s4,ml/versions/v640_mt_leg_s5"
  CTL=""
  if [ -d ml/versions/v610_mt_ctl_s5 ] && [ -d ml/versions/v610_seq_ctl_s3 ]; then
    CTL="--candidate ctl=multitask:ml/versions/v610_mt_ctl_s1,ml/versions/v610_mt_ctl_s2,ml/versions/v610_mt_ctl_s3,ml/versions/v610_mt_ctl_s4,ml/versions/v610_mt_ctl_s5;sequence:ml/versions/v610_seq_ctl_s1,ml/versions/v610_seq_ctl_s2,ml/versions/v610_seq_ctl_s3"
  fi
  # shellcheck disable=SC2086
  python scripts/model_candidate_research.py --dataset ml/datasets/v640_legacy_dataset.csv \
    --candidate "installed=multitask:ml;sequence:ml" ${CTL} --candidate "v640_leg=multitask:${MEMBERS};sequence:ml" \
    --out "${OUT}/model_ic.json" || echo "model_candidate_research failed (the model stage will be skipped)"
  python - <<'PYEOF'
import json
path = "ml/evaluation/v640/model_ic.json"
data = json.load(open(path))
data["bootstrap"] = {key: {"yardstick": 0.034} for key in ("decision_rank_20d", "decision_rank_20d_swapped_priority")}
json.dump(data, open(path, "w"), indent=1)
print("yardstick fixed at 0.034 (owner's seed bar)")
PYEOF
  python scripts/prepare_v610_candidates.py --model-ic "${OUT}/model_ic.json" --dataset ml/datasets/v640_legacy_dataset.csv \
    --out "${OUT}/candidates.json" --rule r-model10 --prefix v640_cand_ || echo "prepare failed (the model stage will be skipped)"
  python - <<'PYEOF'
import json
path = "ml/evaluation/v640/candidates.json"
try:
    data = json.load(open(path))
except OSError:
    data = {}
for name, spec in data.items():
    if name != "installed":
        spec["dataset"] = "ml/datasets/v640_legacy_dataset.csv"
json.dump(data, open(path, "w"), indent=1)
PYEOF
  finish candidates
fi

COMMON=(--dataset "${DATASET}" --legacy-probability "${LEGACY}" --legacy-components "${COMPONENTS}" --candidates "${OUT}/candidates.json"
  --model-ic "${OUT}/model_ic.json" --lean-run "${BT4}" --workers 2)
if ! marker smoke; then
  step "S5a smoke pass (one variant per stage, 2 phases)"
  rm -f "${OUT}/smoke.json" "${OUT}/smoke.memo.json"
  python scripts/v640_research.py "${COMMON[@]}" --smoke --out "${OUT}/smoke.json" --adopted-config-out "${OUT}/smoke_adopted.json" \
    || { echo "ABORT: the smoke pass failed - fix the script, push -CodeOnly, RESUME=1"; exit 1; }
  finish smoke
fi
if ! marker research; then
  step "S5b the research chain"
  python scripts/v640_research.py "${COMMON[@]}" --max-phases 10 --out "${OUT}/research.json" --adopted-config-out "${OUT}/adopted_changes.json" \
    || { echo "ABORT: the research chain failed - RESUME=1 continues from the memo"; exit 1; }
  finish research
fi
[ -f "${OUT}/adopted_changes.json" ] || { echo "ABORT: the rule chain wrote no adopted_changes.json"; exit 1; }
run registry python scripts/build_trial_registry.py

if ! marker apply; then
  step "S6a apply the config-only adopted changes (items needing a live path wait for the PC)"
  python - <<'PYEOF'
import json, sys
sys.path.insert(0, "scripts")
from v610_research import apply_dotted
from v640_research import patch_config

adopted = json.load(open("ml/evaluation/v640/adopted_changes.json"))
config = json.load(open("ml/evaluation/v640/config_base.json"))
config = patch_config(apply_dotted(config, adopted["config"]), adopted.get("patch", {}))
json.dump(config, open("ml/evaluation/v640/config_adopted.json", "w"), indent=4)
json.dump(config, open("config.json", "w"), indent=4)
print("adopted:", json.dumps(adopted)[:600])
if adopted.get("needs_live_path"):
    print("NEEDS_LIVE_PATH:", adopted["needs_live_path"])
    open("ml/evaluation/v640/NEEDS_LIVE_PATH", "w").write(json.dumps(adopted["needs_live_path"]))
PYEOF
  finish apply
fi

run asl_val $AQ evaluate --rank-book --as-live --split validation
run mt_bt $AQ evaluate --rank-book --capacity --stress --classification --model multitask --split backtest
run seq_cls $AQ evaluate --classification --model sequence --split backtest
run all_bt $AQ evaluate --all --as-live --split backtest --mc-runs 1000
run killswitch $AQ evaluate --replay-kill-switch
run factor $AQ evaluate --rank-book --factor-exposure
run ic_val $AQ evaluate --ic-by-class --split validation
run ic_bt $AQ evaluate --ic-by-class --split backtest
run gate_val $AQ evaluate --audit-gates --split validation
run gate_bt $AQ evaluate --audit-gates --split backtest
run heads $AQ evaluate --audit-heads
run features $AQ evaluate --audit-features --permutation
run reconcile $AQ evaluate --reconcile-book-history --book-history-path "${BT4_HISTORY}" --replay-hysteresis --hysteresis-survives-veto
run holdout python scripts/holdout_report.py --models multitask sequence --book
run bond python scripts/class_sleeve_research.py --asset-class bond
run topology python scripts/topology_sizing_research.py
run rl python scripts/rl_sizing_research.py --rl-model ml/rl_sizing_model.json

if ! marker tests; then
  step "S7 full suite (Python 3.11, CI's interpreter)"
  bash scripts/codespace_run_tests.sh ml/test_run_v640.log
  tail -n 6 ml/test_run_v640.log
  finish tests
fi

step "pack the reports this session wrote (older Codespace copies must not overwrite newer local ones)"
find ml/evaluation -maxdepth 1 \( -name '*.json' -o -name '*.npz' \) -newer "${OUT}/session_start" > /tmp/eval_pack.list
echo "${OUT}" >> /tmp/eval_pack.list
echo ml/session_v640.log >> /tmp/eval_pack.list
echo ml/test_run_v640.log >> /tmp/eval_pack.list
for dir in ml/versions/v640_mt_leg_s1 ml/versions/v640_mt_leg_s2 ml/versions/v640_mt_leg_s3 ml/versions/v640_mt_leg_s4 ml/versions/v640_mt_leg_s5; do
  [ -d "${dir}" ] && echo "${dir}" >> /tmp/eval_pack.list
done
for dir in ml/versions/v640_cand_*; do [ -d "${dir}" ] && echo "${dir}" >> /tmp/eval_pack.list; done
echo ml/datasets/legacy_probability.csv >> /tmp/eval_pack.list
tar czf /tmp/eval_pack.tgz -T /tmp/eval_pack.list
ls -la /tmp/eval_pack.tgz; wc -l < /tmp/eval_pack.list
step "SESSION DONE"
