# backtests

Backtest output, gitignored and excluded from the Docker build.

- **`<timestamp>/`:** a Lean run: the algorithm snapshot, `<id>.json`, `<id>-summary.json`, `<id>-order-events.json`, and the engine's `log.txt`. Read the engine log for teardown claims, not only `<id>-log.txt` (AGENTS.md rule 7).
- **`strategy_report.json`, `equity_curves.csv`:** the active model's offline validation and backtest report (`train.py`, or a promotion).
- **`candidate_<version_id>_report.json`:** a candidate against active and buy-and-hold (`aq retrain backtest`). Never overwritten.

Always run `pytest tests/` with the explicit path: a bare `pytest` crawls the run folders' copied tests (#8).
