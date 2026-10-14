#!/usr/bin/env bash
# V5.8.0 Codespace preparation, run once after `codespace_sync.ps1 -Mode push` and before stage A.
#   1. remove the equity factor files the data refresh deleted locally (a push never deletes: leaving them would
#      double-adjust the Yahoo-adjusted zips again, Problems.md #130)
#   2. free disk: the datasets are rebuilt by train.py, finished walk-forward windows keep only models/metrics/summary
#   3. verify the data manifest and the factor-file audit
set -uo pipefail
cd "$(dirname "$0")/.."
echo "=== factor files that exist remotely but not locally"
for t in aapl spy qqq iwm eem bac ibm aig bno fb goog googl uso wm aaa; do
  f="data/equity/usa/factor_files/${t}.csv"
  [ -f "$f" ] && rm -v "$f"
done
python -m data_pipeline.factor_file_backfill --audit

echo "=== disk before"; df -h /workspaces | tail -1
rm -rf ml/datasets ml/expert_datasets
find ml/versions -path '*walk-forward-*' -name '*dataset.csv' -print -delete 2>/dev/null | wc -l
echo "=== disk after"; df -h /workspaces | tail -1
mkdir -p ml/versions ml/evaluation

echo "=== data manifest"
python - <<'PYEOF'
import json
from pathlib import Path
from data_pipeline.data_audit import build_data_manifest
manifest = build_data_manifest(Path("data"))
with open("data/manifest_v580.json", "w", encoding="utf-8", newline="
") as handle:
    handle.write(json.dumps(manifest, indent=1, sort_keys=True))
print("files:", len(manifest))
PYEOF
