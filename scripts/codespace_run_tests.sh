#!/usr/bin/env bash
# Full test suite on the Codespace (the 4 GB dev PC cannot hold it); same selection as `aq test`.
#   bash scripts/codespace_run_tests.sh [log path, default ml/test_run.log]
cd "$(dirname "$0")/.."
LOG="${1:-ml/test_run.log}"
exec python -m pytest tests -q -p no:cacheprovider --durations=15 -m "not lean_backtest" > "${LOG}" 2>&1
