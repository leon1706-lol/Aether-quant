# backtests

Strategy validation output for the **active** model, plus per-candidate
comparison reports (V2-17).

- `strategy_report.json` — the active model's validation/backtest report:
  return, Sharpe, max drawdown, hit rate, exposure, trade count and a
  buy-and-hold comparison, per split and per asset. Written by
  `train.py`'s `build_strategy_report()`/`compute_strategy_metrics()`, and
  overwritten on every full (non-candidate) `python train.py` run and on
  every V2-17 promotion (copied from the newly-active candidate's own
  report — see `retraining/artifacts.py`'s `copy_backtest_report_to_active()`).
- `equity_curves.csv` — equity curves backing that report's validation and
  backtest splits, same overwrite behaviour.
- `candidate_<version_id>_report.json` (V2-17) — a per-candidate,
  never-overwritten active/candidate/buy-and-hold comparison, written by
  `retraining/orchestrator.py`'s `backtest()` stage
  (`retraining/backtest_gate.py`'s `compare_backtests()` plus an optional
  Lean-backtest result if the `lean` CLI is available).
- `<timestamp>/` — Lean CLI backtest run directories (`lean backtest .`),
  each a full snapshot of the algorithm source plus Lean's own
  `<id>.json`/`<id>-summary.json`/`log.txt`/data-monitor reports. Not
  produced by `train.py`.

This folder is gitignored (backtest runs are local artifacts) and excluded
from the Docker build context. Per `development/Problems.md` #8, always run
`pytest tests/` with the explicit path — a bare `pytest` from the repo root
also crawls the Lean run directories' copied `tests/` and collides on
duplicate module names once enough backtests have accumulated locally.
