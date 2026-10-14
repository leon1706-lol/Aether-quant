#!/usr/bin/env bash
# V5.8.0 P5.3 on the Codespace (it holds the full dataset): evaluate the installed candidate end to end.
#   bash scripts/codespace_p53_eval.sh /tmp/installed_manifest_local.txt     (the local manifest, copied over with scp)
# Stops before any evaluation if the installed models differ from the local ones. Each step prints its tail; every
# aq evaluate run refreshes the README blocks it feeds. Validation first, backtest last (Monte Carlo and the
# benchmark table describe the last split run).
set -u
cd "$(dirname "$0")/.."
EXPECTED="${1:?path of the expected installed_manifest_local.txt}"
python scripts/ml_manifest.py > /tmp/remote_manifest_now.txt
tr -d '\r' < "$EXPECTED" > /tmp/expected_manifest.txt
if ! diff -q /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt > /dev/null; then
  echo "MANIFEST MISMATCH - the installed models differ from the local ones; not evaluating"
  diff /tmp/remote_manifest_now.txt /tmp/expected_manifest.txt | head -20
  exit 1
fi
echo "manifest: identical to local ($(wc -l < /tmp/remote_manifest_now.txt) files)"
AQ="python aq_cli.py"
run() { echo; echo "=== $*"; "$@" 2>&1 | tail -n 16 | cut -c1-230; }
run $AQ evaluate --rank-book --as-live --split validation
run $AQ evaluate --all --as-live --split backtest --mc-runs 1000
run $AQ evaluate --ic-by-class --split validation
run $AQ evaluate --ic-by-class --split backtest
run $AQ evaluate --audit-gates --split validation
run $AQ evaluate --audit-gates --split backtest
run $AQ evaluate --audit-heads
run $AQ evaluate --audit-features --permutation
run $AQ evaluate --calibrate-volatility-threshold
run python scripts/topology_sizing_research.py
echo; echo "P5.3 done $(date -u +%FT%TZ)"
