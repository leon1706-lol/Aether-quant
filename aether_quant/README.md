# aether_quant — the library (V6.4.3, whole project since V6.6.1)

The reusable part of Aether Quant as one importable package, covering every subsystem: risk, book construction, execution gates, features, training splits, evaluation, research tools, the research cycle, regime, topology, gating, monitoring views, data parsers and the Lean 4 differential cases. It is a **facade**: every name is re-exported from the module the live algorithm (`main.py`) and the offline simulator already use, so the library can never drift from the system (`tests/test_aether_quant_api.py` checks they are the same objects).

```powershell
pip install -e .[research]      # from the repo; extras: lib = numpy, pandas; research = + pyarrow, scipy, scikit-learn, statsmodels; train = + torch
python examples/aether_quant_quickstart.py
python examples/aether_quant_cycle.py     # two generations hand over; no data, no network
```

Importing it never loads torch, Lean's `AlgorithmImports`, Redis, Postgres, the web stack or sklearn (sklearn loads only when `fit_hgb_rank` is called, scipy only for `compute_hrp_weights`).

| Module | What |
|---|---|
| `aether_quant.cycle` | The research cycle: `update_generation_shares`, `dynamic_generation_shares`, `shrunk_sharpe`, `blend_generation_rows`, `GlidePolicy`, `decay_state`, `next_stage`, `share_cap`, `RoundSpec` and each round stage, `ram_preflight`, `due_actions`, the holdout cells, the forward record |
| `aether_quant.training` | `purged_embargoed_folds`, `purge_label_overlap`, `assign_split`, `annual_windows`, `rank_inputs`, `fama_macbeth_ridge`, `build_table`, `residualise_signal`, `feature_group_ic`, with none of the training stack |
| `aether_quant.risk` | `evaluate_kill_switch`, `build_dynamic_position_sizing` and its multipliers, `cap_target_weight`, `assess_drawdown_lock`, asset-class routing, forex and futures risk, RL sizing |
| `aether_quant.portfolio` | `apply_book_neutrality`, `build_rank_based_book`, tranche helpers, class caps, rank normalisation, the sleeve guard, `compute_hrp_weights`, the target-weights path, premia signals, sleeves, options, financing, the T-bill sweep |
| `aether_quant.execution` | `resolve_order_permission`, slippage, `build_net_edge_decision` and the cost model, `reconcile_positions`, paper readiness, the secret scan |
| `aether_quant.features` | technical indicators, `cross_sectional_rank`, as-of beta labels, bond, FX, macro, options, cross-asset timing and wide-panel features |
| `aether_quant.evaluation` | `rank_ic_from_arrays`, `newey_west_t_stat`, Monte Carlo, Lean-exact statistics, PSR / deflated Sharpe, `simulate_rank_book`, `simulate_target_weights`, power analysis, impact, calibration |
| `aether_quant.research` | `evaluate_signal`, `probability_of_backtest_overfitting`, factor baselines and `factor_spanning`, leakage and overfit audits, the simulator-vs-Lean gap, research probes, the trial registry and ledger, `selection_gate`, `alpha_regression` |
| `aether_quant.regime`, `.topology`, `.moe`, `.liquidity`, `.analyzer` | `build_market_regime_vector`, `build_market_topology`, `build_gating_decision`, spread estimates, the market analyzer |
| `aether_quant.performance`, `.retraining`, `.notifications`, `.monitoring`, `.experience`, `.experts` | Triggers and the rank-IC monitor; `evaluate_retraining_plan`, the validation and backtest gates, rollback; alert formatting; evaluation views; observation metrics and the simulated portfolio; expert dataset definitions |
| `aether_quant.data` | Parsers and tables: `first_filings_annual`, `extended_rows`, `fundamentals_table`, bar synthesis, membership, factors, insider and short-volume tables. Fetchers stay in `data_pipeline/` |
| `aether_quant.audit`, `.io`, `.inference` | The hash chain, finite-safe JSON, the numpy forward pass over exported networks |
| `aether_quant.formal` | `targets`, `load_cases`, `decode_rational`: the Lean-computed cases, to check a Python function against its verified model |

Example:

```python
from aether_quant import cycle, research

shares = cycle.update_generation_shares({"old": 0.7, "new": 0.3}, {"old": "active", "new": "ramping"}, {}, {}, cycle.GlidePolicy())
book = cycle.blend_generation_rows({"old": {"BTCUSD": 0.02}, "new": {"AAPL": 0.03}}, shares)
report = research.evaluate_signal(frame, score_column="my_score")   # frame: date, ticker, split, my_score, target_rank_20d
```

**What it leaves out, on purpose.** `main.py`'s 9,000 lines need Lean's engine, and moving them would change the live path for no gain. Workers, queues, `monitoring/api_server.py` (fastapi at import) and network fetchers stay in their own modules, outside the import-light core. The trainers' networks need torch: run them with `train_cross_sectional.py`, or `aq cycle retrain`.

**Stability.** The public surface (every module's `__all__`) is pinned in `tests/data/aether_quant_api.json`; changing it is a deliberate snapshot update (`AQ_UPDATE_API_SNAPSHOT=1 aq test --meta`). Versions come from git tags through `setuptools_scm`; there are no V6 tags yet, so an install reads 5.4.x until there are.

**Known caveat.** Installing the wheel also installs the top-level packages it re-exports (`risk`, `portfolio`, `execution`, `features`, `evaluation`, ...). A project that has its own top-level package of the same name should keep the two apart; moving the code under the `aether_quant` namespace (with compatibility shims at the old paths) is the path if that ever matters.
