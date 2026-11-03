# aether_quant — the library (V6.4.3)

The reusable, pure part of Aether Quant as one importable package: risk controls, book construction, execution gates,
features, evaluation statistics, the research and audit tools, and the Lean 4 differential cases. It is a **facade**:
every name is re-exported from the module the live algorithm (`main.py`) and the offline simulator already use, so
the library can never drift from the system (`tests/test_aether_quant_api.py` checks they are the same objects).

```powershell
pip install -e .[research]      # from the repo; extras: lib = numpy, pandas; research = + pyarrow, scipy, scikit-learn, statsmodels
python examples/aether_quant_quickstart.py
```

Importing it never loads torch, Lean's `AlgorithmImports`, Redis, Postgres, the web stack or sklearn (sklearn loads
only when `fit_hgb_rank` is called, scipy only for `compute_hrp_weights`).

| Module | What |
|---|---|
| `aether_quant.risk` | `evaluate_kill_switch`, `build_dynamic_position_sizing` and its bounded multipliers, `cap_target_weight`, `assess_drawdown_lock` |
| `aether_quant.portfolio` | `apply_book_neutrality`, `build_rank_based_book`, tranche helpers, `apply_class_weight_caps`, rank normalisation, the sleeve guard, `compute_hrp_weights` |
| `aether_quant.execution` | `resolve_order_permission`, slippage, `build_net_edge_decision` and the cost model, `reconcile_positions` |
| `aether_quant.features` | technical indicators, `cross_sectional_rank`, the as-of (lookahead-free) beta labels |
| `aether_quant.evaluation` | `rank_ic_from_arrays`, `newey_west_t_stat`, Monte Carlo, Lean-exact statistics, PSR / deflated Sharpe, `simulate_rank_book` |
| `aether_quant.research` | `evaluate_signal`, `probability_of_backtest_overfitting`, factor baselines and `factor_spanning`, leakage and overfit audits, the simulator-vs-Lean gap, research probes, the trial registry |
| `aether_quant.audit` | the hash chain (`verify_chain`, with an optional anchored tail) |
| `aether_quant.io` | finite-safe JSON (`sanitize_json_finite`, `atomic_write_json`, ...) |
| `aether_quant.inference` | the numpy forward pass over the JSON-exported networks |
| `aether_quant.formal` | `targets`, `load_cases`, `decode_rational`: the Lean-computed cases, to check a Python function against its verified model |

Example:

```python
from aether_quant import portfolio, research

weights, diagnostics = portfolio.apply_book_neutrality(
    {"A": 0.2, "B": -0.1}, sector_by_symbol={"A": "x", "B": "x"}, dollar_neutral=True, sector_neutral=True,
    gross_exposure_cap=1.0, max_weight_per_name=0.12, sector_max_net_weight=0.15)
report = research.evaluate_signal(frame, score_column="my_score")   # frame: date, ticker, split, my_score, target_rank_20d
```

**Stability.** The public surface (every module's `__all__`) is pinned in `tests/data/aether_quant_api.json`; changing it
is a deliberate snapshot update (`AQ_UPDATE_API_SNAPSHOT=1 aq test --meta`). Versions follow the repo's git tags.

**Known caveat.** Installing the wheel also installs the top-level packages it re-exports (`risk`, `portfolio`,
`execution`, `features`, `evaluation`, ...). A project that has its own top-level package of the same name should keep
the two apart; moving the code under the `aether_quant` namespace (with compatibility shims at the old paths) is the
path if that ever matters.
