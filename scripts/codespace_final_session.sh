#!/usr/bin/env bash
# V5.8.0 last remote batch: multitask offline reports (the README table lists both models), the one-look holdout report,
# the full test suite, then the evaluation pack for scp. Run after `codespace_sync.ps1 -Mode push -CodeOnly`.
set -u
cd "$(dirname "$0")/.."
AQ="python aq_cli.py"
run() { echo; echo "=== $*"; "$@" 2>&1 | tail -n 14 | cut -c1-230; }
python scripts/ml_manifest.py | tr -d '\r' > /tmp/final_manifest.txt
echo "installed models: $(wc -l < /tmp/final_manifest.txt) files, sha256 of the manifest $(sha256sum /tmp/final_manifest.txt | cut -c1-16)"
run $AQ evaluate --rank-book --capacity --stress --model multitask --split backtest
run python scripts/holdout_report.py --models multitask sequence --book
echo; echo "=== full test suite"; bash scripts/codespace_run_tests.sh; tail -n 4 ml/test_run_v580.log | cut -c1-200
bash scripts/codespace_pack_eval.sh
echo; echo "FINAL SESSION DONE $(date -u +%FT%TZ)"
