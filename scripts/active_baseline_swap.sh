#!/usr/bin/env bash
# Score the pre-V5.8.0 ACTIVE models under the CURRENT config on both splits (R-MODEL8 clause 4, fair gates).
# Swaps ml/_backup_pre_v580 over the installed models, runs scripts/active_baseline.py, then restores the snapshot
# ml/_installed_candidate_v580 (taken here first) and verifies it against the manifest - the restore runs even if a
# step fails. Needs ml/evaluation/v580/installed_manifest_local.txt (python scripts/ml_manifest.py of the candidate).
set -u
cd "$(dirname "$0")/.."
MANIFEST=ml/evaluation/v580/installed_manifest_local.txt
python scripts/ml_manifest.py | diff -q - "$MANIFEST" > /dev/null || { echo "installed models differ from $MANIFEST; not swapping"; exit 1; }
python - <<'PY'
import shutil
from pathlib import Path
import sys
sys.path.insert(0, "scripts")
from ml_manifest import installed_files
ml, snap = Path("ml"), Path("ml/_installed_candidate_v580")
for path in installed_files(ml):
    target = snap / path.relative_to(ml)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
PY
restore() {
  python - <<'PY'
import shutil
from pathlib import Path
import sys
sys.path.insert(0, "scripts")
from ml_manifest import installed_files
ml, snap = Path("ml"), Path("ml/_installed_candidate_v580")
for path in installed_files(snap):
    target = ml / path.relative_to(snap)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
PY
  if python scripts/ml_manifest.py | diff -q - "$MANIFEST" > /dev/null; then echo "restored: installed models == candidate manifest"; rm -rf ml/_installed_candidate_v580; else echo "RESTORE MISMATCH (snapshot kept in ml/_installed_candidate_v580)"; fi
}
trap restore EXIT
python - <<'PY'
import shutil
from pathlib import Path
import sys
sys.path.insert(0, "scripts")
from ml_manifest import installed_files
ml, bk = Path("ml"), Path("ml/_backup_pre_v580")
for path in installed_files(bk):
    shutil.copy2(path, ml / path.relative_to(bk))
print("swapped in the pre-V5.8.0 active models")
PY
for split in validation backtest; do
  python scripts/active_baseline.py --split "$split" --dataset ml/datasets/v580_active_dataset.csv --out "ml/evaluation/v580/active_${split}_newgates.json" 2>&1 | tail -n 2 | cut -c1-200
done
