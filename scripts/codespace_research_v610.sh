#!/usr/bin/env bash
# V6.1.0 Codespace session S2: calibration and the rule chain (resumable; launch with scripts/codespace_start_bg.sh).
#
#   bash scripts/codespace_research_v610.sh <tag>          RESUME=1 skips every step whose output already exists
#
# 1. the legacy signal's probability for every row (installed models)            -> ml/datasets/legacy_probability.csv
# 2. R-CAL2 on the three windows with the V6.1.0 simulator                         -> ml/evaluation/v610/calibration.json
# 3. R-MODEL9 candidates (model dirs, R-HEAD, latency, IC clauses) and the legacy probability of each passing candidate
# 4. the rule chain model -> head -> book -> legacy -> gate                        -> ml/evaluation/v610/research.json
# 5. the BT1 prediction of the final configuration (whole span, written BEFORE the Lean run)
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?tag, e.g. v610cs20261016r}"
OUT=ml/evaluation/v610
DATASET=ml/datasets/v610_full_dataset.csv
mkdir -p "${OUT}"
exec > >(tee -a "ml/research_${TAG}.log") 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }

if ! done_marker ml/datasets/legacy_probability.csv; then
  step "legacy probability (installed models)"
  python scripts/build_legacy_probability.py --dataset "${DATASET}" --out ml/datasets/legacy_probability.csv \
    || { echo "ABORT: legacy probability failed"; exit 1; }
fi

if ! done_marker "${OUT}/calibration.json"; then
  step "R-CAL2"
  python scripts/lean_calibration.py --rcal2 --dataset "${DATASET}" --legacy-probability ml/datasets/legacy_probability.csv \
    --gate-warmup-days 400 --out "${OUT}/calibration.json" || { echo "ABORT: calibration failed"; exit 1; }
fi
python -c "import json; print('R-CAL2 verdict:', json.load(open('${OUT}/calibration.json'))['verdict'])"

if ! done_marker "${OUT}/candidates.json"; then
  step "R-MODEL9 candidates"
  python scripts/prepare_v610_candidates.py --model-ic "${OUT}/model_ic.json" --dataset ml/datasets/validation_dataset.csv \
    --out "${OUT}/candidates.json" || { echo "ABORT: candidates failed"; exit 1; }
  python - <<'PYEOF'
import json, subprocess
path = "ml/evaluation/v610/candidates.json"
candidates = json.load(open(path))
for name, spec in candidates.items():
    if not spec.get("ic_pass"):
        continue
    out = f"ml/datasets/legacy_probability_{name}.csv"
    members = spec["members"].get("sequence") or []
    subprocess.run(["python", "scripts/build_legacy_probability.py", "--dataset", "ml/datasets/v610_full_dataset.csv",
                    "--out", out, "--sequence-members", *members], check=True)
    spec["legacy_probability"] = out
json.dump(candidates, open(path, "w"), indent=1)
print({name: spec.get("ic_pass") for name, spec in candidates.items()})
PYEOF
fi

step "rule chain"
python scripts/v610_research.py --dataset "${DATASET}" --legacy-probability ml/datasets/legacy_probability.csv \
  --candidates "${OUT}/candidates.json" --model-ic "${OUT}/model_ic.json" --max-phases 10 --workers 2 --out "${OUT}/research.json" \
  || { echo "ABORT: research failed"; exit 1; }

step "SESSION DONE (the BT1 prediction runs after the adopted config is written locally)"
