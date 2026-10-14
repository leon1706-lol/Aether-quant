#!/usr/bin/env bash
# Retrain the learned topology from the dataset (regime labels in the live format) and print its prototype statistics.
cd "$(dirname "$0")/.."
python train_topology.py --version-id "${1:?version id}" --source dataset 2>&1 | tail -n 2 | cut -c1-200
python - "ml/versions/${1}/topology_training_metrics.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print("samples", m["sample_count"], "labeled", m["labeled_sample_count"])
for c in m["per_cluster"]:
    print(c["label"], c["sample_count"], round(c["win_rate"], 3) if c["win_rate"] is not None else None, c["dominant_regime_label"])
PY
