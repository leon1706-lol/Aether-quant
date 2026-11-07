# portfolio

Decides what the book holds: target weights, the rank-based book and its neutrality, sleeves and options. Everything here is pure and free of Lean, so `main.py` and the offline simulators share it.

## Target weights: the shipped path

`target_weights.py` (`phase_v2.target_weights`) holds a hash-pinned file of weights with no gates between a weight and its order.

- **Read:** `load_weight_file`, pinned by `weights_sha256`; `live_reload` and `next_unapplied_row` for a paper run, `no_bar_exit` for a held name whose bars stop (all off by default).
- **Twin:** `evaluation/target_weights_engine.py` simulates the same path, and tracks Lean above 0.99 daily correlation.
- **Sources:** `premia_signals.py` (rule sleeves as pure functions of what is known at each equity close: `sleeve_signal`, `signal_to_weights`, `scale_and_cap`), and `generation_blend.py` (below).
- **Costs:** `financing.py::daily_financing_usd` adds margin interest, stock borrow and FX swap, which Lean doesn't charge.
- **Idle cash:** `cash_sweep.py` (`phase_v2.cash_sweep`) sweeps into T-bills (BIL) under the no-borrow and margin limits.

## Generations

`generation_blend.py` (stdlib only) shares a book among generations: `update_generation_shares` (a ladder), `dynamic_generation_shares` (shares from each record), `blend_generation_rows`. Off by default; see RUNBOOK "Research cycle".

## The rank-based book

Trained and tested, not trading (`phase_v2.portfolio_book`).

**`book_construction.py::build_rank_based_book()`** picks top and bottom N by predicted rank. A symbol absent from the result means no view, not flat.

- **Own package:** it sees the whole universe and sets direction, which per-symbol sizing can't do. A book pick still passes the analyzer's safety tiers.
- **Direction:** `book_role_multiplier` (+1 or -1) is the one sizing input that sets direction. Lean opens the short through `SetHoldings`, bounded by `phase9.portfolio.max_short_exposure`.
- **Disengaging:** `min_rank_confidence_spread` is a floor on long minus short rank; below it, or with one side missing, the book returns `{}`.
- **Hysteresis:** `hysteresis_rank_margin` keeps an incumbent just past the cutoff, which cuts turnover. `remember_formed_book()` keeps that memory through a veto.
- **Slots:** one pooled ranking by default; `per_asset_class_slots` gives each class its own budget. Per-class caps still apply after selection, and `apply_class_weight_caps` bounds crypto.
- **Ownership:** `update_book_owned_symbols()` marks what the book opened, `is_rotation_exit_candidate()` limits rotation exits to those, and `should_hold_owned_position_on_veto()` keeps them through a veto.

**`main.py::on_data()`** runs in two passes, because a book needs every rank first: inference for all symbols, then `build_rank_based_book()`, then sizing, liquidity, analyzer and orders. Disabled, order and behaviour are unchanged.

**`book_neutrality.py::apply_book_neutrality()`** sizes the selected book: per-name cap, sector-neutral demean, dollar-neutral (scaling the larger leg down, never up), gross cap. `reapply_sector_cap_after_dollar_neutral` keeps the sector cap true at the end, which the Lean 4 proofs found the dollar step could break. The offline simulator calls the same function.

**HRP (`phase_v2.portfolio_book.allocation_method: "hrp"`)** re-weights the same selection with inverse-variance weights (`hrp_allocation.py`, Lopez de Prado 2016). Thin history falls back to equal weight per leg, and the default `"rank"` never imports scipy.

**`rank_signal.py`:** the head blend the live book reads, with promotion gates, grouped ranks and `sector_relative` normalization. `rolling_ic_gate.py` vetoes a rebalance on trailing IC.

## Sleeves

- **`legacy_sleeve.py` (`phase_v2.legacy_sleeve`):** budgets the old probability-up signal: `max_gross_exposure`, `max_weight_per_name`, no entries while the book is vetoed.
- **`class_sleeve.py`:** a small, separately budgeted long/short book over one class, for bonds and forex. `forex_sleeve.py`: forex weights and a dollar deadband.
- **`sleeve_guard.py`:** `evaluate_sleeve_guard`, a loss guard with a cooldown (`phase_v2.sleeve_guards`).
- **`trend_sleeve.py` (`phase_v2.trend_sleeve`, off):** directional time-series momentum.
- **`direction_overlay.py`:** a calibrated direction probability on ranks. Offline until a rule adopts it.
- **`wide_signals.py`:** the research universe's tables, masked to members or liquid coins.

## Options

Wired end to end, verified on Lean's samples, never on a real Gateway (#58-#61). Off by default (`phase_v2.options_risk`).

- **`options_strategy.py`:** `build_options_position_sizing()` turns direction and confidence into a target delta, picks the nearest contract and sizes it by a vega budget. `MULTI_LEG_STRATEGY_REGISTRY` covers <!--fact:options.structures-->43<!--/fact--> `OptionStrategies` factories through shared shape selectors (`phase_v2.options_risk.multi_leg_strategies_enabled`).
- **`options_margin_sizing.py`:** sizes what a vega budget can't: naked shorts, ladders, backspreads.
- **`options_arbitrage_detector.py`:** one-sided edge at bid and ask, parity net of dividends.
- **`options_assignment_risk.py`:** dividend-driven early assignment; puts always score 0.
- **`rerank_enabled_strategies_by_score()`:** the learned selector's plug point, dormant until options trade.

Single bonds aren't tradable in this Lean version, so `features/bond_features.py` models duration for the bond ETFs instead.
