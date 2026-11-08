# aether_quant

The reusable part of Aether Quant as one importable package, over every subsystem. A **facade**: each name is re-exported from the module the live algorithm and the offline tools use, so a library result and a live decision come from the same code.

```powershell
pip install -e .[research]    # extras: lib (numpy, pandas), research (adds pyarrow, scipy, scikit-learn, statsmodels), train (adds torch)
python examples/aether_quant_quickstart.py
python examples/aether_quant_cycle.py     # two generations hand over; no data, no network
```

Importing it never loads torch, Lean's `AlgorithmImports`, Redis, Postgres or the web stack. sklearn loads only for `fit_hgb_rank`, and scipy only for `compute_hrp_weights`.

| Module | What |
|---|---|
| `aether_quant.cycle` | The research cycle: `update_generation_shares`, `dynamic_generation_shares`, `shrunk_sharpe`, `blend_generation_rows`, `GlidePolicy`, `decay_state`, `next_stage`, `share_cap`, `RoundSpec`, `ram_preflight`, `due_actions`, `resolve_session` (a late run still records its session), `build_trial_table` and the closed set of round builders |
| `aether_quant.training` | `purged_embargoed_folds`, `purge_label_overlap`, `assign_split`, `annual_windows`, `rank_inputs`, `fama_macbeth_ridge`, `build_table`, `residualise_signal`, `feature_group_ic` |
| `aether_quant.risk` | `evaluate_kill_switch`, `build_dynamic_position_sizing`, `cap_target_weight`, `assess_drawdown_lock`, asset-class routing, forex and futures risk, RL sizing, `risk_controls` helpers, the manual lock overrides |
| `aether_quant.portfolio` | `apply_book_neutrality`, `build_rank_based_book`, tranches, class caps, the sleeve guard, `compute_hrp_weights`, target weights, sleeves, options, financing, the T-bill sweep, crypto signals (`low_vol`, `lottery_max`, `amihud`, `funding_filtered_trend`, `regime_gate`) and filing signals (`similarity_table`, `announcement_proximity`, `opportunistic_buying`, `term_credit_timing`), book construction helpers |
| `aether_quant.execution` | `resolve_order_permission`, slippage, `build_net_edge_decision`, `reconcile_positions`, paper readiness, the secret scan, the order gate's limit-price and pending-order helpers, route-aware fees |
| `aether_quant.features` | Technical indicators, `cross_sectional_rank`, as-of beta labels, bond, FX, macro, options, cross-asset timing, wide-panel features |
| `aether_quant.evaluation` | `rank_ic_from_arrays`, `newey_west_t_stat`, Monte Carlo, Lean-exact statistics, PSR and deflated Sharpe, `simulate_rank_book`, `simulate_target_weights`, power analysis, impact |
| `aether_quant.research` | `evaluate_signal`, `probability_of_backtest_overfitting`, `factor_spanning`, leakage and overfit audits, the trial registry and ledger, `selection_gate`, `alpha_regression` |
| `aether_quant.regime`, `.topology`, `.moe`, `.liquidity`, `.analyzer` | `build_market_regime_vector`, `build_market_topology`, `build_gating_decision`, spread estimates, the market analyzer |
| `aether_quant.performance`, `.retraining`, `.notifications`, `.monitoring`, `.experience`, `.experts` | Triggers, `evaluate_retraining_plan`, validation gates, rollback, alert formatting, evaluation views, observation metrics |
| `aether_quant.data` | Parsers and tables: `first_filings_annual`, `fundamentals_table`, bar synthesis, membership, factors. Fetchers stay in `data_pipeline/`, filing text as hashed word counts (`hashed_counts`, `filing_tokens`, `count_cosine`) |
| `aether_quant.audit`, `.io`, `.inference` | The hash chain, finite-safe JSON, the numpy forward pass |
| `aether_quant.formal` | `targets`, `load_cases`, `decode_rational`: check a Python function against its verified model |

The README has [a worked example](../README.md#the-aether_quant-library).

**Left out on purpose.** `main.py` needs Lean's engine. Workers, queues, `monitoring/api_server.py` and network fetchers stay in their own modules. The trainers' networks need torch: use `aq cycle retrain`.

**Up to date.** A commit that adds a public function or class to a shipped package updates this package, or lists why it stays out: `scripts/library_gate.py` fails the pre-commit hook (`python scripts/install_hooks.py`) and CI's fast-guards otherwise. What stays out on purpose, with a reason, is in `tests/data/aether_quant_unexported.json`.

**Stability.** The public surface is pinned in `tests/data/aether_quant_api.json`; changing it is a deliberate update (`AQ_UPDATE_API_SNAPSHOT=1 aq test --meta`). Versions come from git tags through `setuptools_scm`.

**Caveat.** The wheel also installs the top-level packages it re-exports (`risk`, `portfolio`, `execution`, `features`, `evaluation`, ...). A project with its own package of the same name should keep the two apart.
