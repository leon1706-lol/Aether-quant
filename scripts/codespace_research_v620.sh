#!/usr/bin/env bash
# V6.2.0 Codespace session S2: the R-MODEL10 noise yardstick, the candidates and the rule chain (resumable; launch with
# scripts/codespace_start_bg.sh after codespace_session_v620.sh is done).
#
#   bash scripts/codespace_research_v620.sh <tag>          RESUME=1 skips every step whose output already exists
#
# 1. the control ensemble's resampled decision-IC spread (model_candidate_research --bootstrap ctl), merged into model_ic.json
# 2. R-MODEL10 candidates (model dirs, R-HEAD, latency, IC clauses) and the legacy probability of each passing candidate
# 3. the rule chain dedupe -> stagger -> model                                           -> ml/evaluation/v620/research.json
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?tag, e.g. v620cs20261017r}"
OUT=ml/evaluation/v620
DATASET=ml/datasets/v610_full_dataset.csv
mkdir -p "${OUT}"
exec > >(tee -a "ml/research_${TAG}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }

[ -f "${OUT}/model_ic.json" ] || { echo "ABORT: ${OUT}/model_ic.json missing (run codespace_session_v620.sh first)"; exit 1; }
[ -f ml/datasets/legacy_probability.csv ] || { echo "ABORT: ml/datasets/legacy_probability.csv missing"; exit 1; }

members() {  # prefix count file -> comma list of the version dirs that exist
  local out=""
  for seed in $(seq 1 "$2"); do
    [ -f "ml/versions/$1_s${seed}/$3" ] && out="${out:+${out},}ml/versions/$1_s${seed}"
  done
  echo "${out}"
}

if ! done_marker "${OUT}/model_ic_bootstrap.json"; then
  step "R-MODEL10 yardstick: resampled control ensembles"
  python scripts/model_candidate_research.py --dataset "${DATASET}" --bootstrap ctl --bootstrap-n 200 \
    --candidate "ctl=multitask:$(members v610_mt_ctl 5 multitask_model.json);sequence:$(members v610_seq_ctl 3 sequence_model.json)" \
    --out "${OUT}/model_ic_bootstrap.json" || { echo "ABORT: bootstrap failed"; exit 1; }
  python - <<'PYEOF'
import json
path = "ml/evaluation/v620/model_ic.json"
model_ic = json.load(open(path))
model_ic["bootstrap"] = json.load(open("ml/evaluation/v620/model_ic_bootstrap.json"))["bootstrap"]
json.dump(model_ic, open(path, "w"), indent=1)
print("yardstick:", {k: v.get("yardstick") for k, v in model_ic["bootstrap"].items() if isinstance(v, dict)})
PYEOF
fi

if ! done_marker "${OUT}/candidates.json"; then
  step "R-MODEL10 candidates"
  python scripts/prepare_v610_candidates.py --model-ic "${OUT}/model_ic.json" --dataset ml/datasets/validation_dataset.csv \
    --rule r-model10 --prefix v620_cand_ --out "${OUT}/candidates.json" || { echo "ABORT: candidates failed"; exit 1; }
  python - <<'PYEOF'
import json, subprocess
path = "ml/evaluation/v620/candidates.json"
candidates = json.load(open(path))
for name, spec in candidates.items():
    if not spec.get("ic_pass"):
        continue
    out = f"ml/datasets/legacy_probability_v620_{name}.csv"
    members = spec["members"].get("sequence") or []
    subprocess.run(["python", "scripts/build_legacy_probability.py", "--dataset", "ml/datasets/v610_full_dataset.csv",
                    "--out", out, "--sequence-members", *members], check=True)
    spec["legacy_probability"] = out
json.dump(candidates, open(path, "w"), indent=1)
print({name: spec.get("ic_pass") for name, spec in candidates.items()})
PYEOF
fi

step "rule chain"
python scripts/v620_research.py --dataset "${DATASET}" --legacy-probability ml/datasets/legacy_probability.csv \
  --candidates "${OUT}/candidates.json" --model-ic "${OUT}/model_ic.json" --max-phases 10 --workers 2 --out "${OUT}/research.json" \
  || { echo "ABORT: research failed"; exit 1; }

step "SESSION DONE"
