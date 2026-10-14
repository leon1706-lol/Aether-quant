#!/usr/bin/env bash
# Full test suite on the Codespace (the 4 GB dev PC cannot hold it); same selection as `aq test`.
cd "$(dirname "$0")/.."
exec python -m pytest tests -q -p no:cacheprovider --durations=15 -m "not lean_backtest" > ml/test_run_v580.log 2>&1
