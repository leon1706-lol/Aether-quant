"""
Lean algorithm for Aether Quant.

Phase 4 adds the first end-to-end inference loop:
- load the exported model JSON and scaler
- recreate the training features inside Lean
- run a forward pass locally from the exported architecture
- emit simple buy/sell/hold signals and conservative target weights
- keep the dashboard state updated with probabilities and feature readiness
"""

import os

# Lean's own AlgorithmImports bridge pulls in matplotlib (for its charting
# support), which defaults to a per-container cache directory - and Lean CLI
# runs each backtest in a fresh Docker container, so that cache never
# persists and matplotlib rebuilds its font list from scratch every single
# run (20-40+ seconds, a meaningful chunk of Lean's hard 90-second
# Initialize() isolator budget - see Problems.md #16). Redirecting it to a
# directory inside this mounted project folder makes the cache survive
# across container runs, so only the very first run ever pays this cost.
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".matplotlib_cache"))

import bisect
import json
import math
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from AlgorithmImports import *
from risk_controls import (
    active_position_limit_reached,
    assess_drawdown_lock,
    cap_target_weight,
    is_backtest_safety_bypass_active,
)
from analyzer import build_market_analysis_decision
from moe import EXPERT_NAMES, build_gating_decision
from regime import build_market_regime_vector
from risk.asset_class_router import route_position_sizing
from risk.futures_risk import load_futures_contract_specs
from risk.manual_override import read_manual_trade_lock_override
from risk.position_sizing import build_dynamic_position_sizing
from portfolio import build_rank_based_book
from liquidity import TYPICAL_SPREAD_BY_TYPE, build_liquidity_decision, estimate_high_low_spread
from topology import apply_learned_topology, build_market_topology, liquidity_score_from_decision
from experience import (
    ExperienceQueue,
    SimulatedPortfolioState,
    build_experience_event,
    build_session_summary_event,
    compute_observation_summary,
)
from execution import (
    MAX_LIQUIDITY_SLIPPAGE_BPS,
    classify_order_status,
    credentials_present,
    evaluate_broker_config,
    liquidity_cost_fraction,
    resolve_fill_slippage,
    resolve_fill_slippage_source,
    resolve_limit_price,
    resolve_order_permission,
    resolve_runtime_mode,
    resolve_slippage_bps,
)
from execution.live_credentials_io import load_live_credentials
from execution.paper_readiness_io import read_paper_trading_config
from inference import (
    build_models_batched_cache,
    build_multitask_models_batched_cache,
    convert_state_dict_arrays,
    init_worker,
    resolve_sequence_window_size,
    run_exported_model,
    run_exported_multitask_model,
    run_exported_multitask_models_batched,
    run_exported_models_batched,
    run_exported_sequence_multitask_model,
    run_symbol_inference,
)
from features import (
    average_true_range_pct,
    bollinger_pctb,
    bond_yield_curve_slope,
    compute_greeks,
    credit_spread_level,
    credit_spread_proxy,
    cross_sectional_momentum_rank,
    crypto_risk_appetite_proxy,
    distance_from_52w_high,
    empirical_duration_beta,
    futures_term_structure_slope,
    implied_volatility,
    macd_histogram_normalized,
    options_implied_vol_skew,
    options_put_call_ratio,
    relative_strength_index,
    volume_zscore,
    yield_curve_curvature,
    yield_curve_level,
    yield_curve_slope_proxy,
)
from data_pipeline.fred_backfill import load_cached_fred_series
from performance import evaluate_all_triggers

# volume_change_1d clamp bounds - must match train.py::VOLUME_CHANGE_FLOOR/
# VOLUME_CHANGE_CEILING exactly for train/runtime feature parity. Duplicated
# (not imported) since main.py never imports train.py (heavy training-only
# deps like torch/sklearn have no place in the Lean runtime).
VOLUME_CHANGE_FLOOR = -1.0
VOLUME_CHANGE_CEILING = 20.0


class _LiquidityAwareSlippageModel:
    """Lean SlippageModel that charges the algorithm's own already-computed
    per-symbol liquidity cost estimate on every fill, instead of Lean's
    default zero-slippage fill.

    Reuses liquidity/market_liquidity.py's LiquidityDecision (price impact
    + bid-ask spread, or impact alone - see
    phase_v2.liquidity.fill_slippage.source below - already computed every
    bar for position-sizing/routing decisions in on_data()'s Pass 2,
    previously only ever used to gate/resize orders, never applied to an
    actual fill price) via self._algorithm.latest_liquidity_slippage_bps,
    a plain dict keyed by str(symbol) and refreshed every bar in on_data().
    All lookup/clamp/apply math lives in execution.order_gate's pure,
    unit-tested functions - this class is just the thin adapter unpacking
    Lean's asset/order objects into plain values, matching every other
    Lean-wiring pattern in this file.

    Two config knobs (`phase_v2.liquidity.fill_slippage`, read once in
    _ensure_ready()): `source` ("round_trip", default, or "impact_only" -
    execution.order_gate.liquidity_cost_fraction()'s choice of which
    LiquidityDecision field to convert to bps) and `max_bps` (the clamp
    ceiling, default execution.order_gate.MAX_LIQUIDITY_SLIPPAGE_BPS) - so
    either the cost estimate or its ceiling can be retuned via
    `aq config set` without a code change if the default proves too
    aggressive or too permissive.

    Duck-typed against Lean's ISlippageModel (a GetSlippageApproximation(
    asset, order) method returning a positive price-delta that Lean itself
    applies in the direction unfavorable to the trader) - no explicit base
    class needed, matching how Lean's own Python API examples define custom
    slippage models.
    """

    def __init__(self, algorithm) -> None:
        self._algorithm = algorithm

    def GetSlippageApproximation(self, asset, order):
        return resolve_fill_slippage(
            str(asset.Symbol),
            float(asset.Price),
            self._algorithm.latest_liquidity_slippage_bps,
            max_bps=self._algorithm._liquidity_slippage_max_bps,
        )


class AetherQuantAlgorithm(QCAlgorithm):
    """Lean algorithm with JSON-model inference and a basic signal engine."""

    def initialize(self) -> None:
        # Lean's AlgorithmFactory.Loader wraps module import + Initialize()
        # in a hard, non-configurable 90-second isolator timeout. Subscribing
        # securities (the loop below) must happen here - Lean only calls
        # on_data() once subscriptions exist - and its cost scales with the
        # asset count (20 assets vs the old 10 roughly doubles it). Every
        # other setup step below (model/expert/topology artifact loading,
        # derived risk/regime/topology/liquidity config, broker/experience
        # setup) does NOT need to exist before on_data() fires, so it's
        # deferred into _ensure_ready(), run once on the first on_data()
        # call, which carries no such time limit. See Problems.md for the
        # original 20-asset regression this fixes.
        self.root_path = Path(__file__).resolve().parent
        self.state_path = self.root_path / "visualization" / "state.json"
        self.scene_path = self.root_path / "visualization" / "scene.json"
        self.topology_state_path = self.root_path / "visualization" / "topology_state.json"
        self.grafana_dir = self.root_path / "visualization" / "grafana"
        self.runtime_metrics_path = self.grafana_dir / "runtime_metrics_snapshot.json"
        self.runtime_asset_metrics_path = self.grafana_dir / "runtime_asset_metrics.csv"
        self.observation_summary_path = self.grafana_dir / "observation_summary.json"
        self.observation_equity_curve_path = self.grafana_dir / "observation_equity_curve.csv"
        self.performance_triggers_path = self.grafana_dir / "performance_triggers.json"
        self.model_path = self.root_path / "ml" / "model_weights.json"
        self.expert_model_dir = self.root_path / "ml" / "expert_models"
        self.expert_metrics_path = self.root_path / "ml" / "expert_training_metrics.json"
        self.feature_schema_path = self.root_path / "ml" / "feature_schema.json"
        self.scaler_stats_path = self.root_path / "ml" / "scaler_stats.json"
        self.dataset_manifest_path = self.root_path / "ml" / "dataset_manifest.json"
        self.topology_model_path = self.root_path / "ml" / "topology_model.json"
        self.topology_feature_schema_path = self.root_path / "ml" / "topology_feature_schema.json"
        self.gating_model_path = self.root_path / "ml" / "gating_model.json"
        self.gating_feature_schema_path = self.root_path / "ml" / "gating_feature_schema.json"
        self.multitask_model_path = self.root_path / "ml" / "multitask_model.json"
        self.multitask_feature_schema_path = self.root_path / "ml" / "multitask_feature_schema.json"
        self.sequence_model_path = self.root_path / "ml" / "sequence_model.json"
        self.sequence_feature_schema_path = self.root_path / "ml" / "sequence_feature_schema.json"

        self._validate_runtime_artifacts()
        self.config = self._load_json(self.root_path / "config.json")
        self.phase1 = self.config["phase1"]
        self.runtime = self.config["runtime"]
        self._ready = False

        self.resolution = self._resolve_resolution(self.phase1["universe"]["resolution"])
        backtest_window = self.phase1["windows"]["backtest"]
        start_year, start_month, start_day = map(int, backtest_window["start"].split("-"))
        end_year, end_month, end_day = map(int, backtest_window["end"].split("-"))
        self.set_start_date(start_year, start_month, start_day)
        self.set_end_date(end_year, end_month, end_day)
        self.set_cash(float(self.runtime["initial_cash"]))

        self.symbols = []
        self.asset_lookup = {}
        self.ticker_to_symbol = {}
        self.symbol_windows = {}
        # Phase 6 long-lookback indicators (macd_histogram_norm/
        # dist_52w_high) need more history than self.symbol_windows'
        # deliberately-fixed 25-bar size (main.py:264-268 explains why that
        # one is never resized) - a SEPARATE, longer buffer, matching
        # train.py::LONG_LOOKBACK_WINDOW_BARS exactly for train/runtime
        # parity (features/technical_indicators.py's long indicators
        # recompute fresh from whatever window they're given, so the
        # window size itself must match, not just the formula).
        self.symbol_long_windows = {}
        self.long_bar_history_size = 260
        # Paired with symbol_long_windows (same length, same append point in
        # on_data()) so a bond-tagged symbol's own close-return history and
        # the 10yr Treasury yield level as-of that same bar stay index-
        # aligned per symbol, regardless of any other symbol's data gaps -
        # see _build_model_input()'s bond_empirical_duration_beta block.
        self.symbol_treasury_10yr_history = {}
        self.latest_momentum_by_symbol = {}
        self.latest_signal_state = {}
        self.last_trade_bar_by_symbol = {}
        # Position-close/exposure tracking for options (A7): main.py's
        # canonical chain Symbol (self.ticker_to_symbol[asset["ticker"]])
        # is what every other per-symbol dict here is keyed by, but a real
        # options ORDER executes on a specific CONTRACT Symbol
        # (OptionsPositionDecision.contract_symbol) - a different Lean
        # object. Without this pair of maps, _is_invested()/the sell and
        # hold-liquidate branches/_asset_class_exposure() would all still
        # look at the (never-invested) chain Symbol and never find the
        # real position - see _apply_signal()'s "option" branches.
        self.option_contract_symbol_by_symbol: dict[str, object] = {}
        self.symbol_key_by_option_contract_symbol: dict[str, str] = {}
        # Real limit-order support (execution/risk realism pass, part 2):
        # in-flight limit orders this algorithm is currently waiting to
        # fill, keyed by str(symbol) - the canonical chain-Symbol string
        # (deliberately NOT last_trade_bar_by_symbol's raw-Symbol-object
        # keying just above - that inconsistency is a pre-existing
        # landmine, not a pattern to copy). For options, keyed by the
        # CHAIN symbol_key (matching every other per-symbol dict here)
        # even though the real order/OrderTicket targets the CONTRACT
        # symbol - see _try_submit_limit_order()'s docstring. See
        # execution/README.md's "Real limit orders" section for the full
        # design; empty/unused whenever phase_v2.limit_orders.enabled is
        # False (the default).
        self.pending_limit_orders: dict[str, dict] = {}
        self.bar_history_size = 25
        # Most recent per-symbol liquidity/market_liquidity.py
        # estimated_round_trip_cost, in bps - refreshed every bar in Pass 2
        # of on_data(), read by _LiquidityAwareSlippageModel (real Lean
        # fills, below) and threaded into SimulatedPortfolioState.enter_long()
        # (observation-mode fills) so both paths charge the same estimate.
        # Must exist before _add_asset()'s SetSlippageModel() call, hence
        # initialized here rather than in _ensure_ready(). max_bps gets a
        # safe hardcoded default here; _ensure_ready() overwrites it with
        # the real phase_v2.liquidity.fill_slippage.max_bps config value
        # (read before any real order can be placed) - this is only a
        # fallback in case GetSlippageApproximation is ever somehow called
        # before _ensure_ready() has run once.
        self.latest_liquidity_slippage_bps: dict[str, float] = {}
        self._liquidity_slippage_max_bps = MAX_LIQUIDITY_SLIPPAGE_BPS
        self._liquidity_slippage_model = _LiquidityAwareSlippageModel(self)

        for asset in self.phase1["universe"]["assets"]:
            symbol = self._add_asset(asset)
            if symbol is None:
                continue

            ticker = asset["ticker"]
            self.symbols.append(symbol)
            self.asset_lookup[str(symbol)] = asset
            self.ticker_to_symbol[ticker] = symbol
            self.symbol_windows[symbol] = deque(maxlen=self.bar_history_size)
            self.symbol_long_windows[symbol] = deque(maxlen=self.long_bar_history_size)
            self.symbol_treasury_10yr_history[symbol] = deque(maxlen=self.long_bar_history_size)
            self.latest_signal_state[str(symbol)] = "hold"
            self.last_trade_bar_by_symbol[symbol] = -1000000
            self.securities[symbol].fee_model = InteractiveBrokersFeeModel()

        self.set_warm_up(max(int(self.runtime["warmup_bars"]), 21), self.resolution)

    def _ensure_ready(self) -> None:
        """One-time setup deferred out of initialize() (see the comment
        there) - loads model/expert/topology artifacts and derives every
        risk/regime/topology/liquidity/broker/experience config value. Runs
        once, on the first on_data() call."""
        if self._ready:
            return

        self.phase3 = self.config["phase3"]
        self.phase5 = self.config.get("phase5", {})
        self.phase6 = self.config.get("phase6", {})
        self.phase9 = self.config.get("phase9", {})
        self.phase_v2 = self.config.get("phase_v2", {})
        self.model_export = self._load_json(self.model_path)
        convert_state_dict_arrays(self.model_export)
        self.expert_training_metrics = self._load_json(self.expert_metrics_path) if self.expert_metrics_path.exists() else {}
        self.expert_model_exports = self._load_expert_model_exports()
        self.feature_schema = self._load_json(self.feature_schema_path)
        self.scaler_stats = self._load_json(self.scaler_stats_path)
        self.dataset_manifest = self._load_json(self.dataset_manifest_path) if self.dataset_manifest_path.exists() else {}

        self.base_feature_names = list(self.feature_schema["feature_names"])
        self.scaled_feature_names = list(self.feature_schema["scaled_feature_names"])
        self.categorical_feature_names = list(self.feature_schema.get("categorical_feature_names", []))
        self.context_feature_names = list(self.feature_schema.get("context_feature_names", []))
        self.model_input_names = list(self.feature_schema.get("model_input_names", self.scaled_feature_names))

        phase5_backtest = self.phase5.get("backtest", {})
        phase6_risk = self.phase6.get("risk", {})
        self.phase_v2_paper_trading = self.phase_v2.get("paper_trading", {})
        self.phase_v2_live = self.phase_v2.get("live", {})
        self._live_credentials = load_live_credentials()
        phase9_portfolio = self.phase9.get("portfolio", {})
        phase_v2_risk = self.phase_v2.get("dynamic_risk", {})
        phase_v2_regime = self.phase_v2.get("regime_detection", {})
        phase_v2_gating = self.phase_v2.get("gating_network", {})
        phase_v2_analyzer = self.phase_v2.get("market_analyzer", {})
        phase_v2_topology = self.phase_v2.get("topology", {})
        phase_v2_backtest = self.phase_v2.get("backtest", {})
        phase_v2_portfolio_book = self.phase_v2.get("portfolio_book", {})

        self.decision_threshold = float(self.model_export["training"]["decision_threshold"])
        self.buy_threshold = min(0.75, self.decision_threshold + float(phase5_backtest.get("buy_threshold_offset", 0.08)))
        self.sell_threshold = max(0.25, self.decision_threshold - float(phase5_backtest.get("sell_threshold_offset", 0.08)))
        self.max_position_weight = float(phase6_risk.get("max_position_weight", 0.25))
        self.min_confidence_to_trade = float(phase6_risk.get("min_confidence_to_trade", 0.12))
        self.trade_cooldown_bars = int(phase6_risk.get("trade_cooldown_bars", 3))
        self.max_daily_drawdown_pct = float(phase6_risk.get("max_daily_drawdown_pct", 0.03))
        self.max_total_drawdown_pct = float(phase6_risk.get("max_total_drawdown_pct", 0.12))
        self.liquidate_on_risk_breach = bool(phase6_risk.get("liquidate_on_risk_breach", True))
        # Opt-in, statistical/diagnostic-only: see risk_controls.py::is_backtest_safety_bypass_active()'s
        # docstring and Problems.md for why this is a dedicated flag, not
        # aq trade-lock's on/off/auto override. Defaults False (gates
        # active) and only ever takes effect when self.runtime_mode is
        # literally "backtest" - never in paper/live.
        self.bypass_safety_gates = bool(phase_v2_backtest.get("bypass_safety_gates", False))
        self.asset_quality = self.dataset_manifest.get(
            "asset_quality",
            self.feature_schema.get("asset_quality", {}),
        )
        self.trading_eligible_tickers = set(
            self.dataset_manifest.get(
                "trading_eligible_assets",
                self.feature_schema.get("trading_eligible_assets", []),
            )
        )
        self.observation_only_assets_can_trade = bool(phase9_portfolio.get("observation_only_assets_can_trade", False))
        self.max_active_positions = int(phase9_portfolio.get("max_active_positions", 5))
        self.max_equity_exposure = float(phase9_portfolio.get("max_equity_exposure", 0.65))
        self.max_crypto_exposure = float(phase9_portfolio.get("max_crypto_exposure", 0.25))
        # Phase: multi-asset-class support - mirrors max_equity_exposure/
        # max_crypto_exposure exactly, keyed by asset_class rather than
        # Lean's own security_type (see _asset_class_exposure()'s
        # docstring for why those two are deliberately different concepts).
        self.exposure_caps_by_asset_class = {
            "equity": self.max_equity_exposure,
            "crypto": self.max_crypto_exposure,
            "bond": float(phase9_portfolio.get("max_bond_exposure", 0.30)),
            "future": float(phase9_portfolio.get("max_futures_exposure", 0.20)),
            "option": float(phase9_portfolio.get("max_options_exposure", 0.10)),
        }
        # Phase 3 of the 5/10 -> 9/10 roadmap: a portfolio-book-only cap -
        # short-selling doesn't exist anywhere else in this codebase, so
        # this is the only exposure cap that bounds it. Independent of the
        # book's own enabled/off switch below - stays a safety ceiling even
        # if someone enables the book without touching this default.
        self.max_short_exposure = float(phase9_portfolio.get("max_short_exposure", 0.30))
        # Phase 3 of the 5/10 -> 9/10 roadmap: off by default, same
        # precedent as rank_sizing_enabled - see portfolio/book_construction.py's
        # module docstring for why this is the one signal in this codebase
        # allowed to SET direction rather than only scale an already-decided
        # trade's magnitude.
        self.portfolio_book_enabled = bool(phase_v2_portfolio_book.get("enabled", False))
        self.portfolio_book_top_n = int(phase_v2_portfolio_book.get("top_n", 3))
        self.portfolio_book_bottom_n = int(phase_v2_portfolio_book.get("bottom_n", 3))
        self.portfolio_book_min_rank_confidence_spread = float(
            phase_v2_portfolio_book.get("min_rank_confidence_spread", 0.2)
        )
        self.target_daily_volatility = float(phase_v2_risk.get("target_daily_volatility", 0.015))
        self.low_volatility_threshold = float(phase_v2_risk.get("low_volatility_threshold", 0.01))
        self.high_volatility_threshold = float(phase_v2_risk.get("high_volatility_threshold", 0.03))
        self.min_volatility_multiplier = float(phase_v2_risk.get("min_volatility_multiplier", 0.35))
        self.max_volatility_multiplier = float(phase_v2_risk.get("max_volatility_multiplier", 1.25))
        self.min_dynamic_position_weight = float(phase_v2_risk.get("min_position_weight", 0.0))
        self.max_leverage = float(phase_v2_risk.get("max_leverage", 1.0))
        # Learned-topology sizing input (see risk/position_sizing.py::
        # topology_sizing_multiplier()) - a bounded, continuous, shrink-only
        # adjustment, never a new trade-blocking gate. Independent kill
        # switch from phase_v2.topology_learning.enabled, which also gates
        # the unrelated dashboard/retrain-trigger consumers of the same
        # overlay.
        self.topology_sizing_enabled = bool(phase_v2_risk.get("topology_sizing_enabled", True))
        self.min_topology_multiplier = float(phase_v2_risk.get("min_topology_multiplier", 0.5))
        self.max_topology_multiplier = float(phase_v2_risk.get("max_topology_multiplier", 1.0))
        # Cross-sectional rank_20d sizing input (see risk/position_sizing.py::
        # rank_sizing_multiplier()) - a bounded, continuous, direction-
        # preserving adjustment, never a new trade-blocking gate. Default
        # OFF: the rank_20d signal's full backtest series is significant
        # (IC 0.073, t=4.40) but its non-overlapping-date subsample is not
        # yet independently significant (t=1.20) - see development/
        # Changelog.md's "frontier-model edge investigation" entry.
        self.rank_sizing_enabled = bool(phase_v2_risk.get("rank_sizing_enabled", False))
        self.min_rank_multiplier = float(phase_v2_risk.get("min_rank_multiplier", 0.75))
        self.max_rank_multiplier = float(phase_v2_risk.get("max_rank_multiplier", 1.25))
        self.regime_bullish_threshold = float(phase_v2_regime.get("bullish_threshold", 0.02))
        self.regime_bearish_threshold = float(phase_v2_regime.get("bearish_threshold", -0.02))
        self.regime_risk_off_drawdown_threshold = float(phase_v2_regime.get("risk_off_drawdown_threshold", 0.08))
        self.regime_risk_on_drawdown_threshold = float(phase_v2_regime.get("risk_on_drawdown_threshold", 0.03))
        self.regime_high_correlation_threshold = float(phase_v2_regime.get("high_correlation_threshold", 0.75))
        self.gating_baseline_weight = float(phase_v2_gating.get("baseline_weight", 0.25))
        self.gating_learned_model_enabled = bool(phase_v2_gating.get("learned_model_enabled", True))
        # Optional Phase 2 sequence-encoder blend into the gating decision
        # (moe/gating.py::build_gating_decision()'s sequence_prediction/
        # sequence_weight params) - off by default (0.0), matching
        # use_predicted_volatility's convention for any new signal that
        # changes final_probability_up itself, not just a sizing
        # multiplier. See moe/README.md.
        self.gating_sequence_weight = float(phase_v2_gating.get("sequence_weight", 0.0))
        phase_v2_multitask = self.phase_v2.get("multitask_model", {})
        self.multitask_model_enabled = bool(phase_v2_multitask.get("enabled", True))
        self.use_predicted_volatility = bool(phase_v2_risk.get("use_predicted_volatility", False))
        self.analyzer_retrain_min_regime_confidence = float(phase_v2_analyzer.get("retrain_min_regime_confidence", 0.20))
        self.analyzer_low_regime_confidence_threshold = float(phase_v2_analyzer.get("low_regime_confidence_threshold", 0.35))
        self.analyzer_use_composite_signal_score = bool(phase_v2_analyzer.get("use_composite_signal_score", False))
        self.topology_correlation_threshold = float(phase_v2_topology.get("correlation_threshold", 0.6))
        self.topology_link_threshold = float(phase_v2_topology.get("link_threshold", 0.5))
        self.topology_min_observations = int(phase_v2_topology.get("min_observations", 5))
        self.topology_embedding_iterations = int(phase_v2_topology.get("embedding_iterations", 100))
        self.topology_warm_start_enabled = bool(phase_v2_topology.get("warm_start_enabled", True))
        self.topology_convergence_tolerance = float(phase_v2_topology.get("convergence_tolerance", 0.01))
        self.topology_top_peers_n = int(phase_v2_topology.get("top_peers_n", 3))
        # Phase 1b of the 5/10 -> 9/10 roadmap: deliberate, explicit
        # cross-asset "macro" features (features/macro_features.py) -
        # mirrors train.py::DEFAULT_MACRO_REFERENCE_TICKERS exactly for
        # train/runtime parity, overridable via the same config key.
        self.macro_reference_tickers = {
            "long_duration": "TLT",
            "short_duration": "SHY",
            "high_yield": "HYG",
            "investment_grade": "LQD",
            "crypto": "BTCUSD",
            **self.phase1.get("features", {}).get("macro_reference_tickers", {}),
        }
        # Derivatives-macro sibling of macro_reference_tickers above - one
        # reference underlying per broadcast signal (futures term structure
        # needs one futures ticker; options sentiment needs one options
        # underlying), since these are broadcast, once-per-bar, cross-asset
        # macro features (see _build_derivatives_macro_payload()), not
        # computed per-asset. Neutral-defaults (0.0) whenever the reference
        # ticker isn't actually configured/subscribed in this universe.
        self.derivatives_reference_tickers = {
            "futures_term_structure": "ES",
            "options_sentiment": "SPY",
            **self.phase1.get("features", {}).get("derivatives_reference_tickers", {}),
        }
        # Real yield-curve/credit-spread data (data_pipeline/fred_backfill.py)
        # - loaded ONCE here from the local cache, never fetched live
        # mid-backtest (Lean backtests are date-bounded). {} if the cache
        # was never populated (fresh clone) - every bond feature below then
        # neutral-defaults to 0.0, same convention as a missing macro
        # reference ticker.
        self.fred_series = load_cached_fred_series()
        # Static offline/backtest fallback margin reference
        # (risk/futures_risk.py) - {} if the file is missing/unparseable,
        # which just means build_futures_position_sizing() finds no spec
        # for any ticker and sizes it to zero contracts, never a crash.
        self.futures_contract_specs = load_futures_contract_specs()
        phase_v2_futures_risk = self.phase_v2.get("futures_risk", {})
        self.futures_risk_enabled = bool(phase_v2_futures_risk.get("enabled", False))
        self.futures_target_margin_utilization = float(phase_v2_futures_risk.get("target_margin_utilization", 0.20))
        self.futures_max_margin_utilization = float(phase_v2_futures_risk.get("max_margin_utilization", 0.40))
        phase_v2_options_risk = self.phase_v2.get("options_risk", {})
        self.options_risk_enabled = bool(phase_v2_options_risk.get("enabled", False))
        self.options_target_delta_at_full_confidence = float(phase_v2_options_risk.get("target_delta_at_full_confidence", 0.60))
        self.options_max_vega_budget_pct_of_equity = float(phase_v2_options_risk.get("max_vega_budget_pct_of_equity", 0.02))
        self.options_risk_free_rate = float(phase_v2_options_risk.get("risk_free_rate", 0.045))
        self.options_iv_solver_max_iterations = int(phase_v2_options_risk.get("iv_solver_max_iterations", 100))
        self.options_iv_solver_tolerance = float(phase_v2_options_risk.get("iv_solver_tolerance", 1e-06))
        phase_v2_topology_learning = self.phase_v2.get("topology_learning", {})
        self.topology_learning_enabled = bool(phase_v2_topology_learning.get("enabled", True))
        self.topology_learning_temperature = float(phase_v2_topology_learning.get("temperature", 0.35))
        self.topology_learning_top_n_neighbors = int(phase_v2_topology_learning.get("top_n_neighbors", 3))
        self.topology_learning_min_confidence = float(phase_v2_topology_learning.get("min_confidence_for_learned", 0.2))
        self.topology_learning_max_offset_xy = float(phase_v2_topology_learning.get("max_offset_xy", 6.0))
        self.topology_learning_max_offset_z = float(phase_v2_topology_learning.get("max_offset_z", 0.1))
        self.learned_topology_model, self.learned_topology_feature_schema = self._load_learned_topology_model()
        self.gating_model, self.gating_feature_schema = self._load_gating_model()
        self.multitask_model, self.multitask_feature_schema = self._load_multitask_model()
        self.expert_multitask_model_exports = self._load_expert_multitask_exports()

        # Precomputed once here (never rebuilt per-bar) - expert exports
        # never change after this point in a run, so the same weight/bias
        # stacks run_exported_models_batched()/run_exported_multitask_models_batched()
        # would otherwise rebuild via np.stack() on every single bar can be
        # built exactly once. None whenever batching wouldn't apply anyway
        # (fewer than 2 experts loaded, mismatched architectures) - the
        # batched functions' own fallback path handles that identically
        # whether the cache is None or simply absent.
        self.expert_models_stack_cache = build_models_batched_cache(
            [self.expert_model_exports.get(expert_name) for expert_name in EXPERT_NAMES]
        )
        self.expert_multitask_models_stack_cache = build_multitask_models_batched_cache(
            [self.expert_multitask_model_exports.get(expert_name) for expert_name in EXPERT_NAMES]
        )

        # Phase 2 (sequence encoder, additive/graceful-fallback; can
        # optionally blend into gating - see gating_sequence_weight above):
        # a per-symbol rolling buffer of already-computed flat
        # model_inputs vectors (see _build_model_input()) - reusing that
        # vector directly, not recomputing regime/liquidity/topology per
        # historical bar, matches train.py::build_sequence_tensor_dataset()'s
        # exact offline windowing (see train_sequence.py). Deliberately a
        # SEPARATE buffer from self.symbol_windows (raw OHLCV, sized to
        # match train.py's CROSS_SECTIONAL_WINDOW_BARS for Stage 1-3
        # feature parity) rather than reusing/resizing it - changing
        # symbol_windows' length would silently break that parity.
        phase_v2_sequence = self.phase_v2.get("sequence_model", {})
        self.sequence_model_enabled = bool(phase_v2_sequence.get("enabled", True))
        self.sequence_model, self.sequence_feature_schema = self._load_sequence_model()
        self.sequence_window_size = resolve_sequence_window_size(
            self.sequence_feature_schema, int(phase_v2_sequence.get("window_size", 30))
        )
        self.symbol_feature_history = {symbol: deque(maxlen=self.sequence_window_size) for symbol in self.symbols}

        # Opt-in per-symbol multiprocessing for Pass 1's inference cluster
        # (see inference/parallel_inference.py's module docstring for the
        # full honest tradeoff writeup) - default off. Windows'
        # ProcessPoolExecutor uses the `spawn` start method, which
        # re-bootstraps a fresh interpreter per worker; this has never run
        # inside Lean's own embedded-Python runtime (not a standard
        # python.exe process tree), so pool creation is wrapped in its own
        # try/except - ANY failure here, including at Initialize() time,
        # permanently falls back to self._inference_pool = None (the
        # always-correct sequential path main.py has always used), never
        # a crash that takes the whole algorithm down.
        phase_v2_inference_parallelism = self.phase_v2.get("inference_parallelism", {})
        self.inference_parallelism_enabled = bool(phase_v2_inference_parallelism.get("enabled", False))
        self._inference_pool: ProcessPoolExecutor | None = None
        if self.inference_parallelism_enabled:
            worker_count = int(phase_v2_inference_parallelism.get("worker_count", min(4, os.cpu_count() or 1)))
            worker_model_exports = {
                "baseline": self.model_export,
                "experts": self.expert_model_exports,
                "expert_names": list(EXPERT_NAMES),
                "expert_stack_cache": self.expert_models_stack_cache,
                "multitask": self.multitask_model,
                "expert_multitask": self.expert_multitask_model_exports,
                "expert_multitask_stack_cache": self.expert_multitask_models_stack_cache,
                "sequence": self.sequence_model,
            }
            try:
                self._inference_pool = ProcessPoolExecutor(
                    max_workers=worker_count, initializer=init_worker, initargs=(worker_model_exports,)
                )
            except Exception as error:
                self.Debug(f"Inference parallelism pool failed to start, falling back to sequential: {error}")
                self._inference_pool = None

        phase_v2_liquidity = self.phase_v2.get("liquidity", {})
        self._liquidity_thresholds = {
            "thin_participation_threshold": float(phase_v2_liquidity.get("thin_participation_threshold", 0.002)),
            "high_impact_participation_threshold": float(phase_v2_liquidity.get("high_impact_participation_threshold", 0.01)),
            "blocked_participation_threshold": float(phase_v2_liquidity.get("blocked_participation_threshold", 0.05)),
            "min_daily_dollar_volume": float(phase_v2_liquidity.get("min_daily_dollar_volume", 100_000.0)),
            "high_impact_size_factor": float(phase_v2_liquidity.get("high_impact_size_factor", 0.5)),
            "slippage_factor": float(phase_v2_liquidity.get("slippage_factor", 0.1)),
        }
        phase_v2_spread_estimation = phase_v2_liquidity.get("spread_estimation", {})
        self._spread_estimation_enabled = bool(phase_v2_spread_estimation.get("enabled", True))
        self._spread_estimation_min_bars = int(phase_v2_spread_estimation.get("min_bars", 2))
        # Real fill slippage (execution/risk realism pass) - which
        # liquidity_payload field feeds _LiquidityAwareSlippageModel/
        # simulate_fill(), and the ceiling on how much slippage either path
        # will ever charge. See execution/order_gate.py's docstrings for
        # the "round_trip" vs "impact_only" rationale and why 500bps is a
        # degenerate-estimate guard, not a normal-path limiter.
        phase_v2_fill_slippage = phase_v2_liquidity.get("fill_slippage", {})
        self._liquidity_slippage_source = resolve_fill_slippage_source(phase_v2_fill_slippage.get("source"))
        self._liquidity_slippage_max_bps = float(
            phase_v2_fill_slippage.get("max_bps", MAX_LIQUIDITY_SLIPPAGE_BPS)
        )
        # Real limit-order support (execution/risk realism pass, part 2) -
        # config-gated, default OFF. When disabled, every routing call site
        # in _apply_signal()/_apply_option_order() takes the EXACT same
        # MarketOrder()/SetHoldings() branch it always has - this whole
        # block changes nothing about today's behavior unless explicitly
        # turned on. See execution/README.md's "Real limit orders" section
        # for the full design and development/Problems.md #34 for the
        # writeup, including the PascalCase/casing risks only a real Lean
        # backtest can settle.
        phase_v2_limit_orders = self.phase_v2.get("limit_orders", {})
        self.limit_orders_enabled = bool(phase_v2_limit_orders.get("enabled", False))
        self.limit_orders_asset_classes = set(
            phase_v2_limit_orders.get("asset_classes", ["equity", "crypto", "bond", "future", "option"])
        )
        self.limit_order_offset_multiplier = float(phase_v2_limit_orders.get("offset_multiplier", 1.0))
        self.limit_order_unfilled_timeout_bars = int(phase_v2_limit_orders.get("unfilled_timeout_bars", 3))
        # Per-asset-class, not a single global bool: a fallback market fill
        # is low-consequence for equity/crypto/bond (the same trade
        # SetHoldings would have placed anyway), but a real position the
        # model didn't choose at that price for future/option, where
        # margin/expiry mechanics make that a worse outcome than staying
        # flat and letting the model re-decide next bar - hence the
        # differing defaults below. Dict-merged so a partial config
        # override only changes the classes it mentions.
        self.limit_order_fallback_to_market_by_asset_class = {
            "equity": True, "crypto": True, "bond": True, "future": False, "option": False,
            **phase_v2_limit_orders.get("fallback_to_market_on_timeout", {}),
        }
        phase_v2_experience = self.phase_v2.get("experience", {})
        phase_v2_runtime = self.phase_v2.get("runtime", {})
        raw_runtime_mode = phase_v2_runtime.get("mode")
        self.runtime_mode = resolve_runtime_mode(raw_runtime_mode)
        if self.runtime_mode != raw_runtime_mode:
            self.Debug(f"Unknown phase_v2.runtime.mode={raw_runtime_mode!r}; falling back to '{self.runtime_mode}'")
        self.allow_live_orders = bool(phase_v2_runtime.get("allow_live_orders", False))
        self._recompute_broker_config()
        self._experience_mode = self.runtime_mode
        self._experience_queue = ExperienceQueue(
            enabled=bool(phase_v2_experience.get("enabled", False)),
            redis_url="redis://localhost:6380/0",
            stream_name=str(phase_v2_experience.get("redis_stream", "aether:experience")),
            maxlen=int(phase_v2_experience.get("maxlen", 100_000)),
        )
        self._simulated_portfolio = SimulatedPortfolioState(initial_cash=float(self.runtime["initial_cash"]))
        self._equity_curve_flushed_count = 0
        self._observation_event_log = deque(maxlen=5000)
        self._session_events: list[dict] = []
        self._performance_triggers_config = self.phase_v2.get("performance_triggers", {})

        self.last_state_write = None
        self.bar_index = 0
        self.current_session_date = None
        self.session_start_equity = float(self.runtime["initial_cash"])
        self.peak_equity = float(self.runtime["initial_cash"])
        self.current_daily_drawdown = 0.0
        self.current_total_drawdown = 0.0
        self.trade_lock_active = False
        self.trade_lock_reason = None
        self.latest_regime_by_symbol = {}
        self.latest_regime_risk_score_by_symbol = {}
        self.latest_liquidity_by_symbol = {}
        self.latest_learned_neighbors_by_symbol = {}
        self.latest_topology_payload = {}
        self.latest_macro_payload = {}
        self.latest_bond_payload = {}
        self.latest_options_chains_payload = {}
        self.latest_futures_chains_payload = {}
        self.latest_derivatives_macro_payload = {}
        self._previous_topology_positions: dict[str, tuple[float, float]] = {}

        self._ready = True
        self._write_state(mode="initialize", insight="Phase 4 inference engine initialized")

    def on_data(self, slice: Slice) -> None:
        if not self._ready:
            self._ensure_ready()

        if len(slice.Bars) == 0:
            return

        self.bar_index += 1
        self._refresh_risk_state()
        self._process_pending_limit_order_timeouts()
        self.latest_topology_payload = self._build_topology_payload()
        self.latest_macro_payload = self._build_macro_payload()
        self.latest_bond_payload = self._build_bond_payload()
        self.latest_options_chains_payload = self._build_options_chains_payload(slice)
        self.latest_futures_chains_payload = self._build_futures_chains_payload(slice)
        self.latest_derivatives_macro_payload = self._build_derivatives_macro_payload()
        topology_by_symbol = {node["symbol"]: node for node in self.latest_topology_payload.get("nodes", [])}
        signals: dict[str, dict] = {}
        close_prices_by_symbol: dict[str, float] = {}

        # ---- Pass 1 (Phase 3 of the 5/10 -> 9/10 roadmap): per-symbol
        # feature build + inference, through predicted_rank_20d and the
        # existing (pre-book) signal derivation - every symbol's rank_20d
        # for this bar must exist before ANY symbol's book role can be
        # decided (portfolio/book_construction.py needs the whole-universe
        # view at once). signal_payload is inserted into `signals` here,
        # in self.symbols order, for EVERY symbol with a bar - Pass 2 below
        # only ever mutates these same dict objects in place (never
        # re-inserts), so key order/content is byte-identical to the
        # previous single-pass loop whenever the book is disabled.
        pass1_state: dict[str, dict] = {}
        book_candidates: dict[str, dict] = {}

        # Phase 1a: per-symbol feature build - cheap, stays sequential
        # regardless of self._inference_pool (depends on ordered, append-
        # only mutation of self.symbol_long_windows/self.symbol_windows/
        # self.symbol_treasury_10yr_history/self.symbol_feature_history in
        # self.symbols order, which other consumers this same bar rely on).
        # `pending` collects everything Phase 1b/1c need for the symbols
        # whose features are actually ready to run inference on.
        pending: list[dict] = []
        for symbol in self.symbols:
            bar = slice.bars.get(symbol)
            if bar is None:
                continue

            self.symbol_long_windows[symbol].append(float(bar.close))
            self.symbol_treasury_10yr_history[symbol].append(self.latest_bond_payload.get("treasury_10yr_level"))
            self.symbol_windows[symbol].append(
                {
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
            )

            topology_payload = topology_by_symbol.get(str(symbol))
            feature_payload = self._build_model_input(symbol, topology_payload)
            signal_payload = {
                "ticker": self.asset_lookup[str(symbol)]["ticker"],
                "security_type": self.asset_lookup[str(symbol)]["security_type"],
                "close": float(bar.close),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "volume": float(bar.volume),
                "signal": "hold",
                "confidence": 0.0,
                "probability_up": None,
                "target_weight": 0.0,
                "feature_ready": feature_payload["ready"],
                "asset_quality": self._asset_quality_for_symbol(symbol),
                "trading_eligible": self._is_trading_eligible(symbol),
                "can_trade": not self.trade_lock_active and self._is_trading_eligible(symbol),
            }
            signals[str(symbol)] = signal_payload

            if feature_payload["ready"] and not self.is_warming_up:
                # Computed inside _build_model_input(), before this model
                # even ran, since regime is now a genuine model input, not
                # just a downstream consumer of its output - reused here
                # rather than recomputed, so the value gating/analyzer/
                # dashboard see always matches what the model actually saw.
                regime_payload = feature_payload["regime_payload"]
                # Phase 2 (see _run_sequence_model()'s docstring; the
                # resulting prediction can optionally blend into gating
                # below via gating_sequence_weight, off by default):
                # append this bar's flat model_inputs to the rolling
                # per-symbol buffer BEFORE reading it, so the sequence
                # model's most-recent timestep is always the current bar,
                # matching train.py::build_sequence_tensor_dataset()'s
                # row-includes-itself windowing.
                sequence_history: list[list[float]] | None = None
                if self.sequence_model_enabled:
                    self.symbol_feature_history.setdefault(
                        symbol, deque(maxlen=self.sequence_window_size)
                    ).append(feature_payload["model_inputs"])
                    sequence_history = list(self.symbol_feature_history[symbol])
                pending.append(
                    {
                        "symbol": symbol,
                        "bar": bar,
                        "feature_payload": feature_payload,
                        "topology_payload": topology_payload,
                        "regime_payload": regime_payload,
                        "sequence_history": sequence_history,
                    }
                )
            else:
                signal_payload["reason"] = feature_payload["reason"]

        # Phase 1b: the actual profiled inference cluster (baseline +
        # sequence + experts + multitask + expert-multitask) - the only
        # part that's ever parallelized, and only when
        # phase_v2.inference_parallelism.enabled is true (self._inference_pool
        # is not None). Sequential-by-default behavior/order/results are
        # BYTE-IDENTICAL to before this restructuring existed - every
        # symbol still calls _run_inference_cluster_sequential() in
        # self.symbols order, one at a time, exactly as the old inline
        # code did. Only diverges when parallelism is explicitly enabled;
        # even then, any pooled failure (including a timeout - Windows'
        # spawn-based ProcessPoolExecutor has never been verified inside
        # Lean's own embedded-Python runtime, see
        # inference/parallel_inference.py's module docstring) permanently
        # disables the pool for the rest of THIS bar's remaining symbols
        # and falls back to the sequential path, never a crash.
        inference_results: dict[str, dict] = {}
        if self._inference_pool is not None:
            futures = {
                str(item["symbol"]): self._inference_pool.submit(
                    run_symbol_inference,
                    item["feature_payload"]["model_inputs"],
                    item["sequence_history"],
                    self.sequence_window_size,
                )
                for item in pending
            }
            pool_broken = False
            for item in pending:
                symbol_key = str(item["symbol"])
                if pool_broken:
                    inference_results[symbol_key] = self._run_inference_cluster_sequential(
                        item["feature_payload"]["model_inputs"], item["symbol"]
                    )
                    continue
                try:
                    inference_results[symbol_key] = futures[symbol_key].result(timeout=30)
                except Exception as error:
                    self.Debug(
                        f"Inference parallelism failed ({error}) - disabling the pool for the rest of this run "
                        "and falling back to the sequential inference path."
                    )
                    pool_broken = True
                    self._inference_pool = None
                    inference_results[symbol_key] = self._run_inference_cluster_sequential(
                        item["feature_payload"]["model_inputs"], item["symbol"]
                    )
        else:
            for item in pending:
                inference_results[str(item["symbol"])] = self._run_inference_cluster_sequential(
                    item["feature_payload"]["model_inputs"], item["symbol"]
                )

        # Phase 1c: gating + signal derivation - cheap, stays sequential.
        for item in pending:
            symbol = item["symbol"]
            symbol_key = str(symbol)
            bar = item["bar"]
            feature_payload = item["feature_payload"]
            topology_payload = item["topology_payload"]
            regime_payload = item["regime_payload"]

            result = inference_results[symbol_key]
            baseline_probability_up = result["baseline_probability"]
            sequence_prediction = result["sequence_result"]
            expert_probabilities = result["expert_probabilities"]
            multitask_payload = result["multitask_result"]
            baseline_magnitude = multitask_payload.get("magnitude") if multitask_payload else None
            baseline_volatility = multitask_payload.get("volatility") if multitask_payload else None
            expert_magnitudes = result["expert_multitask_magnitudes"]
            expert_volatilities = result["expert_multitask_volatilities"]

            gating_payload = build_gating_decision(
                regime=regime_payload,
                expert_training_metrics=self.expert_training_metrics,
                expert_probabilities=expert_probabilities,
                baseline_probability_up=baseline_probability_up,
                baseline_weight=self.gating_baseline_weight,
                gating_model=self.gating_model,
                gating_feature_schema=self.gating_feature_schema,
                expert_magnitudes=expert_magnitudes,
                expert_volatilities=expert_volatilities,
                baseline_magnitude=baseline_magnitude,
                baseline_volatility=baseline_volatility,
                sequence_prediction=sequence_prediction,
                sequence_weight=self.gating_sequence_weight,
            ).to_dict()
            probability_up = float(gating_payload["final_probability_up"])
            # Same gating-blended treatment probability_up already gets
            # (baseline anchor + per-expert weighted average, not just
            # the raw single-model prediction) - see
            # moe/gating.py::_weighted_blend()/moe/README.md.
            predicted_return_magnitude = gating_payload.get("final_magnitude")
            predicted_volatility = gating_payload.get("final_volatility")
            # Prefer the sequence model's rank_20d head (strongest
            # backtest rank-IC, 0.073/t=4.40) and fall back to the
            # multitask model's own rank_20d head when the sequence
            # model is unavailable/disabled - see risk/position_sizing.py::
            # rank_sizing_multiplier(). Off by default (rank_sizing_enabled).
            predicted_rank_20d = None
            if sequence_prediction:
                predicted_rank_20d = sequence_prediction.get("rank_20d")
            if predicted_rank_20d is None and multitask_payload:
                predicted_rank_20d = multitask_payload.get("rank_20d")
            signal_name, confidence, base_target_weight = self._derive_signal(probability_up)

            pass1_state[symbol_key] = {
                "symbol": symbol,
                "bar": bar,
                "feature_payload": feature_payload,
                "topology_payload": topology_payload,
                "regime_payload": regime_payload,
                "sequence_prediction": sequence_prediction,
                "expert_probabilities": expert_probabilities,
                "baseline_probability_up": baseline_probability_up,
                "gating_payload": gating_payload,
                "probability_up": probability_up,
                "predicted_return_magnitude": predicted_return_magnitude,
                "predicted_volatility": predicted_volatility,
                "predicted_rank_20d": predicted_rank_20d,
                "signal_name": signal_name,
                "confidence": confidence,
                "base_target_weight": base_target_weight,
            }
            book_candidates[symbol_key] = {
                "predicted_rank_20d": predicted_rank_20d,
                "trading_eligible": self._is_trading_eligible(symbol),
            }

        # `enabled=False` (default) always resolves to {} here - every
        # symbol in Pass 2 below then finds no book_allocation, taking the
        # exact same code path as before this restructuring existed.
        book_allocations = (
            build_rank_based_book(
                book_candidates,
                top_n=self.portfolio_book_top_n,
                bottom_n=self.portfolio_book_bottom_n,
                min_rank_confidence_spread=self.portfolio_book_min_rank_confidence_spread,
            )
            if self.portfolio_book_enabled
            else {}
        )

        # ---- Pass 2: sizing/liquidity/analyzer/order-application, now
        # that every symbol's book role (if any) is known. Iterates
        # pass1_state (populated in self.symbols order during Pass 1), so
        # cross-symbol sequencing (e.g. exposure-cap consumption order in
        # _apply_signal()) is unchanged from the previous single-pass loop. ----
        for symbol_key, state in pass1_state.items():
            symbol = state["symbol"]
            bar = state["bar"]
            feature_payload = state["feature_payload"]
            topology_payload = state["topology_payload"]
            regime_payload = state["regime_payload"]
            sequence_prediction = state["sequence_prediction"]
            expert_probabilities = state["expert_probabilities"]
            baseline_probability_up = state["baseline_probability_up"]
            gating_payload = state["gating_payload"]
            probability_up = state["probability_up"]
            predicted_return_magnitude = state["predicted_return_magnitude"]
            predicted_volatility = state["predicted_volatility"]
            predicted_rank_20d = state["predicted_rank_20d"]
            signal_name = state["signal_name"]
            confidence = state["confidence"]
            base_target_weight = state["base_target_weight"]

            # The one deliberate departure from every other rank_20d
            # integration's "never flips direction" rule - see
            # portfolio/book_construction.py's module docstring. A
            # book-selected role OVERRIDES the model's own buy/sell/hold
            # call and its target-weight sign, but still flows through the
            # exact same sizing/liquidity/analyzer pipeline below as any
            # other signal - never bypasses it.
            book_allocation = book_allocations.get(symbol_key)
            if book_allocation is not None:
                signal_name = "buy" if book_allocation.role == "long" else "short"
                confidence = min(1.0, abs(book_allocation.predicted_rank_20d - 0.5) * 2.0)
                base_target_weight = (
                    min(self.max_position_weight, 0.10 + 0.15 * confidence) * book_allocation.book_role_multiplier
                )

            asset = self.asset_lookup[symbol_key]
            sizing_payload = self._build_dynamic_sizing_payload(
                signal_name,
                confidence,
                base_target_weight,
                feature_payload["base_features"],
                asset,
                float(bar.close),
                topology_payload,
                predicted_volatility=predicted_volatility,
                predicted_rank_20d=predicted_rank_20d,
            )
            target_weight = float(sizing_payload["target_weight"])
            # Reuses the exact same spread estimate _build_model_input()
            # already computed and fed to the model as
            # liquidity_spread_proxy, rather than recomputing it here -
            # one estimate per bar, consistently used everywhere.
            liquidity_payload = build_liquidity_decision(
                close=float(bar.close),
                volume=float(bar.volume),
                target_weight=target_weight,
                portfolio_value=float(self.Portfolio.TotalPortfolioValue),
                annualized_volatility=float(sizing_payload.get("annualized_volatility", 0.0)),
                security_type=str(asset.get("security_type", "equity")),
                dynamic_spread=feature_payload.get("liquidity_spread_proxy"),
                **self._liquidity_thresholds,
            ).to_dict()
            if liquidity_payload["recommended_action"] == "reduce_size":
                target_weight = float(liquidity_payload["adjusted_target_weight"])
            # Refresh this bar's fill-slippage estimate for symbol_key -
            # read by _LiquidityAwareSlippageModel (real Lean fills) and
            # passed into SimulatedPortfolioState.enter_long() below
            # (observation-mode fills), so both paths charge the same,
            # already-computed cost instead of Lean's/simulate_fill()'s
            # previous implicit zero-slippage default. Which liquidity_payload
            # field is used is config-driven (self._liquidity_slippage_source,
            # phase_v2.liquidity.fill_slippage.source).
            self.latest_liquidity_slippage_bps[symbol_key] = (
                liquidity_cost_fraction(liquidity_payload, self._liquidity_slippage_source) * 10_000.0
            )

            decision = build_market_analysis_decision(
                signal_name=signal_name,
                confidence=confidence,
                probability_up=probability_up,
                target_weight=target_weight,
                regime=regime_payload,
                gating=gating_payload,
                trading_eligible=self._is_trading_eligible(symbol),
                trade_lock_active=self.trade_lock_active,
                trade_lock_reason=self.trade_lock_reason,
                topology=topology_payload,
                liquidity=liquidity_payload,
                min_confidence_to_trade=self.min_confidence_to_trade,
                retrain_min_regime_confidence=self.analyzer_retrain_min_regime_confidence,
                low_regime_confidence_threshold=self.analyzer_low_regime_confidence_threshold,
                use_composite_signal_score=self.analyzer_use_composite_signal_score,
                predicted_return_magnitude=predicted_return_magnitude,
                predicted_volatility=predicted_volatility,
            ).to_dict()

            signal_name = decision["signal"]
            target_weight = decision["target_weight"]
            close_price = float(bar.close)

            if decision["action"] == "trade":
                execution_note = self._apply_signal(symbol, signal_name, target_weight, close_price, sizing_payload)
            else:
                execution_note = decision["action"]

            close_prices_by_symbol[symbol_key] = close_price

            self.latest_regime_by_symbol[symbol_key] = regime_payload.get("trend_regime", "unknown")
            self.latest_regime_risk_score_by_symbol[symbol_key] = float(regime_payload.get("risk_score", 0.0) or 0.0)
            self.latest_liquidity_by_symbol[symbol_key] = liquidity_payload

            # sizing_payload can carry a raw OptionsPositionDecision dataclass
            # (with a live, non-JSON-serializable Lean Symbol on its
            # contract_symbol field) inside asset_class_routing_extra -
            # json.dumps() in _write_state() has no idea how to serialize
            # that. Build a JSON-safe copy for the dashboard state ONLY;
            # _apply_signal() above already received (and used) the
            # original, unsanitized sizing_payload with the real Symbol.
            # Without this, the first bar that actually sizes an options
            # position would silently break the ENTIRE state write (caught
            # by _write_state()'s blanket except), not just this section.
            dynamic_sizing_for_state = sizing_payload
            extra = (sizing_payload or {}).get("asset_class_routing_extra") or {}
            options_decision_obj = extra.get("options_decision")
            if options_decision_obj is not None:
                dynamic_sizing_for_state = {
                    **sizing_payload,
                    "asset_class_routing_extra": {**extra, "options_decision": options_decision_obj.to_dict()},
                }

            signals[symbol_key].update(
                {
                    "signal": signal_name,
                    "confidence": confidence,
                    "probability_up": probability_up,
                    "baseline_probability_up": baseline_probability_up,
                    "expert_probabilities": expert_probabilities,
                    "predicted_return_magnitude": predicted_return_magnitude,
                    "predicted_volatility": predicted_volatility,
                    "predicted_rank_20d": predicted_rank_20d,
                    # Phase 2 sequence-encoder signal - informational
                    "sequence_model": sequence_prediction,
                    "moe_gating": gating_payload,
                    "base_target_weight": base_target_weight,
                    "target_weight": target_weight,
                    "dynamic_sizing": dynamic_sizing_for_state,
                    "regime": regime_payload,
                    "features": feature_payload["base_features"],
                    "execution_note": execution_note,
                    "market_analysis": decision,
                    "topology": topology_payload or {},
                    "liquidity": liquidity_payload,
                    "portfolio_book_role": book_allocation.role if book_allocation is not None else None,
                }
            )
            orders_allowed, _ = self._order_permission()
            portfolio_snapshot = (
                {
                    "total_value": float(self.Portfolio.TotalPortfolioValue),
                    "cash": float(self.Portfolio.Cash),
                    "current_drawdown": self.current_total_drawdown,
                }
                if orders_allowed
                else self._simulated_portfolio.snapshot()
            )
            portfolio_snapshot["trade_lock_active"] = self.trade_lock_active
            portfolio_snapshot["trade_lock_reason"] = self.trade_lock_reason
            experience_event = build_experience_event(
                mode=self._experience_mode,
                symbol=symbol_key,
                ticker=self.asset_lookup[symbol_key]["ticker"],
                signal=signal_name,
                action=decision["action"],
                execution_note=execution_note,
                probability_up=probability_up,
                confidence=confidence,
                target_weight=target_weight,
                regime=regime_payload,
                moe_gating=gating_payload,
                topology=topology_payload or {},
                liquidity=liquidity_payload,
                market_analysis=decision,
                portfolio=portfolio_snapshot,
                sequence_model=sequence_prediction,
                resolved_predicted_rank_20d=predicted_rank_20d,
                close_price=float(bar.close),
            )
            self._experience_queue.push(experience_event)
            self._observation_event_log.append(experience_event)
            self._session_events.append(experience_event)

        if close_prices_by_symbol:
            self._simulated_portfolio.mark_to_market(close_prices_by_symbol, bar_index=self.bar_index)

        if signals:
            insight = "Phase 4 model inference active" if not self.is_warming_up else "Warming up feature history"
            self._write_state(mode="runtime", insight=insight, signals=signals)

    def on_end_of_algorithm(self) -> None:
        self._ensure_ready()
        self._write_state(mode="shutdown", insight="Algorithm finished")

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_expert_model_exports(self) -> dict:
        exports = {}
        if not self.expert_model_dir.exists():
            return exports

        for expert_name in EXPERT_NAMES:
            weights_path = self.expert_model_dir / expert_name / "model_weights.json"
            if weights_path.exists():
                try:
                    exports[expert_name] = self._load_json(weights_path)
                    convert_state_dict_arrays(exports[expert_name])
                except Exception as error:
                    self.Debug(f"Expert export load failed for {expert_name}: {error}")
        return exports

    def _load_expert_multitask_exports(self) -> dict:
        """Optional per-expert multitask (direction+magnitude+volatility)
        exports (train.py::_train_expert_multitask(), best-effort - not
        every expert necessarily has enough rows to train one). Same
        graceful-degrade contract as _load_expert_model_exports(): a
        missing or malformed multitask_model.json for one expert just
        means that expert contributes no magnitude/volatility to
        moe/gating.py's blend, never a hard failure."""
        exports = {}
        if not self.expert_model_dir.exists() or not self.multitask_model_enabled:
            return exports

        for expert_name in EXPERT_NAMES:
            weights_path = self.expert_model_dir / expert_name / "multitask_model.json"
            if weights_path.exists():
                try:
                    exports[expert_name] = self._load_json(weights_path)
                    convert_state_dict_arrays(exports[expert_name])
                except Exception as error:
                    self.Debug(f"Expert multitask export load failed for {expert_name}: {error}")
        return exports

    def _load_learned_topology_model(self) -> tuple[dict | None, dict | None]:
        """Optional artifact pair (V2-17.5) - graceful/best-effort like
        _load_expert_model_exports(), never like _validate_runtime_artifacts()'s
        hard fail. Missing/malformed files just mean topology.learned_topology
        falls back to the deterministic layer; they must never block startup."""
        if not self.topology_learning_enabled:
            return None, None
        if not self.topology_model_path.exists() or not self.topology_feature_schema_path.exists():
            return None, None
        try:
            model = self._load_json(self.topology_model_path)
            feature_schema = self._load_json(self.topology_feature_schema_path)
            return model, feature_schema
        except Exception as error:
            self.Debug(f"Learned topology model load failed: {error}")
            return None, None

    def _load_gating_model(self) -> tuple[dict | None, dict | None]:
        """Optional artifact pair, identical fallback contract to
        _load_learned_topology_model(): missing/malformed files mean
        build_gating_decision() falls back to its hardcoded quality/
        performance/regime-alignment blend - never a hard failure."""
        if not self.gating_learned_model_enabled:
            return None, None
        if not self.gating_model_path.exists() or not self.gating_feature_schema_path.exists():
            return None, None
        try:
            model = self._load_json(self.gating_model_path)
            feature_schema = self._load_json(self.gating_feature_schema_path)
            return model, feature_schema
        except Exception as error:
            self.Debug(f"Gating model load failed: {error}")
            return None, None

    def _load_multitask_model(self) -> tuple[dict | None, dict | None]:
        """Optional artifact pair (train_multitask.py), identical fallback
        contract to _load_gating_model()/_load_learned_topology_model():
        missing/malformed files just mean predicted_return_magnitude/
        predicted_volatility stay None everywhere downstream (position
        sizing keeps using rolling_volatility_20d, exactly today's
        behavior) - never a hard failure."""
        if not self.multitask_model_enabled:
            return None, None
        if not self.multitask_model_path.exists() or not self.multitask_feature_schema_path.exists():
            return None, None
        try:
            model = self._load_json(self.multitask_model_path)
            convert_state_dict_arrays(model)
            feature_schema = self._load_json(self.multitask_feature_schema_path)
            return model, feature_schema
        except Exception as error:
            self.Debug(f"Multitask model load failed: {error}")
            return None, None

    def _load_sequence_model(self) -> tuple[dict | None, dict | None]:
        """Optional artifact pair (train_sequence.py, Phase 2), identical
        fallback contract to _load_multitask_model(): missing/malformed
        files just mean the sequence-model signal stays absent from
        signal_payload and gating (see on_data()'s sequence_prediction
        threading, gating_sequence_weight), never a hard failure."""
        if not self.sequence_model_enabled:
            return None, None
        if not self.sequence_model_path.exists() or not self.sequence_feature_schema_path.exists():
            return None, None
        try:
            model = self._load_json(self.sequence_model_path)
            convert_state_dict_arrays(model)
            feature_schema = self._load_json(self.sequence_feature_schema_path)
            return model, feature_schema
        except Exception as error:
            self.Debug(f"Sequence model load failed: {error}")
            return None, None

    def _validate_runtime_artifacts(self) -> None:
        required_paths = [
            self.root_path / "config.json",
            self.model_path,
            self.feature_schema_path,
            self.scaler_stats_path,
        ]
        missing = [str(path.relative_to(self.root_path)) for path in required_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(
                "Lean runtime artifacts are missing. Run `python train.py` before `lean backtest .`. "
                f"Missing: {', '.join(missing)}"
            )

    def _resolve_resolution(self, resolution_name: str):
        resolution_map = {
            "Daily": Resolution.DAILY,
            "Hour": Resolution.HOUR,
            "Minute": Resolution.MINUTE,
        }
        return resolution_map.get(resolution_name, Resolution.DAILY)

    def _add_asset(self, asset: dict):
        ticker = asset["ticker"]
        security_type = asset["security_type"]
        try:
            if security_type == "equity":
                security = self.add_equity(ticker, self.resolution)
            elif security_type == "crypto":
                market = Market.COINBASE if asset["market"].lower() == "coinbase" else asset["market"].upper()
                security = self.add_crypto(ticker, self.resolution, market)
            elif security_type == "future":
                # Lean's native continuous-contract subscription -
                # rollover/mark-to-market are entirely Lean's job
                # (risk/futures_risk.py::rollover_due() is a diagnostic
                # signal only, never a trade trigger - see that module's
                # docstring). asset["ticker"] is the Lean root symbol
                # (e.g. "ES") unless lean_future_ticker overrides it.
                security = self.add_future(asset.get("lean_future_ticker", ticker), self.resolution)
                security.SetFilter(0, 90)
            elif security_type == "option":
                # Near-the-money, <=60 day chain - real greeks/IV
                # (features/options_greeks.py) only populate once IB
                # supplies real chain bid/ask data; order PLACEMENT against
                # a specific resolved contract is a documented non-goal of
                # this pass (see _apply_signal()'s "option" branch).
                security = self.add_option(asset.get("underlying_ticker", ticker), self.resolution)
                security.SetFilter(-5, 5, timedelta(0), timedelta(60))
            else:
                self.debug(f"Unsupported asset type skipped: {security_type} {ticker}")
                return None

            # Real per-asset fill slippage (liquidity/market_liquidity.py's
            # estimated_round_trip_cost, refreshed every bar) instead of
            # Lean's default zero-slippage fill - one shared model instance
            # across every security, keyed internally by symbol.
            security.SetSlippageModel(self._liquidity_slippage_model)
            return security.symbol
        except Exception as error:
            self.debug(f"{ticker} subscription skipped: {error}")
            return None

    def _build_model_input(self, symbol, topology_payload: dict | None = None) -> dict:
        """Builds the full model input vector - the original 10 price/
        volume-derived features, plus regime/liquidity/topology as genuine
        input features (Phase 1 remainder, not just downstream consumers of
        the model's own output - see train.py::build_feature_dataset()'s
        matching offline reconstruction and development/Changelog.md).

        topology_payload must be this bar's already-computed node (from
        self.latest_topology_payload, built once per bar before the symbol
        loop in on_data()) - topology needs no reordering, it was already
        available before model inference. Regime is computed here, inside
        this method, specifically so it exists *before* the model runs -
        previously it was only computed after, purely for gating/analyzer/
        dashboard consumption.
        """
        bars = list(self.symbol_windows[symbol])
        if len(bars) < 2:
            return {"ready": False, "reason": f"Need 2 bars, have {len(bars)}"}

        closes = [bar["close"] for bar in bars]
        volumes = [bar["volume"] for bar in bars]
        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]
        current = bars[-1]

        daily_returns = []
        for index in range(1, len(closes)):
            previous = closes[index - 1]
            if previous == 0:
                return {"ready": False, "reason": "Previous close equals zero"}
            daily_returns.append(closes[index] / previous - 1.0)

        previous_close = closes[-2]
        close_5 = closes[max(0, len(closes) - 6)]
        close_20 = closes[max(0, len(closes) - 21)]
        previous_volume = volumes[-2]

        if previous_close == 0 or close_5 == 0 or close_20 == 0 or current["open"] == 0 or current["close"] == 0:
            return {"ready": False, "reason": "Encountered zero price in feature calculation"}

        base_features = {
            "close_to_close_return_1d": closes[-1] / previous_close - 1.0,
            "close_to_close_return_5d": closes[-1] / close_5 - 1.0,
            "close_to_close_return_20d": closes[-1] / close_20 - 1.0,
            "rolling_volatility_5d": self._standard_deviation(daily_returns[-5:]),
            "rolling_volatility_20d": self._standard_deviation(daily_returns[-20:]),
            "momentum_5d": closes[-1] / close_5 - 1.0,
            "momentum_20d": closes[-1] / close_20 - 1.0,
            "high_low_range_pct": (current["high"] - current["low"]) / current["close"],
            "open_close_range_pct": (current["close"] - current["open"]) / current["open"],
            "volume_change_1d": self._clamp_volume_change(
                0.0 if previous_volume == 0 else current["volume"] / previous_volume - 1.0
            ),
        }

        # Phase 6 technical indicators - shared pure implementations
        # (features/technical_indicators.py), same functions
        # train.py::engineer_features() calls, so both sides compute every
        # one identically by construction. rsi_14/atr_pct_14/
        # bollinger_pctb_20/volume_zscore_20 only look at their own trailing
        # period (<=20 bars), well within this 25-bar `closes`/`highs`/
        # `lows`/`volumes` window. macd_histogram_norm/dist_52w_high need
        # the separate, longer self.symbol_long_windows buffer (deque(maxlen=260),
        # matching train.py::LONG_LOOKBACK_WINDOW_BARS) instead.
        base_features["rsi_14"] = relative_strength_index(closes, period=14)
        base_features["atr_pct_14"] = average_true_range_pct(highs, lows, closes, period=14)
        base_features["bollinger_pctb_20"] = bollinger_pctb(closes, period=20)
        base_features["volume_zscore_20"] = volume_zscore(volumes, period=20)
        long_closes = list(self.symbol_long_windows.get(symbol, []))
        base_features["macd_histogram_norm"] = macd_histogram_normalized(long_closes)
        base_features["dist_52w_high"] = distance_from_52w_high(long_closes, window=self.long_bar_history_size)

        topology_payload = topology_payload or {}
        regime_payload = self._build_regime_payload(
            base_features,
            average_correlation=float(topology_payload.get("correlation_strength", 0.0) or 0.0),
        )

        # Same asset-intrinsic spread estimate build_liquidity_decision()
        # will use later for the real sizing/liquidity decision (reused
        # verbatim via feature_payload["liquidity_spread_proxy"] below, not
        # recomputed) - no order-size assumption needed, unlike
        # participation_rate/estimated_slippage, which is why only this
        # piece of liquidity/market_liquidity.py's output becomes a model
        # input (see train.py::add_liquidity_features()'s docstring).
        dynamic_spread = None
        if self._spread_estimation_enabled and len(bars) >= self._spread_estimation_min_bars:
            dynamic_spread = estimate_high_low_spread(highs, lows)
        if dynamic_spread is None:
            asset_for_spread = self.asset_lookup[str(symbol)]
            dynamic_spread = TYPICAL_SPREAD_BY_TYPE.get(str(asset_for_spread.get("security_type", "equity")), 0.001)

        base_features["regime_signal_confidence"] = float(regime_payload.get("confidence", 0.0) or 0.0)
        base_features["regime_signal_trend_score"] = float(regime_payload.get("trend_score", 0.0) or 0.0)
        base_features["regime_signal_risk_score"] = float(regime_payload.get("risk_score", 0.0) or 0.0)
        base_features["liquidity_log_dollar_volume"] = math.log1p(max(current["close"] * current["volume"], 0.0))
        base_features["liquidity_spread_proxy"] = float(dynamic_spread)
        base_features["topology_correlation_strength"] = float(topology_payload.get("correlation_strength", 0.0) or 0.0)

        # Peer-return features (Phase 5) - top_peer_returns is already each
        # top-N correlated peer's own latest 1d return, computed by
        # build_market_topology() itself (topology/market_topology.py) from
        # the exact same per-bar returns_by_symbol used for correlation, no
        # separate lookup needed here. Missing peer (thin universe) -> 0.0,
        # identically padded to train.py::build_topology_features_by_date()'s
        # offline convention (peer_return_feature_names()).
        peer_returns = list(topology_payload.get("top_peer_returns") or [])
        padded_peer_returns = peer_returns + [0.0] * (self.topology_top_peers_n - len(peer_returns))
        for rank, peer_return in enumerate(padded_peer_returns, start=1):
            base_features[f"peer_rank{rank}_return_1d"] = float(peer_return)
        base_features["peer_mean_return_1d"] = float(sum(peer_returns) / len(peer_returns)) if peer_returns else 0.0

        # cs_momentum_rank_20 (Phase 6) - self.latest_momentum_by_symbol is
        # computed once per bar in _build_topology_payload() (before the
        # per-symbol loop, same as returns_by_symbol/topology itself), so
        # it reflects every symbol's momentum_20d through the PREVIOUS bar
        # - the same one-bar-lag limitation this codebase's regime/topology
        # inputs already have (see _build_topology_payload()'s docstring),
        # not a new one. Ties/thin-universe handling matches
        # build_cross_sectional_momentum_rank_features()'s offline default.
        base_features["cs_momentum_rank_20"] = cross_sectional_momentum_rank(
            self.latest_momentum_by_symbol, str(symbol)
        )

        # Macro features (Phase 1b) - computed once per bar in
        # _build_macro_payload() (before the per-symbol loop, same as
        # topology/cs_momentum_rank_20 above), identical for every symbol
        # this bar by design (a fixed, global cross-asset-class state, not
        # a per-symbol value).
        base_features["macro_yield_curve_slope_proxy"] = float(
            self.latest_macro_payload.get("yield_curve_slope_proxy", 0.0) or 0.0
        )
        base_features["macro_credit_spread_proxy"] = float(
            self.latest_macro_payload.get("credit_spread_proxy", 0.0) or 0.0
        )
        base_features["macro_crypto_risk_appetite_proxy"] = float(
            self.latest_macro_payload.get("crypto_risk_appetite_proxy", 0.0) or 0.0
        )

        # Real yield-curve/credit-spread features (features/bond_features.py)
        # - the first 4 are date-only and identical for every symbol this
        # bar (self.latest_bond_payload, built once in on_data() same as
        # the macro block above); bond_empirical_duration_beta is the one
        # per-symbol exception - only bond-tagged symbols get a non-zero
        # value, see _bond_empirical_duration_beta_for_symbol()'s docstring.
        base_features["bond_yield_curve_level"] = float(
            self.latest_bond_payload.get("yield_curve_level", 0.0) or 0.0
        )
        base_features["bond_yield_curve_slope"] = float(
            self.latest_bond_payload.get("yield_curve_slope", 0.0) or 0.0
        )
        base_features["bond_yield_curve_curvature"] = float(
            self.latest_bond_payload.get("yield_curve_curvature", 0.0) or 0.0
        )
        base_features["bond_credit_spread_level"] = float(
            self.latest_bond_payload.get("credit_spread_level", 0.0) or 0.0
        )
        base_features["bond_empirical_duration_beta"] = float(
            self._bond_empirical_duration_beta_for_symbol(symbol)
        )

        # Futures term-structure / options-sentiment cross-asset macro
        # features (features/derivatives_macro_features.py) - broadcast to
        # every symbol, same shape as the bond block above. Computed once
        # per bar in _build_derivatives_macro_payload() (on_data(), right
        # after the chain payloads it depends on) - real values once a
        # future/option asset matching self.derivatives_reference_tickers
        # is configured and subscribed; neutral-default (0.0) otherwise,
        # same convention as every other missing-reference-ticker case.
        base_features["futures_term_structure_slope"] = float(
            self.latest_derivatives_macro_payload.get("futures_term_structure_slope", 0.0) or 0.0
        )
        base_features["options_put_call_ratio"] = float(
            self.latest_derivatives_macro_payload.get("options_put_call_ratio", 0.0) or 0.0
        )
        base_features["options_implied_vol_skew"] = float(
            self.latest_derivatives_macro_payload.get("options_implied_vol_skew", 0.0) or 0.0
        )

        # Safe default (10.0) for scaler_stats.json files written before
        # clip_sigma existed - see train.py::write_scaler_artifacts().
        clip_sigma = float(self.scaler_stats.get("clip_sigma", 10.0))
        scaled_features = {}
        for index, base_name in enumerate(self.base_feature_names):
            scaled_name = self.scaled_feature_names[index]
            mean_value = float(self.scaler_stats["mean"][index])
            scale_value = float(self.scaler_stats["scale"][index]) if float(self.scaler_stats["scale"][index]) != 0 else 1.0
            scaled_value = (base_features[base_name] - mean_value) / scale_value
            # Mirrors train.py::fit_and_apply_scaler()'s scaled-space clip -
            # the layer that actually protects the sequence model's sliding
            # window from a single poisoned bar replicating into every
            # subsequent window (see development/Problems.md).
            scaled_features[scaled_name] = max(-clip_sigma, min(clip_sigma, scaled_value))

        # Regime/topology one-hots - unscaled, same treatment as the asset
        # context flags below (already-bounded [0,1], no StandardScaler
        # needed). Matches train.py::_categorical_feature_names() exactly.
        categorical_values = {feature_name: 0.0 for feature_name in self.categorical_feature_names}
        for label, key in (
            ("bullish", "regime_trend_bullish"),
            ("bearish", "regime_trend_bearish"),
            ("sideways", "regime_trend_sideways"),
        ):
            if key in categorical_values and regime_payload.get("trend_regime") == label:
                categorical_values[key] = 1.0
        for label, key in (
            ("low_volatility", "regime_volatility_low"),
            ("normal_volatility", "regime_volatility_normal"),
            ("high_volatility", "regime_volatility_high"),
        ):
            if key in categorical_values and regime_payload.get("volatility_regime") == label:
                categorical_values[key] = 1.0
        for label, key in (
            ("risk_on", "regime_risk_on"),
            ("risk_off", "regime_risk_off"),
            ("risk_neutral", "regime_risk_neutral"),
        ):
            if key in categorical_values and regime_payload.get("risk_regime") == label:
                categorical_values[key] = 1.0
        for label, key in (
            ("normal", "topology_risk_normal"),
            ("elevated", "topology_risk_elevated"),
            ("isolated", "topology_risk_isolated"),
        ):
            if key in categorical_values and topology_payload.get("topology_risk") == label:
                categorical_values[key] = 1.0

        context_values = {feature_name: 0.0 for feature_name in self.context_feature_names}
        asset = self.asset_lookup[str(symbol)]
        ticker_key = f"asset_{asset['ticker']}"
        if ticker_key in context_values:
            context_values[ticker_key] = 1.0
        # train.py::add_asset_class_context_features() - 5-column one-hot,
        # same "asset_"-prefixed naming so it lands in context_values above
        # automatically once a retrained model's feature_schema lists it;
        # a no-op against any older exported model (the key simply won't
        # be in context_values yet, matching the ticker one-hot's own
        # "if key in context_values" backward-compat guard immediately
        # above).
        asset_class_key = f"asset_class_{asset.get('asset_class') or asset.get('security_type')}"
        if asset_class_key in context_values:
            context_values[asset_class_key] = 1.0

        model_inputs = []
        for feature_name in self.model_input_names:
            if feature_name in scaled_features:
                model_inputs.append(float(scaled_features[feature_name]))
            elif feature_name in categorical_values:
                model_inputs.append(float(categorical_values[feature_name]))
            else:
                model_inputs.append(float(context_values.get(feature_name, 0.0)))

        return {
            "ready": True,
            "reason": "ok",
            "base_features": base_features,
            "scaled_features": scaled_features,
            "categorical_features": categorical_values,
            "context_features": context_values,
            "model_inputs": model_inputs,
            "regime_payload": regime_payload,
            "liquidity_spread_proxy": float(dynamic_spread),
        }

    def _run_model(self, inputs: list[float]) -> float:
        return run_exported_model(self.model_export, inputs)

    def _run_expert_models(self, inputs: list[float]) -> dict:
        """Batched across all 4 experts (one NumPy call per layer instead
        of 4 separate run_exported_model() calls) whenever their exported
        architectures match closely enough - see
        inference/exported_model.py::run_exported_models_batched(). Falls
        back to the original per-expert behavior automatically and safely
        whenever they don't (e.g. only some experts trained, or a shape
        mismatch) - added after profiling (scripts/profile_inference.py)
        showed this loop as a meaningful share of the per-bar hot path's
        cost, see development/Problems.md."""
        model_exports = [self.expert_model_exports.get(expert_name) for expert_name in EXPERT_NAMES]
        results = run_exported_models_batched(model_exports, inputs, stack_cache=self.expert_models_stack_cache)
        probabilities = dict(zip(EXPERT_NAMES, results))
        for expert_name, model_export, result in zip(EXPERT_NAMES, model_exports, results):
            if model_export and result is None:
                self.Debug(f"Expert inference failed for {expert_name}")
        return probabilities

    def _run_multitask_model(self, inputs: list[float]) -> dict | None:
        """Runs the optional joint direction+magnitude+volatility model
        (train_multitask.py) alongside _run_model()/_run_expert_models() -
        never replacing either. Returns None (not a crash) on any failure,
        same graceful-degradation contract as _run_expert_models()."""
        if not self.multitask_model:
            return None
        try:
            return run_exported_multitask_model(self.multitask_model, inputs)
        except Exception as error:
            self.Debug(f"Multitask inference failed: {error}")
            return None

    def _run_expert_multitask_models(self, inputs: list[float]) -> tuple[dict, dict]:
        """Per-expert magnitude/volatility, parallel to _run_expert_models()'s
        per-expert probability_up dict - feeds moe/gating.py's
        final_magnitude/final_volatility weighted blend (see
        moe/README.md). A missing or failed expert just contributes None
        to both dicts, same per-expert graceful-degradation contract as
        _run_expert_models(). Batched across all 4 experts the same way
        _run_expert_models() is - see
        inference/exported_model.py::run_exported_multitask_models_batched()."""
        model_exports = [self.expert_multitask_model_exports.get(expert_name) for expert_name in EXPERT_NAMES]
        results = run_exported_multitask_models_batched(
            model_exports, inputs, stack_cache=self.expert_multitask_models_stack_cache
        )

        magnitudes: dict[str, float | None] = {}
        volatilities: dict[str, float | None] = {}
        for expert_name, model_export, result in zip(EXPERT_NAMES, model_exports, results):
            magnitudes[expert_name] = result.get("magnitude") if result else None
            volatilities[expert_name] = result.get("volatility") if result else None
            if model_export and result is None:
                self.Debug(f"Expert multitask inference failed for {expert_name}")
        return magnitudes, volatilities

    def _run_sequence_model(self, symbol) -> dict | None:
        """Phase 2: runs the optional causal-TCN sequence encoder
        (train_sequence.py/AetherNetSequenceMultiTask) over this symbol's
        rolling buffer of already-computed flat model_inputs vectors
        (self.symbol_feature_history, appended once per bar right after
        _build_model_input() - see on_data()). Left-pads with zero vectors
        when fewer than self.sequence_window_size bars of history exist
        yet, matching train.py::build_sequence_tensor_dataset()'s exact
        offline zero-padding convention.

        Same graceful-degradation contract as _run_multitask_model():
        returns None on any failure or when no model is loaded, never
        raises, never blocks a bar. The result can optionally blend into
        the gating decision (build_gating_decision(sequence_prediction=...,
        sequence_weight=self.gating_sequence_weight)) - off by default,
        see moe/README.md."""
        if not self.sequence_model:
            return None
        history = self.symbol_feature_history.get(symbol)
        if not history:
            return None
        try:
            input_width = len(history[0])
            padding_needed = self.sequence_window_size - len(history)
            sequence = [[0.0] * input_width for _ in range(max(0, padding_needed))] + list(history)
            return run_exported_sequence_multitask_model(self.sequence_model, sequence)
        except Exception as error:
            self.Debug(f"Sequence model inference failed for {symbol}: {error}")
            return None

    def _run_inference_cluster_sequential(self, model_inputs: list[float], symbol) -> dict:
        """Bundles the exact same 5 calls Pass 1 has always made
        (_run_model/_run_sequence_model/_run_expert_models/
        _run_multitask_model/_run_expert_multitask_models) into ONE return
        shape - the always-correct, always-available path on_data() uses
        directly when self._inference_pool is None (the default), and
        falls back to per-symbol whenever a pooled call fails for any
        reason. Same result-dict shape as
        inference/parallel_inference.py::run_symbol_inference(), so Pass
        1's gating/signal-derivation step (Phase 1c) can consume either
        one identically."""
        baseline_probability_up = self._run_model(model_inputs)
        sequence_prediction = self._run_sequence_model(symbol)
        expert_probabilities = self._run_expert_models(model_inputs)
        multitask_payload = self._run_multitask_model(model_inputs)
        expert_magnitudes, expert_volatilities = self._run_expert_multitask_models(model_inputs)
        return {
            "baseline_probability": baseline_probability_up,
            "sequence_result": sequence_prediction,
            "expert_probabilities": expert_probabilities,
            "multitask_result": multitask_payload,
            "expert_multitask_magnitudes": expert_magnitudes,
            "expert_multitask_volatilities": expert_volatilities,
        }

    def _derive_signal(self, probability_up: float) -> tuple[str, float, float]:
        confidence = abs(probability_up - self.decision_threshold) / max(1.0 - self.decision_threshold, self.decision_threshold)
        confidence = max(0.0, min(confidence, 1.0))

        if probability_up >= self.buy_threshold:
            target_weight = min(self.max_position_weight, 0.10 + 0.15 * confidence)
            return "buy", confidence, target_weight

        if probability_up <= self.sell_threshold:
            target_weight = -min(self.max_position_weight, 0.10 + 0.15 * confidence)
            return "sell", confidence, target_weight

        return "hold", confidence, 0.0

    def _build_dynamic_sizing_payload(
        self,
        signal_name: str,
        confidence: float,
        base_target_weight: float,
        base_features: dict,
        asset: dict,
        close_price: float,
        topology: dict | None = None,
        predicted_volatility: float | None = None,
        predicted_rank_20d: float | None = None,
    ) -> dict:
        # {"buy", "sell", "short"} - "short" added alongside the portfolio
        # book (Phase 3 of the 5/10 -> 9/10 roadmap, see
        # portfolio/book_construction.py); the book is off by default so
        # this previously never fired with signal_name == "short" in
        # practice, but zeroing base_target_weight for it here would
        # silently defeat the book's entire short-selling role once
        # enabled - closing that gap while this function is rewritten for
        # asset-class routing rather than leaving it for a future,
        # separate fix.
        if signal_name not in {"buy", "sell", "short"}:
            base_target_weight = 0.0

        topology = topology or {}
        asset_class = asset.get("asset_class") or asset.get("security_type")
        equity_crypto_kwargs = dict(
            rolling_volatility=float(base_features.get("rolling_volatility_20d", 0.0) or 0.0),
            max_position_weight=self.max_position_weight,
            target_daily_volatility=self.target_daily_volatility,
            min_position_weight=self.min_dynamic_position_weight,
            low_volatility_threshold=self.low_volatility_threshold,
            high_volatility_threshold=self.high_volatility_threshold,
            min_volatility_multiplier=self.min_volatility_multiplier,
            max_volatility_multiplier=self.max_volatility_multiplier,
            max_leverage=self.max_leverage,
            topology_source=topology.get("topology_source") if self.topology_sizing_enabled else None,
            topology_confidence=topology.get("topology_confidence"),
            topology_disagreement=topology.get("topology_disagreement"),
            min_topology_multiplier=self.min_topology_multiplier,
            max_topology_multiplier=self.max_topology_multiplier,
            predicted_volatility=predicted_volatility,
            use_predicted_volatility=self.use_predicted_volatility,
            predicted_rank_20d=predicted_rank_20d,
            rank_sizing_enabled=self.rank_sizing_enabled,
            min_rank_multiplier=self.min_rank_multiplier,
            max_rank_multiplier=self.max_rank_multiplier,
        )

        orders_allowed, _ = self._order_permission()
        portfolio_value = (
            float(self.Portfolio.TotalPortfolioValue)
            if orders_allowed
            else float(self._simulated_portfolio.snapshot(consume_realized_pnl=False)["total_value"])
        )

        decision, extra = route_position_sizing(
            asset_class,
            signal_name,
            confidence,
            base_target_weight,
            equity_crypto_kwargs=equity_crypto_kwargs,
            price=close_price,
            portfolio_value=portfolio_value,
            contract_spec=self.futures_contract_specs.get(asset.get("ticker"), {}),
            futures_kwargs=dict(
                target_margin_utilization=self.futures_target_margin_utilization,
                max_margin_utilization=self.futures_max_margin_utilization,
            )
            if self.futures_risk_enabled
            else {"target_margin_utilization": 0.0, "max_margin_utilization": 0.0},
            # Real chain rows once IB is connected and an option asset is
            # configured (self.latest_options_chains_payload, built once
            # per bar in on_data() - see _build_options_chains_payload()).
            # An empty/missing chain (IB disabled, no option asset
            # configured, or a parse failure) correctly, safely resolves to
            # a zero position via build_options_position_sizing(), never a
            # crash.
            available_chain=(
                self.latest_options_chains_payload.get(asset.get("underlying_ticker"), [])
                if asset_class == "option"
                else []
            ),
            options_kwargs=dict(
                target_delta_at_full_confidence=self.options_target_delta_at_full_confidence,
                max_vega_budget_pct_of_equity=self.options_max_vega_budget_pct_of_equity,
            )
            if self.options_risk_enabled
            else {"target_delta_at_full_confidence": 0.0, "max_vega_budget_pct_of_equity": 0.0},
        )
        payload = decision.to_dict()
        payload["asset_class_routing_extra"] = extra
        return payload

    def _build_topology_payload(self) -> dict:
        returns_by_symbol = {}
        # cs_momentum_rank_20 (Phase 6) needs every symbol's own momentum_20d
        # for the SAME bar before any of them can rank against the others -
        # computed here (this function already runs once per bar before the
        # per-symbol loop, exactly like returns_by_symbol above) using the
        # identical formula _build_model_input() itself uses for its own
        # momentum_20d base feature, so a symbol's rank always reflects its
        # own current-bar momentum, not a stale one-bar-lagged value.
        momentum_by_symbol: dict[str, float] = {}
        for symbol in self.symbols:
            closes = [bar["close"] for bar in self.symbol_windows.get(symbol, [])]
            returns = []
            for index in range(1, len(closes)):
                previous = closes[index - 1]
                if previous == 0:
                    continue
                returns.append(closes[index] / previous - 1.0)
            if returns:
                returns_by_symbol[str(symbol)] = returns
            if len(closes) >= 2:
                close_20 = closes[max(0, len(closes) - 21)]
                if close_20:
                    momentum_by_symbol[str(symbol)] = closes[-1] / close_20 - 1.0
        self.latest_momentum_by_symbol = momentum_by_symbol

        deterministic_topology = build_market_topology(
            returns_by_symbol=returns_by_symbol,
            regime_labels_by_symbol=dict(self.latest_regime_by_symbol),
            correlation_threshold=self.topology_correlation_threshold,
            link_threshold=self.topology_link_threshold,
            min_observations=self.topology_min_observations,
            embedding_iterations=self.topology_embedding_iterations,
            previous_positions=self._previous_topology_positions if self.topology_warm_start_enabled else None,
            convergence_tolerance=self.topology_convergence_tolerance,
            top_peers_n=self.topology_top_peers_n,
        ).to_dict()
        self._previous_topology_positions = {
            node["symbol"]: (node["x"], node["y"]) for node in deterministic_topology["nodes"]
        }

        # V2-17.5 - probabilistic overlay on top of the deterministic layer
        # above (never a replacement). Liquidity/regime-risk-score inputs
        # are necessarily one-bar lagged, same limitation
        # latest_regime_by_symbol already has: topology is built once per
        # bar before the per-symbol loop that produces this bar's values.
        deterministic_nodes_by_symbol = {node["symbol"]: node for node in deterministic_topology["nodes"]}
        symbol_features = {}
        for symbol, returns in returns_by_symbol.items():
            node = deterministic_nodes_by_symbol.get(symbol)
            if node is None:
                continue
            momentum_window = returns[-5:]
            symbol_features[symbol] = {
                "volatility": node["volatility_pressure"],
                "momentum": sum(momentum_window) / len(momentum_window) if momentum_window else 0.0,
                "correlation_strength": node["correlation_strength"],
                "liquidity_score": liquidity_score_from_decision(self.latest_liquidity_by_symbol.get(symbol)),
                "regime_risk_score": self.latest_regime_risk_score_by_symbol.get(symbol, 0.0),
            }

        learned_topology = apply_learned_topology(
            deterministic_topology,
            symbol_features,
            dict(self.latest_learned_neighbors_by_symbol),
            self.learned_topology_model,
            self.learned_topology_feature_schema,
            temperature=self.topology_learning_temperature,
            top_n_neighbors=self.topology_learning_top_n_neighbors,
            min_confidence_for_learned=self.topology_learning_min_confidence,
            max_offset_xy=self.topology_learning_max_offset_xy,
            max_offset_z=self.topology_learning_max_offset_z,
        )
        self.latest_learned_neighbors_by_symbol = learned_topology.get("learned_neighbors_by_symbol", {})
        return learned_topology

    def _build_macro_payload(self) -> dict:
        """Phase 1b of the 5/10 -> 9/10 roadmap: deliberate, explicit
        cross-asset-class "macro" features (features/macro_features.py),
        computed once per bar (mirrors _build_topology_payload()'s
        "compute once, every symbol reads it" shape - called right after
        it in on_data(), before the per-symbol loop) from a small fixed
        set of reference tickers (the Phase 1a bond ETF sleeve + the
        existing crypto sleeve), broadcast identically to every symbol's
        model input this bar via _build_model_input().

        Reads self.latest_momentum_by_symbol, already populated by
        _build_topology_payload() earlier this same bar - same one-bar-lag
        characteristic that dict already has (see that method's
        docstring), not a new inconsistency this introduces. No separate
        computation needed here, unlike features/technical_indicators.py's
        long-lookback indicators.

        A reference ticker not configured in this universe (e.g. testing a
        subset without the bond sleeve) has no self.ticker_to_symbol entry
        -> None momentum -> the corresponding proxy neutral-defaults to
        0.0, matching features/macro_features.py's own convention.
        """

        def _momentum_for(ticker: str) -> float | None:
            symbol = self.ticker_to_symbol.get(ticker)
            if symbol is None:
                return None
            return self.latest_momentum_by_symbol.get(str(symbol))

        long_value = _momentum_for(self.macro_reference_tickers["long_duration"])
        short_value = _momentum_for(self.macro_reference_tickers["short_duration"])
        high_yield_value = _momentum_for(self.macro_reference_tickers["high_yield"])
        investment_grade_value = _momentum_for(self.macro_reference_tickers["investment_grade"])
        crypto_value = _momentum_for(self.macro_reference_tickers["crypto"])

        return {
            "yield_curve_slope_proxy": yield_curve_slope_proxy(long_value, short_value),
            "credit_spread_proxy": credit_spread_proxy(high_yield_value, investment_grade_value),
            "crypto_risk_appetite_proxy": crypto_risk_appetite_proxy(crypto_value),
        }

    def _fred_series_asof(self, series_key: str, current_date) -> float | None:
        """Bisect as-of lookup against self.fred_series[series_key] (loaded
        once in _ensure_ready(), never fetched live mid-bar) - the most
        recent FRED observation on or before current_date, matching
        train.py::build_bond_features_by_date()'s identical lookup exactly
        for train/runtime parity. Returns None if the series is empty
        (cache never populated) or current_date precedes every observation."""
        rows = self.fred_series.get(series_key, [])
        if not rows:
            return None
        dates = [row["date"] for row in rows]
        values = [row["value"] for row in rows]
        position = bisect.bisect_right(dates, current_date)
        if position == 0:
            return None
        return values[position - 1]

    def _build_bond_payload(self) -> dict:
        """Real-data sibling of _build_macro_payload() -
        features/bond_features.py, backed by self.fred_series (real
        Treasury yield/credit-spread observations) rather than bond-ETF-
        price-momentum proxies. Computed once per bar (same "compute once,
        every symbol reads it" shape), broadcast identically to every
        symbol's model input this bar via _build_model_input().

        Also returns the raw treasury_10yr_level so on_data() can append it
        to self.symbol_treasury_10yr_history[symbol] - the per-symbol,
        index-aligned-with-symbol_long_windows series
        bond_empirical_duration_beta regresses against."""
        current_date = self.Time.date()
        t3mo = self._fred_series_asof("treasury_3mo", current_date)
        t2yr = self._fred_series_asof("treasury_2yr", current_date)
        t5yr = self._fred_series_asof("treasury_5yr", current_date)
        t10yr = self._fred_series_asof("treasury_10yr", current_date)
        baa10y = self._fred_series_asof("credit_spread_baa10y", current_date)

        return {
            "yield_curve_level": yield_curve_level(t10yr),
            "yield_curve_slope": bond_yield_curve_slope(t10yr, t3mo),
            "yield_curve_curvature": yield_curve_curvature(t2yr, t5yr, t10yr),
            "credit_spread_level": credit_spread_level(baa10y),
            "treasury_10yr_level": t10yr,
        }

    def _bond_empirical_duration_beta_for_symbol(self, symbol) -> float:
        """Only meaningful for asset_class == "bond" symbols - every other
        symbol gets a flat 0.0 (neutral, same convention as
        train.py::build_bond_features_by_date()'s non-bond rows). Regresses
        that symbol's own close-to-close returns against the same-bar
        Delta-10yr-yield, both read from the two deques appended together
        in on_data() (self.symbol_long_windows / self.symbol_treasury_10yr_history) -
        guaranteed index-aligned per symbol regardless of any other
        symbol's data gaps."""
        asset = self.asset_lookup.get(str(symbol), {})
        is_bond = (asset.get("asset_class") or asset.get("security_type")) == "bond"
        if not is_bond:
            return 0.0

        closes = list(self.symbol_long_windows.get(symbol, []))
        treasury_levels = list(self.symbol_treasury_10yr_history.get(symbol, []))
        if len(closes) < 2 or len(treasury_levels) < 2:
            return 0.0

        returns = [None] + [
            (closes[i] / closes[i - 1] - 1.0) if closes[i - 1] else None for i in range(1, len(closes))
        ]
        delta_yield = [None] + [
            (treasury_levels[i] - treasury_levels[i - 1])
            if treasury_levels[i] is not None and treasury_levels[i - 1] is not None
            else None
            for i in range(1, len(treasury_levels))
        ]
        beta = empirical_duration_beta(returns, delta_yield)
        return beta if beta is not None else 0.0

    def _build_options_chains_payload(self, slice: Slice) -> dict[str, list[dict]]:
        """Once-per-bar sibling of _build_topology_payload()/_build_macro_payload()/
        _build_bond_payload() - for every configured asset_class=="option"
        asset, resolves slice.option_chains via the canonical chain Symbol
        already recorded in self.ticker_to_symbol[asset["ticker"]]
        (main.py::_add_asset()'s return value), parses it into
        available_chain-shaped rows keyed by underlying_ticker (see
        portfolio/options_strategy.py::select_single_leg_contract()/
        build_options_position_sizing()).

        Prefers Lean's own contract.greeks/contract.implied_volatility when
        non-null/non-zero (some data providers, incl. IB, supply these
        directly); falls back to features/options_greeks.py's
        implied_volatility()+compute_greeks() (from bid/ask mid,
        self.options_risk_free_rate, dividend_yield=0.0) otherwise. Never
        executed against real Lean this pass - verified only against the
        locally-installed quantconnect-stubs package's type signatures.

        Degrades to [] per underlying on any failure - never raises,
        matching _run_sequence_model()'s blanket-except-return convention."""
        payload: dict[str, list[dict]] = {}
        for asset in self.phase1["universe"]["assets"]:
            asset_class = asset.get("asset_class") or asset.get("security_type")
            if asset_class != "option":
                continue
            underlying_ticker = asset.get("underlying_ticker")
            if not underlying_ticker:
                continue
            chain_symbol = self.ticker_to_symbol.get(asset["ticker"])
            if chain_symbol is None:
                payload[underlying_ticker] = []
                continue
            try:
                chain = slice.option_chains.get(chain_symbol)
                if chain is None:
                    payload[underlying_ticker] = []
                    continue
                rows = []
                for contract in chain.contracts.values():
                    right = "call" if contract.right == OptionRight.CALL else "put"
                    greeks = contract.greeks
                    delta_value = float(greeks.delta) if greeks is not None else 0.0
                    gamma_value = float(greeks.gamma) if greeks is not None else 0.0
                    theta_value = float(greeks.theta) if greeks is not None else 0.0
                    vega_value = float(greeks.vega) if greeks is not None else 0.0
                    rho_value = float(greeks.rho) if greeks is not None else 0.0
                    iv_value = float(contract.implied_volatility) if contract.implied_volatility else 0.0

                    # Lean/IB didn't supply usable greeks for this contract -
                    # fall back to our own Black-Scholes solve from the mid
                    # price, per the user's requirement for real greeks/IV
                    # rather than proxies whenever real chain data exists.
                    if not delta_value and not vega_value:
                        bid_price = float(contract.bid_price or 0.0)
                        ask_price = float(contract.ask_price or 0.0)
                        mid_price = (bid_price + ask_price) / 2.0 if bid_price > 0 and ask_price > 0 else float(contract.last_price or 0.0)
                        spot = float(contract.underlying_last_price or 0.0)
                        time_to_expiry_years = max((contract.expiry.date() - self.Time.date()).days, 0) / 365.0
                        if mid_price > 0 and spot > 0 and time_to_expiry_years > 0:
                            solved_iv = implied_volatility(
                                option_price=mid_price, spot=spot, strike=float(contract.strike),
                                time_to_expiry_years=time_to_expiry_years,
                                risk_free_rate=self.options_risk_free_rate, dividend_yield=0.0, right=right,
                                max_iterations=self.options_iv_solver_max_iterations,
                                tolerance=self.options_iv_solver_tolerance,
                            )
                            if solved_iv is not None:
                                computed = compute_greeks(
                                    spot=spot, strike=float(contract.strike),
                                    time_to_expiry_years=time_to_expiry_years,
                                    risk_free_rate=self.options_risk_free_rate,
                                    volatility=solved_iv, dividend_yield=0.0, right=right,
                                )
                                delta_value, gamma_value = computed["delta"], computed["gamma"]
                                theta_value, vega_value, rho_value = computed["theta"], computed["vega"], computed["rho"]
                                iv_value = solved_iv

                    rows.append({
                        "symbol": contract.symbol,
                        "strike": float(contract.strike),
                        "right": right,
                        "expiry": contract.expiry.date().isoformat(),
                        "bid": float(contract.bid_price or 0.0),
                        "ask": float(contract.ask_price or 0.0),
                        "volume": float(contract.volume or 0.0),
                        "open_interest": float(contract.open_interest or 0.0),
                        "delta": delta_value, "gamma": gamma_value, "theta": theta_value,
                        "vega": vega_value, "rho": rho_value, "iv": iv_value,
                    })
                payload[underlying_ticker] = rows
            except Exception as error:
                self.Debug(f"Options chain parse failed for {underlying_ticker}: {error}")
                payload[underlying_ticker] = []
        return payload

    def _options_chains_payload_for_state(self) -> dict[str, list[dict]]:
        """JSON-safe copy of self.latest_options_chains_payload for
        _write_state() only - each row's "symbol" is a raw Lean Symbol
        (needed unchanged by _apply_option_order()'s real MarketOrder()
        call), which json.dumps() cannot serialize. Same
        stringify-a-copy-not-the-original precedent as the
        "dynamic_sizing_for_state" sanitization in on_data() for
        OptionsPositionDecision.contract_symbol - reusing that fix's
        lesson here rather than re-learning it via a second silent
        dashboard-state-write crash."""
        return {
            underlying: [{**row, "symbol": str(row["symbol"])} for row in rows]
            for underlying, rows in self.latest_options_chains_payload.items()
        }

    def _build_futures_chains_payload(self, slice: Slice) -> dict[str, dict]:
        """Futures sibling of _build_options_chains_payload() - front/
        next-month price pair per configured asset_class=="future" asset,
        keyed by asset["ticker"]. Degrades to a missing key (never raises) -
        futures_term_structure_slope(None, None) then neutral-defaults."""
        payload: dict[str, dict] = {}
        for asset in self.phase1["universe"]["assets"]:
            asset_class = asset.get("asset_class") or asset.get("security_type")
            if asset_class != "future":
                continue
            ticker = asset["ticker"]
            chain_symbol = self.ticker_to_symbol.get(ticker)
            if chain_symbol is None:
                continue
            try:
                chain = slice.futures_chains.get(chain_symbol)
                if chain is None:
                    continue
                contracts = sorted(chain.contracts.values(), key=lambda c: c.expiry)
                if not contracts:
                    continue

                def _contract_price(contract) -> float | None:
                    if contract.last_price:
                        return float(contract.last_price)
                    bid_price, ask_price = float(contract.bid_price or 0.0), float(contract.ask_price or 0.0)
                    return (bid_price + ask_price) / 2.0 if bid_price > 0 and ask_price > 0 else None

                payload[ticker] = {
                    "front_month_price": _contract_price(contracts[0]),
                    "next_month_price": _contract_price(contracts[1]) if len(contracts) > 1 else None,
                }
            except Exception as error:
                self.Debug(f"Futures chain parse failed for {ticker}: {error}")
        return payload

    def _build_derivatives_macro_payload(self) -> dict:
        """Fourth cross-asset macro sibling to _build_macro_payload()/
        _build_bond_payload() (features/derivatives_macro_features.py) -
        computed once per bar, AFTER self.latest_futures_chains_payload/
        self.latest_options_chains_payload are built this same on_data()
        call, via self.derivatives_reference_tickers (one reference
        underlying per signal, same pattern as self.macro_reference_tickers).
        Neutral-defaults to 0.0 whenever the reference ticker isn't
        configured/subscribed - correct, honest behavior until the user
        adds a future/option asset shaped for this, not a bug."""
        futures_ticker = self.derivatives_reference_tickers.get("futures_term_structure")
        futures_row = self.latest_futures_chains_payload.get(futures_ticker) if futures_ticker else None
        front_month_price = futures_row.get("front_month_price") if futures_row else None
        next_month_price = futures_row.get("next_month_price") if futures_row else None

        options_ticker = self.derivatives_reference_tickers.get("options_sentiment")
        chain_rows = self.latest_options_chains_payload.get(options_ticker, []) if options_ticker else []
        put_volume = sum(float(row.get("volume") or 0.0) for row in chain_rows if row.get("right") == "put")
        call_volume = sum(float(row.get("volume") or 0.0) for row in chain_rows if row.get("right") == "call")

        def _nearest_delta_iv(right: str, target_delta: float) -> float | None:
            candidates = [
                row for row in chain_rows
                if row.get("right") == right and row.get("delta") is not None and row.get("iv") is not None
            ]
            if not candidates:
                return None
            return float(min(candidates, key=lambda row: abs(row["delta"] - target_delta))["iv"])

        return {
            "futures_term_structure_slope": futures_term_structure_slope(front_month_price, next_month_price),
            "options_put_call_ratio": options_put_call_ratio(
                put_volume if chain_rows else None, call_volume if chain_rows else None
            ),
            "options_implied_vol_skew": options_implied_vol_skew(
                _nearest_delta_iv("put", -0.25), _nearest_delta_iv("call", 0.25)
            ),
        }

    def _build_regime_payload(self, base_features: dict, average_correlation: float = 0.0) -> dict:
        # Statistical/diagnostic bypass only (see risk_controls.py::
        # is_backtest_safety_bypass_active() and Problems.md): disables
        # only the drawdown-driven branch of risk_off classification, so a
        # stale, never-recovering portfolio-drawdown number can't freeze
        # every asset's signal for the rest of a bypass-mode backtest run.
        # The bearish-trend+high-vol and composite risk-score branches of
        # classify_risk_regime stay fully active either way.
        bypass_active = is_backtest_safety_bypass_active(self.runtime_mode, self.bypass_safety_gates)
        risk_off_drawdown_threshold = float("inf") if bypass_active else self.regime_risk_off_drawdown_threshold
        vector = build_market_regime_vector(
            base_features,
            portfolio_drawdown=self.current_total_drawdown,
            average_correlation=average_correlation,
            bullish_threshold=self.regime_bullish_threshold,
            bearish_threshold=self.regime_bearish_threshold,
            low_volatility_threshold=self.low_volatility_threshold,
            high_volatility_threshold=self.high_volatility_threshold,
            risk_off_drawdown_threshold=risk_off_drawdown_threshold,
            risk_on_drawdown_threshold=self.regime_risk_on_drawdown_threshold,
            high_correlation_threshold=self.regime_high_correlation_threshold,
        )
        return vector.to_dict()

    def _recompute_broker_config(self) -> None:
        """Single place both initialize() and _refresh_risk_state()'s
        session-rollover call into - keeps the paper (V2-21) and live
        (V2-22) broker-readiness check consistent regardless of which
        mode is active. Live credentials are loaded once at startup
        (execution/live_credentials_io.load_live_credentials() reads
        ib_config.py/env vars, neither of which changes mid-run the way
        config.json can), but the risk-posture ceiling and paper_trading
        attestation flags are re-evaluated fresh every rollover."""
        self._broker_config_present, self._broker_config_reason = evaluate_broker_config(
            self.runtime_mode,
            self.phase_v2_paper_trading,
            live_credentials_present=credentials_present(self._live_credentials),
            risk_config={
                "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
                "max_total_drawdown_pct": self.max_total_drawdown_pct,
                "liquidate_on_risk_breach": self.liquidate_on_risk_breach,
            },
            live_config=self.phase_v2_live,
        )

    def _order_permission(self) -> tuple[bool, str]:
        return resolve_order_permission(
            mode=self.runtime_mode,
            allow_live_orders=self.allow_live_orders,
            broker_config_present=self._broker_config_present,
            risk_locks_healthy=not self.trade_lock_active,
        )

    def _is_invested(self, symbol, orders_allowed: bool) -> bool:
        if orders_allowed:
            return bool(self.Portfolio[self._order_target_symbol(symbol)].Invested)
        # The simulated/observation-mode portfolio is Aether's own
        # abstraction, always keyed by the canonical chain Symbol string
        # regardless of asset class (it never places a real Lean order on
        # a specific contract) - no contract-symbol substitution needed
        # here, unlike the real-order path above.
        return str(symbol) in self._simulated_portfolio.holdings

    def _order_target_symbol(self, symbol):
        """The actual Lean Symbol a real order/Liquidate/Invested-check
        should target for `symbol` - the tracked option CONTRACT Symbol
        (self.option_contract_symbol_by_symbol) when one exists for this
        chain Symbol, else `symbol` itself unchanged (every non-option
        asset class, and an option asset with no currently-open contract
        position)."""
        return self.option_contract_symbol_by_symbol.get(str(symbol), symbol)

    def _try_submit_limit_order(
        self,
        symbol,
        symbol_key: str,
        asset_class: str | None,
        is_buy: bool,
        target_weight: float,
        close_price: float,
        contract_quantity: float | None = None,
        chain_symbol=None,
    ) -> bool:
        """Config-gated real limit-order submission (execution/risk
        realism pass, part 2), shared by every real-order branch in
        _apply_signal()/_apply_option_order() (buy/short x
        equity-crypto-bond/future/option). Returns False immediately
        whenever phase_v2.limit_orders is disabled or asset_class isn't in
        the configured subset - the ONLY behavior this method can ever
        have when the feature is off is a no-op early return, by
        construction, so every caller's existing MarketOrder()/
        SetHoldings() branch (unchanged) is what actually executes.

        contract_quantity, when given, is used exactly as submitted by
        the caller - future's _futures_contract_count_for_weight()
        result is already signed by target_weight (positive=long,
        negative=short, matching MarketOrder(symbol, contract_count)'s
        own existing convention), and option's options_decision.contracts
        is always positive (direction is which contract/right was
        selected, never order sign - options are never shorted). Neither
        needs sign massaging here; get either one wrong upstream and this
        method would just faithfully submit the wrong-signed order, same
        as the existing MarketOrder() calls would. Equity/crypto/bond
        (contract_quantity=None) instead calls Lean's own
        self.CalculateOrderQuantity(symbol, target_weight) - reusing
        Lean's built-in weight->quantity math (whose sign already matches
        target_weight, same as SetHoldings(symbol, target_weight) today)
        instead of writing new custom sizing logic.

        Limit price via resolve_limit_price(), reusing this bar's already-
        computed liquidity spread_proxy (self.latest_liquidity_by_symbol)
        rather than a new estimate. On success, records the OrderTicket in
        self.pending_limit_orders keyed by symbol_key and returns True -
        callers must NOT also stamp last_trade_bar_by_symbol in this
        branch (cooldown is stamped at confirmed-fill time via
        on_order_event(), not here - see execution/README.md's "Real
        limit orders" section).

        chain_symbol is only needed when it differs from `symbol` - i.e.
        options, where `symbol` is the tradeable CONTRACT Symbol (what
        LimitOrder()/Cancel()/the MarketOrder fallback must target) but
        last_trade_bar_by_symbol is keyed by the CHAIN Symbol everywhere
        else in this file (see _apply_option_order()'s own
        self.last_trade_bar_by_symbol[symbol] = ... using its chain
        `symbol` parameter, never contract_symbol). Defaults to `symbol`
        itself for every other asset class, where the two are identical."""
        if not self.limit_orders_enabled or asset_class not in self.limit_orders_asset_classes:
            return False

        quantity = self.CalculateOrderQuantity(symbol, target_weight) if contract_quantity is None else contract_quantity
        if quantity == 0:
            return False

        liquidity_payload = self.latest_liquidity_by_symbol.get(symbol_key, {})
        spread_fraction = float(liquidity_payload.get("spread_proxy", 0.0) or 0.0)
        limit_price = resolve_limit_price(close_price, spread_fraction, is_buy, self.limit_order_offset_multiplier)

        ticket = self.LimitOrder(symbol, quantity, limit_price)
        self.pending_limit_orders[symbol_key] = {
            "ticket": ticket,
            "symbol": symbol,
            "chain_symbol": chain_symbol if chain_symbol is not None else symbol,
            "symbol_key": symbol_key,
            "asset_class": asset_class,
            "submitted_bar": self.bar_index,
            "direction": "buy" if is_buy else "sell",
            "target_weight": target_weight,
        }
        return True

    def _apply_option_order(
        self, symbol, symbol_key: str, sizing_payload: dict | None, target_weight: float,
        close_price: float, orders_allowed: bool, permission_reason: str,
    ) -> str:
        """Shared by _apply_signal()'s "buy" and "short" branches for
        asset_class == "option". Retrieves the OptionsPositionDecision
        computed this bar (risk/asset_class_router.py, surfaced via
        sizing_payload["asset_class_routing_extra"]["options_decision"] -
        see _build_dynamic_sizing_payload()) and places a real order on
        its resolved CONTRACT Symbol - never the canonical chain Symbol
        main.py subscribes to (self.add_option()'s return value is not
        itself a tradable contract). Records the contract in
        self.option_contract_symbol_by_symbol/
        self.symbol_key_by_option_contract_symbol (A7) so
        _is_invested()/the sell and hold-liquidate branches/
        _asset_class_exposure() can find this position again.

        options_decision.contracts is always a positive quantity -
        direction is encoded by which right (call vs put) was selected,
        never by order sign, since portfolio/options_strategy.py never
        shorts options (see that module's docstring).

        Never executed against real Lean this pass - verified only
        against the locally-installed quantconnect-stubs package."""
        options_decision = ((sizing_payload or {}).get("asset_class_routing_extra") or {}).get("options_decision")
        contract_symbol = getattr(options_decision, "contract_symbol", None) if options_decision is not None else None
        if options_decision is None or contract_symbol is None:
            return "options_no_usable_contract"

        if orders_allowed:
            # Set eagerly (before attempting either order type) - required
            # for on_order_event() to resolve a fill on the CONTRACT
            # symbol back to this chain symbol_key even when the limit-
            # order path below is taken. Harmless if the limit order is
            # later canceled with no fallback fill: _is_invested()/
            # _asset_class_exposure() both key off Lean's own Portfolio
            # holdings (ground truth), never this dict directly, and any
            # later real order on this symbol unconditionally overwrites
            # it anyway.
            self.option_contract_symbol_by_symbol[symbol_key] = contract_symbol
            self.symbol_key_by_option_contract_symbol[str(contract_symbol)] = symbol_key
            if self._try_submit_limit_order(
                contract_symbol,
                symbol_key,
                "option",
                is_buy=True,
                target_weight=target_weight,
                close_price=close_price,
                contract_quantity=options_decision.contracts,
                chain_symbol=symbol,
            ):
                return f"submitted_limit_option_{options_decision.right}"
            self.MarketOrder(contract_symbol, options_decision.contracts)
            self.last_trade_bar_by_symbol[symbol] = self.bar_index
            return f"entered_option_{options_decision.right}"

        self._simulated_portfolio.enter_long(
            symbol_key,
            close_price,
            target_weight,
            self.bar_index,
            slippage_bps=resolve_slippage_bps(
                symbol_key, self.latest_liquidity_slippage_bps, max_bps=self._liquidity_slippage_max_bps
            ),
        )
        self.last_trade_bar_by_symbol[symbol] = self.bar_index
        return f"simulated_entered_option_{options_decision.right}:{permission_reason}"

    def _liquidate_position(self, symbol) -> None:
        """self.Liquidate() targeting the correct Lean Symbol (A7 - the
        tracked option contract Symbol when one exists, else `symbol`
        itself), then clears the option-contract-tracking maps so a
        subsequent _is_invested()/_asset_class_exposure() call correctly
        sees the position as closed."""
        self.Liquidate(self._order_target_symbol(symbol))
        symbol_key = str(symbol)
        contract_symbol = self.option_contract_symbol_by_symbol.pop(symbol_key, None)
        if contract_symbol is not None:
            self.symbol_key_by_option_contract_symbol.pop(str(contract_symbol), None)

    def _apply_signal(
        self, symbol, signal_name: str, target_weight: float, close_price: float, sizing_payload: dict | None = None
    ) -> str:
        symbol_key = str(symbol)
        previous_signal = self.latest_signal_state.get(symbol_key, "hold")
        last_trade_bar = self.last_trade_bar_by_symbol.get(symbol, -1000000)
        asset = self.asset_lookup.get(symbol_key, {})
        orders_allowed, permission_reason = self._order_permission()

        if self.bar_index - last_trade_bar < self.trade_cooldown_bars and signal_name != previous_signal:
            return "cooldown_active"

        self.latest_signal_state[symbol_key] = signal_name

        if signal_name == "buy":
            if active_position_limit_reached(
                self._active_position_count(symbol, orders_allowed),
                self.max_active_positions,
                self._is_invested(symbol, orders_allowed),
            ):
                return "max_active_positions_reached"

            asset_class = asset.get("asset_class") or asset.get("security_type")
            exposure_cap = self.exposure_caps_by_asset_class.get(asset_class, self.max_equity_exposure)
            current_exposure = self._asset_class_exposure(asset_class, orders_allowed, exclude_symbol=symbol)
            target_weight, cap_reached = cap_target_weight(target_weight, current_exposure, exposure_cap)
            if cap_reached:
                return f"{asset_class or 'asset'}_exposure_cap_reached"

            if asset_class == "option":
                return self._apply_option_order(symbol, symbol_key, sizing_payload, target_weight, close_price, orders_allowed, permission_reason)

            if asset_class == "future":
                contract_spec = self.futures_contract_specs.get(asset.get("ticker"), {})
                contract_count = self._futures_contract_count_for_weight(target_weight, contract_spec, close_price, orders_allowed)
                if contract_count == 0:
                    return "futures_zero_contract_count"
                if orders_allowed:
                    if self._try_submit_limit_order(
                        symbol, symbol_key, "future", is_buy=True, target_weight=target_weight,
                        close_price=close_price, contract_quantity=contract_count,
                    ):
                        return "submitted_limit_long_futures"
                    self.MarketOrder(symbol, contract_count)
                    self.last_trade_bar_by_symbol[symbol] = self.bar_index
                    return "entered_long_futures"
                self._simulated_portfolio.enter_long(
                    symbol_key,
                    close_price,
                    target_weight,
                    self.bar_index,
                    slippage_bps=resolve_slippage_bps(
                        symbol_key, self.latest_liquidity_slippage_bps, max_bps=self._liquidity_slippage_max_bps
                    ),
                )
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return f"simulated_entered_long_futures:{permission_reason}"

            if previous_signal != "buy" or not self._is_invested(symbol, orders_allowed):
                if orders_allowed:
                    if self._try_submit_limit_order(
                        symbol, symbol_key, asset_class, is_buy=True, target_weight=target_weight,
                        close_price=close_price,
                    ):
                        return "submitted_limit_long"
                    self.SetHoldings(symbol, target_weight)
                    self.last_trade_bar_by_symbol[symbol] = self.bar_index
                    return "entered_long"
                self._simulated_portfolio.enter_long(
                    symbol_key,
                    close_price,
                    target_weight,
                    self.bar_index,
                    slippage_bps=resolve_slippage_bps(
                        symbol_key, self.latest_liquidity_slippage_bps, max_bps=self._liquidity_slippage_max_bps
                    ),
                )
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return f"simulated_entered_long:{permission_reason}"
            return "kept_long" if orders_allowed else "simulated_kept_long"

        if signal_name == "sell":
            if self._is_invested(symbol, orders_allowed):
                if orders_allowed:
                    self._liquidate_position(symbol)
                else:
                    self._simulated_portfolio.exit(symbol_key, close_price, self.bar_index)
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return "liquidated_on_sell" if orders_allowed else f"simulated_liquidated_on_sell:{permission_reason}"
            return "already_flat"

        # Phase 3 of the 5/10 -> 9/10 roadmap: the portfolio book's ONLY
        # signal_name distinct from the existing buy/sell/hold set -
        # target_weight is genuinely negative here (unlike "sell", which
        # only ever liquidates to flat and ignores target_weight's sign
        # entirely). SetHoldings()/enter_long() both already handle a
        # negative target_weight correctly by construction (Lean's
        # SetHoldings opens a short for a negative percentage;
        # experience/simulated_portfolio.py::simulate_fill()'s
        # notional = target_weight * equity is sign-generic despite the
        # enter_long() method name) - the real gap closed here is the
        # signal-routing branch itself, which never existed before.
        if signal_name == "short":
            if active_position_limit_reached(
                self._active_position_count(symbol, orders_allowed),
                self.max_active_positions,
                self._is_invested(symbol, orders_allowed),
            ):
                return "max_active_positions_reached"

            current_short_exposure = self._short_exposure(orders_allowed, exclude_symbol=symbol)
            target_weight, cap_reached = cap_target_weight(target_weight, current_short_exposure, self.max_short_exposure)
            if cap_reached:
                return "short_exposure_cap_reached"

            asset_class = asset.get("asset_class") or asset.get("security_type")
            if asset_class == "option":
                return self._apply_option_order(symbol, symbol_key, sizing_payload, target_weight, close_price, orders_allowed, permission_reason)
            if asset_class == "future":
                contract_spec = self.futures_contract_specs.get(asset.get("ticker"), {})
                contract_count = self._futures_contract_count_for_weight(target_weight, contract_spec, close_price, orders_allowed)
                if contract_count == 0:
                    return "futures_zero_contract_count"
                if orders_allowed:
                    if self._try_submit_limit_order(
                        symbol, symbol_key, "future", is_buy=False, target_weight=target_weight,
                        close_price=close_price, contract_quantity=contract_count,
                    ):
                        return "submitted_limit_short_futures"
                    self.MarketOrder(symbol, contract_count)
                    self.last_trade_bar_by_symbol[symbol] = self.bar_index
                    return "entered_short_futures"
                self._simulated_portfolio.enter_long(
                    symbol_key,
                    close_price,
                    target_weight,
                    self.bar_index,
                    slippage_bps=resolve_slippage_bps(
                        symbol_key, self.latest_liquidity_slippage_bps, max_bps=self._liquidity_slippage_max_bps
                    ),
                )
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return f"simulated_entered_short_futures:{permission_reason}"

            if previous_signal != "short" or not self._is_invested(symbol, orders_allowed):
                if orders_allowed:
                    if self._try_submit_limit_order(
                        symbol, symbol_key, asset_class, is_buy=False, target_weight=target_weight,
                        close_price=close_price,
                    ):
                        return "submitted_limit_short"
                    self.SetHoldings(symbol, target_weight)
                    self.last_trade_bar_by_symbol[symbol] = self.bar_index
                    return "entered_short"
                self._simulated_portfolio.enter_long(
                    symbol_key,
                    close_price,
                    target_weight,
                    self.bar_index,
                    slippage_bps=resolve_slippage_bps(
                        symbol_key, self.latest_liquidity_slippage_bps, max_bps=self._liquidity_slippage_max_bps
                    ),
                )
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return f"simulated_entered_short:{permission_reason}"
            return "kept_short" if orders_allowed else "simulated_kept_short"

        if signal_name == "hold" and previous_signal != "hold" and self._is_invested(symbol, orders_allowed):
            if orders_allowed:
                self._liquidate_position(symbol)
            else:
                self._simulated_portfolio.exit(symbol_key, close_price, self.bar_index)
            self.last_trade_bar_by_symbol[symbol] = self.bar_index
            return "liquidated_on_hold" if orders_allowed else f"simulated_liquidated_on_hold:{permission_reason}"

        return "no_action"

    def _asset_quality_for_symbol(self, symbol) -> dict:
        ticker = self.asset_lookup.get(str(symbol), {}).get("ticker", str(symbol))
        return self.asset_quality.get(
            ticker,
            {
                "ticker": ticker,
                "quality_tier": "unknown",
                "role": "observation_only",
                "training_eligible": False,
                "trading_eligible": False,
                "reason": "missing_asset_quality_metadata",
            },
        )

    def _is_trading_eligible(self, symbol) -> bool:
        if self.observation_only_assets_can_trade:
            return True
        ticker = self.asset_lookup.get(str(symbol), {}).get("ticker", str(symbol))
        return ticker in self.trading_eligible_tickers

    def _active_position_count(self, exclude_symbol=None, orders_allowed: bool = True) -> int:
        if orders_allowed:
            count = 0
            for holding in self.Portfolio.Values:
                if exclude_symbol is not None and holding.Symbol == exclude_symbol:
                    continue
                if holding.Invested:
                    count += 1
            return count

        exclude_key = str(exclude_symbol) if exclude_symbol is not None else None
        return sum(1 for symbol_key in self._simulated_portfolio.holdings if symbol_key != exclude_key)

    def _asset_class_exposure(self, asset_class: str | None, orders_allowed: bool = True, exclude_symbol=None) -> float:
        """asset_class here means the SAME asset_class-or-security_type
        fallback value used everywhere else in this multi-asset-class
        wiring (asset.get("asset_class") or asset.get("security_type")) -
        NOT Lean's raw security_type. Bond ETFs are security_type=="equity"
        but asset_class=="bond"; comparing against the fallback value (not
        raw security_type) is what correctly buckets them as bond
        exposure instead of silently double-counting them as equity
        exposure."""
        def _matches(asset: dict) -> bool:
            return (asset.get("asset_class") or asset.get("security_type")) == asset_class

        if orders_allowed:
            total_value = max(float(self.Portfolio.TotalPortfolioValue), 1.0)
            exposure = 0.0
            exclude_target = self._order_target_symbol(exclude_symbol) if exclude_symbol is not None else None
            for holding in self.Portfolio.Values:
                if exclude_target is not None and holding.Symbol == exclude_target:
                    continue
                # A7: a real option position is held on the CONTRACT Symbol,
                # not the canonical chain Symbol self.asset_lookup is keyed
                # by - resolve back to the chain symbol_key via the reverse
                # map before the asset_lookup, else this option holding is
                # silently invisible to every exposure cap.
                holding_symbol_key = self.symbol_key_by_option_contract_symbol.get(
                    str(holding.Symbol), str(holding.Symbol)
                )
                asset = self.asset_lookup.get(holding_symbol_key, {})
                if not _matches(asset):
                    continue
                exposure += abs(float(holding.HoldingsValue)) / total_value
            return exposure

        exclude_key = str(exclude_symbol) if exclude_symbol is not None else None
        total_value = max(float(self._simulated_portfolio.snapshot(consume_realized_pnl=False)["total_value"]), 1.0)
        exposure = 0.0
        for symbol_key in self._simulated_portfolio.holdings:
            if symbol_key == exclude_key:
                continue
            asset = self.asset_lookup.get(symbol_key, {})
            if not _matches(asset):
                continue
            exposure += abs(self._simulated_portfolio.position_value(symbol_key)) / total_value
        return exposure

    def _futures_contract_count_for_weight(self, target_weight: float, contract_spec: dict, close_price: float, orders_allowed: bool) -> int:
        """Derives a whole-number contract count from the FINAL target
        weight (after liquidity/analyzer adjustments), rather than
        threading risk/futures_risk.py's originally-computed contract
        count through the whole weight-based liquidity/analyzer pipeline
        unchanged. target_weight is already margin-aware by construction
        (risk/asset_class_router.py::_futures_decision_to_position_sizing()
        derives it FROM build_futures_position_sizing()'s margin-budgeted
        contract count) - re-deriving here just means any downstream
        liquidity-driven shrinkage of the weight is correctly reflected as
        a SMALLER final contract count too, the conservative direction.
        Returns 0 (never raises) when the contract spec is missing or
        price/portfolio value are non-positive."""
        multiplier = float(contract_spec.get("multiplier", 0.0) or 0.0)
        if multiplier <= 0.0 or close_price <= 0.0:
            return 0
        portfolio_value = (
            float(self.Portfolio.TotalPortfolioValue)
            if orders_allowed
            else float(self._simulated_portfolio.snapshot(consume_realized_pnl=False)["total_value"])
        )
        if portfolio_value <= 0.0:
            return 0
        notional = target_weight * portfolio_value
        return int(round(notional / (multiplier * close_price)))

    def _short_exposure(self, orders_allowed: bool = True, exclude_symbol=None) -> float:
        """Phase 3 of the 5/10 -> 9/10 roadmap: total exposure currently
        held SHORT (negative quantity), across every asset class - a new
        concept, since nothing in this codebase could open a short position
        before the portfolio book (see _apply_signal()'s new "short" branch).
        Same direction-agnostic-by-quantity-sign shape as
        _asset_class_exposure() above, filtered by sign instead of asset
        class."""
        if orders_allowed:
            total_value = max(float(self.Portfolio.TotalPortfolioValue), 1.0)
            exposure = 0.0
            for holding in self.Portfolio.Values:
                if exclude_symbol is not None and holding.Symbol == exclude_symbol:
                    continue
                if float(holding.Quantity) >= 0:
                    continue
                exposure += abs(float(holding.HoldingsValue)) / total_value
            return exposure

        exclude_key = str(exclude_symbol) if exclude_symbol is not None else None
        total_value = max(float(self._simulated_portfolio.snapshot(consume_realized_pnl=False)["total_value"]), 1.0)
        exposure = 0.0
        for symbol_key, holding in self._simulated_portfolio.holdings.items():
            if symbol_key == exclude_key:
                continue
            if holding["quantity"] >= 0:
                continue
            exposure += abs(self._simulated_portfolio.position_value(symbol_key)) / total_value
        return exposure

    def _refresh_risk_state(self) -> None:
        orders_allowed, _ = self._order_permission()
        portfolio_value = (
            float(self.Portfolio.TotalPortfolioValue)
            if orders_allowed
            else float(self._simulated_portfolio.snapshot(consume_realized_pnl=False)["total_value"])
        )
        current_date = self.Time.date()

        if self.current_session_date != current_date:
            if self.current_session_date is not None:
                session_summary_event = build_session_summary_event(
                    mode=self._experience_mode,
                    session_date=self.current_session_date,
                    session_start_equity=self.session_start_equity,
                    session_end_equity=portfolio_value,
                    events=self._session_events,
                )
                self._experience_queue.push(session_summary_event)
            self._session_events = []
            self.current_session_date = current_date
            self.session_start_equity = portfolio_value
            # Statistical/diagnostic bypass only (see risk_controls.py::
            # is_backtest_safety_bypass_active() and Problems.md): normally
            # a total-drawdown breach is deliberately excluded from this
            # daily auto-clear, for live capital preservation - since
            # peak_equity never decreases, once liquidated to flat cash
            # this lock would otherwise never clear again for the rest of
            # a bypass-mode backtest run.
            if self.trade_lock_reason != "total_drawdown_limit_breached" or is_backtest_safety_bypass_active(
                self.runtime_mode, self.bypass_safety_gates
            ):
                self.trade_lock_active = False
                self.trade_lock_reason = None

            # Manual trade-lock override (`aq trade-lock --on/--off`, or an
            # auto-clear from retraining/orchestrator.py::promote()) - read
            # fresh from config.json once per session rollover, not cached
            # in self.config, so a long-running paper/live process picks up
            # a CLI-issued change without a restart. None leaves the sticky
            # total-drawdown behavior above completely unchanged.
            override = read_manual_trade_lock_override(self.root_path / "config.json")
            if override is True:
                self.trade_lock_active = True
                self.trade_lock_reason = "manual_override_locked"
            elif override is False:
                self.trade_lock_active = False
                self.trade_lock_reason = None

            # Same "fresh from config.json once per session rollover" rule
            # as the manual trade-lock override above - lets a long-running
            # paper/live process pick up a broker-readiness attestation flag
            # (phase_v2.paper_trading.manual_review_confirmed etc.) without
            # a restart. The heavier observation-mode readiness check
            # (min_observations/simulated_sharpe/...) deliberately stays out
            # of this per-bar path - main.py never opens its own Postgres
            # connection, so that check lives only in the offline
            # execution/paper_readiness_report.py (see `aq paper-readiness`).
            self.phase_v2_paper_trading = read_paper_trading_config(self.root_path / "config.json")
            self._recompute_broker_config()

            # Same "fresh from local cache once per session rollover" rule
            # as the two refreshes above - the ALGORITHM only re-reads the
            # local cache file (no network call inside Lean's live thread);
            # keeping the cache itself fresh is a separate, user-scheduled
            # `python -m data_pipeline.fred_backfill --apply` (daily
            # cron/Task Scheduler), not something main.py triggers. Closes
            # the "yield-curve features go stale on a multi-day live/paper
            # deployment" gap - self.fred_series was previously loaded ONCE
            # in _ensure_ready() and never touched again.
            self.fred_series = load_cached_fred_series()

        self.peak_equity = max(self.peak_equity, portfolio_value)
        self.current_daily_drawdown = portfolio_value / max(self.session_start_equity, 1.0) - 1.0
        self.current_total_drawdown = portfolio_value / max(self.peak_equity, 1.0) - 1.0

        breach_active, breach_reason = assess_drawdown_lock(
            self.current_daily_drawdown,
            self.current_total_drawdown,
            self.max_daily_drawdown_pct,
            self.max_total_drawdown_pct,
        )

        if breach_active:
            self.trade_lock_active = True
            self.trade_lock_reason = breach_reason
            if self.liquidate_on_risk_breach:
                if orders_allowed:
                    self.Liquidate()
                else:
                    self._simulated_portfolio.liquidate_all(self.bar_index)

    def _process_pending_limit_order_timeouts(self) -> None:
        """Real limit-order support (execution/risk realism pass, part 2):
        runs once per bar, immediately after _refresh_risk_state() above -
        that's already this codebase's "resolve stale/urgent state before
        this bar's fresh signal computation" anchor point (it does the
        global drawdown-breach Liquidate() there for the identical
        reason). A stale order from a previous bar is resolved (canceled,
        optionally fallback-filled) before this bar's Pass 1/Pass 2 ever
        runs for that symbol - never interleaved with it.

        No-op instantly whenever phase_v2.limit_orders.enabled is False
        or self.pending_limit_orders is empty - zero cost in the
        default-off configuration beyond one dict-emptiness check."""
        if not self.limit_orders_enabled or not self.pending_limit_orders:
            return

        for symbol_key in list(self.pending_limit_orders.keys()):
            pending = self.pending_limit_orders[symbol_key]
            if self.bar_index - pending["submitted_bar"] < self.limit_order_unfilled_timeout_bars:
                continue

            ticket = pending["ticket"]
            status = classify_order_status(getattr(ticket.Status, "name", str(ticket.Status)))
            if status != "pending":
                # Already resolved (filled/canceled) by on_order_event()
                # this bar or an earlier one - just clear the stale
                # bookkeeping entry, no cancel/fallback needed.
                self.pending_limit_orders.pop(symbol_key, None)
                continue

            ticket.Cancel()
            # Per-asset-class, not a single global flag - see
            # limit_order_fallback_to_market_by_asset_class's own comment
            # in _ensure_ready() for the equity/crypto/bond-vs-future/
            # option rationale.
            if self.limit_order_fallback_to_market_by_asset_class.get(pending["asset_class"], True):
                remaining = ticket.QuantityRemaining
                if remaining != 0:
                    self.MarketOrder(pending["symbol"], remaining)
                    self.last_trade_bar_by_symbol[pending["chain_symbol"]] = self.bar_index
            self.pending_limit_orders.pop(symbol_key, None)

    def on_order_event(self, order_event) -> None:
        """Real limit-order support (execution/risk realism pass, part 2):
        Lean's real order-fill/cancel/invalidate callback. Snake_case
        override name, matching this file's proven initialize()/on_data()
        naming - see execution/README.md's "Real limit orders" section for
        why this genuinely-unverified-until-a-real-backtest casing choice
        was made the same way as every other new Lean API surface this
        pass touches.

        Only ever meaningful for orders tracked in
        self.pending_limit_orders - a filled MarketOrder/SetHoldings order
        from the feature-disabled (or non-limit) path was never recorded
        there and is silently ignored here; Lean still calls this hook for
        those too, there is just nothing for it to do.

        Maps order_event.Symbol back to a pending_limit_orders entry via
        self.symbol_key_by_option_contract_symbol for options (the event's
        Symbol is the CONTRACT symbol, not the chain symbol
        pending_limit_orders is keyed by - the same indirection
        _order_target_symbol()/_liquidate_position() already need), else
        str(order_event.Symbol) directly for every other asset class.

        On a "filled" status: stamps last_trade_bar_by_symbol at
        CONFIRMED fill time (not submission time, unlike every
        synchronous market-order branch - see the cooldown-timing note in
        execution/README.md) and clears the pending entry. On
        "canceled": clears the entry only, no cooldown stamp - nothing
        was actually filled. "pending"/"unknown" (e.g. a partial fill):
        left alone, the entry stays tracked for
        _process_pending_limit_order_timeouts() to eventually resolve."""
        symbol_key = self.symbol_key_by_option_contract_symbol.get(
            str(order_event.Symbol), str(order_event.Symbol)
        )
        pending = self.pending_limit_orders.get(symbol_key)
        if pending is None:
            return

        status = classify_order_status(getattr(order_event.Status, "name", str(order_event.Status)))
        if status == "filled":
            self.last_trade_bar_by_symbol[pending["chain_symbol"]] = self.bar_index
            self.pending_limit_orders.pop(symbol_key, None)
        elif status == "canceled":
            self.pending_limit_orders.pop(symbol_key, None)

    def _write_state(self, mode: str, insight: str, signals: dict | None = None) -> None:
        now = self.Time if hasattr(self, "Time") else datetime.utcnow()
        if self.last_state_write == now:
            return

        state = {
            "project": "Aether Quant",
            "mode": mode,
            "updated_at": now.isoformat(),
            "insight": insight,
            "portfolio": self._snapshot_portfolio_summary(),
            "universe": {
                "name": self.phase1["universe"]["name"],
                "resolution": self.phase1["universe"]["resolution"],
                "assets": [asset["ticker"] for asset in self.phase1["universe"]["assets"]],
                "trading_eligible_assets": sorted(self.trading_eligible_tickers),
                "observation_only_assets": [
                    ticker
                    for ticker, quality in self.asset_quality.items()
                    if not bool(quality.get("trading_eligible", False))
                ],
            },
            "model": {
                "type": self.model_export["model"]["type"],
                "decision_threshold": self.decision_threshold,
                "buy_threshold": self.buy_threshold,
                "sell_threshold": self.sell_threshold,
                "input_count": len(self.model_input_names),
                "moe": {
                    "expert_exports_loaded": sorted(self.expert_model_exports.keys()),
                    "gating_metrics_loaded": bool(self.expert_training_metrics),
                    "baseline_weight": self.gating_baseline_weight,
                    "sequence_weight": self.gating_sequence_weight,
                },
                "multitask": {
                    "model_loaded": bool(self.multitask_model),
                    "use_predicted_volatility": self.use_predicted_volatility,
                },
                "sequence": {
                    "model_loaded": bool(self.sequence_model),
                    "window_size": self.sequence_window_size,
                    # False once phase_v2.gating_network.sequence_weight > 0
                    # actually blends the sequence model into
                    # final_probability_up/final_magnitude/final_volatility
                    # (moe/gating.py) - True (the pre-existing, still-default
                    # behavior) whenever that weight is 0.
                    "informational_only": self.gating_sequence_weight <= 0.0,
                },
            },
            "paper_trading": {
                "brokerage": self.phase_v2_paper_trading.get("brokerage", ""),
                "broker_config_present": self._broker_config_present,
                "broker_config_reason": self._broker_config_reason,
                "manual_review_confirmed": bool(self.phase_v2_paper_trading.get("manual_review_confirmed", False)),
            },
            "risk": {
                "trade_lock_active": self.trade_lock_active,
                "trade_lock_reason": self.trade_lock_reason,
                "daily_drawdown": self.current_daily_drawdown,
                "total_drawdown": self.current_total_drawdown,
                "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
                "max_total_drawdown_pct": self.max_total_drawdown_pct,
                "min_confidence_to_trade": self.min_confidence_to_trade,
                "trade_cooldown_bars": self.trade_cooldown_bars,
                "max_position_weight": self.max_position_weight,
                "max_active_positions": self.max_active_positions,
                "max_equity_exposure": self.max_equity_exposure,
                "max_crypto_exposure": self.max_crypto_exposure,
                "target_daily_volatility": self.target_daily_volatility,
                "low_volatility_threshold": self.low_volatility_threshold,
                "high_volatility_threshold": self.high_volatility_threshold,
                "max_leverage": self.max_leverage,
            },
            "positions": self._snapshot_positions(),
            "signals": signals or {},
        }

        state["regime"] = self._build_regime_summary(state["signals"])
        state["topology"] = self.latest_topology_payload
        state["derivatives"] = {
            "macro": self.latest_derivatives_macro_payload,
            "options_chains": self._options_chains_payload_for_state(),
            "futures_chains": self.latest_futures_chains_payload,
        }
        state["observation"] = self._build_observation_view()
        state["performance_triggers"] = self._build_performance_triggers_view()
        state["dashboard"] = self._build_dashboard_view(state)
        state["monitoring"] = self._build_monitoring_view(state)
        state["scene"] = self._build_scene_payload(state)

        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.grafana_dir.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            self.scene_path.write_text(json.dumps(state["scene"], indent=2), encoding="utf-8")
            self.topology_state_path.write_text(json.dumps(state["topology"], indent=2), encoding="utf-8")
            self.runtime_metrics_path.write_text(json.dumps(state["monitoring"], indent=2), encoding="utf-8")
            self.runtime_asset_metrics_path.write_text(self._build_runtime_asset_csv(state), encoding="utf-8")
            self.observation_summary_path.write_text(json.dumps(state["observation"], indent=2), encoding="utf-8")
            self._flush_observation_equity_csv()
            self.performance_triggers_path.write_text(
                json.dumps(state["performance_triggers"], indent=2), encoding="utf-8"
            )
            self.last_state_write = now
        except Exception as error:
            self.Debug(f"State write failed: {error}")

    def _snapshot_portfolio_summary(self) -> dict:
        orders_allowed, _ = self._order_permission()
        if orders_allowed:
            return {
                "cash": float(self.Portfolio.Cash),
                "total_portfolio_value": float(self.Portfolio.TotalPortfolioValue),
                "holdings_value": float(self.Portfolio.TotalPortfolioValue - self.Portfolio.Cash),
                "invested_positions": len([position for position in self.Portfolio.Values if position.Invested]),
            }

        snapshot = self._simulated_portfolio.snapshot(consume_realized_pnl=False)
        return {
            "cash": float(snapshot["cash"]),
            "total_portfolio_value": float(snapshot["total_value"]),
            "holdings_value": float(snapshot["holdings_value"]),
            "invested_positions": len(self._simulated_portfolio.holdings),
        }

    def _snapshot_positions(self) -> list[dict]:
        orders_allowed, _ = self._order_permission()
        if orders_allowed:
            positions = []
            for security_holding in self.Portfolio.Values:
                if not security_holding.Invested:
                    continue

                positions.append(
                    {
                        "symbol": str(security_holding.Symbol),
                        "quantity": float(security_holding.Quantity),
                        "average_price": float(security_holding.AveragePrice),
                        "unrealized_profit": float(security_holding.UnrealizedProfit),
                        "market_value": float(security_holding.HoldingsValue),
                        "weight": float(security_holding.HoldingsValue / max(self.Portfolio.TotalPortfolioValue, 1.0)),
                    }
                )
            return positions

        equity = max(float(self._simulated_portfolio.snapshot(consume_realized_pnl=False)["total_value"]), 1.0)
        positions = []
        for symbol_key, holding in self._simulated_portfolio.holdings.items():
            market_value = self._simulated_portfolio.position_value(symbol_key)
            positions.append(
                {
                    "symbol": symbol_key,
                    "quantity": float(holding["quantity"]),
                    "average_price": float(holding["avg_price"]),
                    "unrealized_profit": float(market_value - holding["quantity"] * holding["avg_price"]),
                    "market_value": float(market_value),
                    "weight": float(market_value / equity),
                }
            )
        return positions

    def _build_regime_summary(self, signals: dict) -> dict:
        regime_payloads = [
            payload.get("regime", {})
            for payload in signals.values()
            if payload.get("regime")
        ]

        def count_by(key: str) -> dict:
            counts = {}
            for regime_payload in regime_payloads:
                value = regime_payload.get(key, "unknown")
                counts[value] = counts.get(value, 0) + 1
            return counts

        def dominant(counts: dict) -> str:
            if not counts:
                return "unknown"
            return max(sorted(counts), key=lambda value: counts[value])

        primary_counts = count_by("primary_regime")
        trend_counts = count_by("trend_regime")
        volatility_counts = count_by("volatility_regime")
        risk_counts = count_by("risk_regime")

        average_confidence = (
            sum(float(payload.get("confidence", 0.0) or 0.0) for payload in regime_payloads) / len(regime_payloads)
            if regime_payloads else 0.0
        )
        risk_off_assets = [
            symbol
            for symbol, payload in signals.items()
            if payload.get("regime", {}).get("risk_regime") == "risk_off"
        ]

        return {
            "asset_count": len(regime_payloads),
            "dominant_primary_regime": dominant(primary_counts),
            "dominant_trend_regime": dominant(trend_counts),
            "dominant_volatility_regime": dominant(volatility_counts),
            "dominant_risk_regime": dominant(risk_counts),
            "average_confidence": average_confidence,
            "risk_off_assets": risk_off_assets,
            "counts": {
                "primary": primary_counts,
                "trend": trend_counts,
                "volatility": volatility_counts,
                "risk": risk_counts,
            },
        }

    def _build_observation_view(self) -> dict:
        summary = compute_observation_summary(list(self._observation_event_log))
        snapshot = self._simulated_portfolio.snapshot(consume_realized_pnl=False)
        summary.update(
            {
                "mode": self.runtime_mode,
                "allow_live_orders": self.allow_live_orders,
                "is_observation_mode": self.runtime_mode == "observation",
                "visually_distinct_banner": "SIMULATED - NOT REAL TRADES",
                "simulated_equity": snapshot["total_value"],
                "simulated_cash": snapshot["cash"],
                "simulated_drawdown": snapshot["current_drawdown"],
                "simulated_exposure": snapshot["exposure"],
                "simulated_turnover": snapshot["turnover_to_date"],
            }
        )
        return summary

    def _build_performance_triggers_view(self) -> dict:
        # In-run, in-memory view only - NOT the durable trigger history. The
        # performance_triggers Postgres table (system of record for
        # Grafana/Phase 17) is populated exclusively by
        # performance/trigger_worker.py, running as its own process/service,
        # never from inside this Lean algorithm.
        report = evaluate_all_triggers(list(self._observation_event_log), self._performance_triggers_config)
        report["source"] = "in_memory_current_run"
        return report

    def _flush_observation_equity_csv(self) -> None:
        """Append-only flush: writes only the equity_curve entries produced
        since the last flush (plus a header on the very first flush), instead
        of rebuilding the full CSV from the entire in-memory list every bar."""
        equity_curve = self._simulated_portfolio.equity_curve
        new_points = equity_curve[self._equity_curve_flushed_count :]
        is_first_flush = self._equity_curve_flushed_count == 0
        if not new_points and not is_first_flush:
            return

        lines = []
        if is_first_flush:
            lines.append("bar_index,equity,cash,exposure,drawdown")
        for point in new_points:
            lines.append(
                ",".join(
                    [
                        str(point.get("bar_index", "")),
                        f"{float(point['equity']):.6f}",
                        f"{float(point['cash']):.6f}",
                        f"{float(point['exposure']):.6f}",
                        f"{float(point['drawdown']):.6f}",
                    ]
                )
            )
        if not lines:
            return

        mode = "w" if is_first_flush else "a"
        with self.observation_equity_curve_path.open(mode, encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self._equity_curve_flushed_count = len(equity_curve)

    def _build_dashboard_view(self, state: dict) -> dict:
        total_portfolio_value = float(state["portfolio"]["total_portfolio_value"])
        asset_heatmap = []
        for symbol, payload in sorted(state["signals"].items()):
            probability_up = payload.get("probability_up")
            confidence = float(payload.get("confidence", 0.0) or 0.0)
            daily_return = float(payload.get("features", {}).get("close_to_close_return_1d", 0.0) or 0.0)
            dynamic_sizing = payload.get("dynamic_sizing", {})
            regime = payload.get("regime", {})
            gating = payload.get("moe_gating", {})
            asset_heatmap.append(
                {
                    "symbol": symbol,
                    "ticker": payload.get("ticker", symbol),
                    "quality_tier": payload.get("asset_quality", {}).get("quality_tier", "unknown"),
                    "role": payload.get("asset_quality", {}).get("role", "unknown"),
                    "trading_eligible": bool(payload.get("trading_eligible", False)),
                    "signal": payload.get("signal", "hold"),
                    "confidence": confidence,
                    "probability_up": probability_up,
                    "baseline_probability_up": payload.get("baseline_probability_up"),
                    "expert_probability_up": gating.get("expert_probability_up"),
                    "predicted_return_magnitude": payload.get("predicted_return_magnitude"),
                    "predicted_volatility": payload.get("predicted_volatility"),
                    "gating_source": gating.get("decision_source", "baseline"),
                    "active_experts": "|".join(gating.get("active_experts", [])),
                    "daily_return": daily_return,
                    "rolling_volatility": float(dynamic_sizing.get("rolling_volatility", 0.0) or 0.0),
                    "annualized_volatility": float(dynamic_sizing.get("annualized_volatility", 0.0) or 0.0),
                    "volatility_regime": dynamic_sizing.get("volatility_regime", "unknown"),
                    "primary_regime": regime.get("primary_regime", "unknown"),
                    "trend_regime": regime.get("trend_regime", "unknown"),
                    "risk_regime": regime.get("risk_regime", "unknown"),
                    "regime_confidence": float(regime.get("confidence", 0.0) or 0.0),
                    "base_target_weight": float(payload.get("base_target_weight", 0.0) or 0.0),
                    "target_weight": float(payload.get("target_weight", 0.0) or 0.0),
                    "leverage_factor": float(dynamic_sizing.get("leverage_factor", 0.0) or 0.0),
                    "execution_note": payload.get("execution_note") or payload.get("reason") or "waiting",
                }
            )

        return {
            "scorecards": [
                {"key": "portfolio_value", "label": "Portfolio Value", "value": total_portfolio_value, "format": "currency"},
                {"key": "cash", "label": "Cash", "value": float(state["portfolio"]["cash"]), "format": "currency"},
                {"key": "daily_drawdown", "label": "Daily Drawdown", "value": float(state["risk"]["daily_drawdown"]), "format": "percent"},
                {"key": "total_drawdown", "label": "Total Drawdown", "value": float(state["risk"]["total_drawdown"]), "format": "percent"},
                {"key": "threshold", "label": "Decision Threshold", "value": float(state["model"]["decision_threshold"]), "format": "number"},
            ],
            "asset_heatmap": asset_heatmap,
            "risk_band": {
                "trade_lock_active": state["risk"]["trade_lock_active"],
                "trade_lock_reason": state["risk"]["trade_lock_reason"],
                "min_confidence_to_trade": state["risk"]["min_confidence_to_trade"],
                "max_position_weight": state["risk"]["max_position_weight"],
                "max_active_positions": state["risk"]["max_active_positions"],
                "max_equity_exposure": state["risk"]["max_equity_exposure"],
                "max_crypto_exposure": state["risk"]["max_crypto_exposure"],
                "target_daily_volatility": state["risk"]["target_daily_volatility"],
                "max_leverage": state["risk"]["max_leverage"],
            },
            "visualization_stage": "v2_dynamic_risk_runtime",
            "runtime_mode": self.runtime_mode,
            "simulated_mode": self.runtime_mode == "observation",
        }

    def _build_monitoring_view(self, state: dict) -> dict:
        signals = list(state["signals"].values())
        active_signals = [payload for payload in signals if payload.get("signal") in {"buy", "sell"}]
        moe_payloads = [payload.get("moe_gating", {}) for payload in signals if payload.get("moe_gating")]
        average_confidence = (
            sum(float(payload.get("confidence", 0.0) or 0.0) for payload in signals) / len(signals)
            if signals else 0.0
        )
        average_moe_probability = (
            sum(float(payload.get("probability_up", 0.0) or 0.0) for payload in signals) / len(signals)
            if signals else 0.0
        )
        average_annualized_volatility = (
            sum(float(payload.get("dynamic_sizing", {}).get("annualized_volatility", 0.0) or 0.0) for payload in signals) / len(signals)
            if signals else 0.0
        )
        max_leverage_factor = max(
            [float(payload.get("dynamic_sizing", {}).get("leverage_factor", 0.0) or 0.0) for payload in signals],
            default=0.0,
        )
        return {
            "project": state["project"],
            "phase": "v2_gating_network",
            "mode": state["mode"],
            "updated_at": state["updated_at"],
            "portfolio_value": float(state["portfolio"]["total_portfolio_value"]),
            "cash": float(state["portfolio"]["cash"]),
            "holdings_value": float(state["portfolio"]["holdings_value"]),
            "invested_positions": int(state["portfolio"]["invested_positions"]),
            "active_signals": len(active_signals),
            "average_confidence": average_confidence,
            "average_moe_probability": average_moe_probability,
            "average_annualized_volatility": average_annualized_volatility,
            "max_leverage_factor": max_leverage_factor,
            "daily_drawdown": float(state["risk"]["daily_drawdown"]),
            "total_drawdown": float(state["risk"]["total_drawdown"]),
            "trade_lock_active": bool(state["risk"]["trade_lock_active"]),
            "dominant_primary_regime": state["regime"]["dominant_primary_regime"],
            "dominant_risk_regime": state["regime"]["dominant_risk_regime"],
            "risk_off_asset_count": len(state["regime"]["risk_off_assets"]),
            "moe_decision_sources": "|".join(sorted({payload.get("decision_source", "unknown") for payload in moe_payloads})),
            "moe_active_experts": "|".join(sorted({expert for payload in moe_payloads for expert in payload.get("active_experts", [])})),
            "trading_eligible_assets": "|".join(state["universe"].get("trading_eligible_assets", [])),
            "observation_only_assets": "|".join(state["universe"].get("observation_only_assets", [])),
            "runtime_mode": self.runtime_mode,
            "allow_live_orders": self.allow_live_orders,
            "observation_active": self.runtime_mode == "observation",
            "feeds": {
                "state": "visualization/state.json",
                "scene": "visualization/scene.json",
                "runtime_metrics": "visualization/grafana/runtime_metrics_snapshot.json",
                "runtime_assets": "visualization/grafana/runtime_asset_metrics.csv",
                "observation_summary": "visualization/grafana/observation_summary.json",
                "observation_equity_curve": "visualization/grafana/observation_equity_curve.csv",
                "performance_triggers": "visualization/grafana/performance_triggers.json",
            },
        }

    def _build_scene_payload(self, state: dict) -> dict:
        positions_by_symbol = {position["symbol"]: position for position in state["positions"]}
        topology = state.get("topology") or {}
        topology_ready = topology.get("state") == "ready"
        topology_nodes_by_symbol = {node["symbol"]: node for node in topology.get("nodes", [])}

        nodes = [
            {
                "id": "portfolio_core",
                "label": "Portfolio Core",
                "kind": "portfolio",
                "x": 50,
                "y": 52,
                "z": 0.95,
                "intensity": 0.84,
                "value": float(state["portfolio"]["total_portfolio_value"]),
                "detail": state["mode"],
            }
        ]
        links = []
        signal_items = sorted(state["signals"].items())
        asset_count = max(len(signal_items), 1)
        for index, (symbol, payload) in enumerate(signal_items):
            ticker = payload.get("ticker", symbol)
            topology_node = topology_nodes_by_symbol.get(symbol)
            if topology_ready and topology_node is not None:
                x = topology_node["x"]
                y = topology_node["y"]
                z = topology_node["z"]
            else:
                angle = (2 * math.pi * index) / asset_count
                x = 50 + math.cos(angle) * 32
                y = 50 + math.sin(angle) * 22
                z = 0.45 + ((index % 4) * 0.12)
            confidence = float(payload.get("confidence", 0.0) or 0.0)
            target_weight = abs(float(payload.get("target_weight", 0.0) or 0.0))
            nodes.append(
                {
                    "id": symbol,
                    "label": ticker,
                    "kind": "asset",
                    "x": x,
                    "y": y,
                    "z": z,
                    "intensity": max(0.18, min(0.98, 0.35 + confidence)),
                    "value": float(payload.get("close", 0.0) or 0.0),
                    "detail": payload.get("signal", "hold"),
                }
            )
            links.append(
                {
                    "source": "portfolio_core",
                    "target": symbol,
                    "strength": max(target_weight, positions_by_symbol.get(symbol, {}).get("weight", 0.0)),
                }
            )

        if topology_ready:
            for link in topology.get("links", []):
                links.append(
                    {
                        "source": link["source"],
                        "target": link["target"],
                        "strength": link["correlation"],
                    }
                )

        return {
            "layout": "market_topology" if topology_ready else "runtime_asset_orbit",
            "nodes": nodes,
            "links": links,
            "dimensions": {"width": 100, "height": 100, "depth": 1},
        }

    def _build_runtime_asset_csv(self, state: dict) -> str:
        rows = [
            "symbol,ticker,quality_tier,role,trading_eligible,signal,confidence,probability_up,baseline_probability_up,expert_probability_up,predicted_return_magnitude,predicted_volatility,gating_source,active_experts,base_target_weight,target_weight,rolling_volatility,annualized_volatility,volatility_regime,volatility_source,primary_regime,trend_regime,risk_regime,regime_confidence,leverage_factor,close,daily_return,position_weight,execution_note"
        ]
        positions_by_symbol = {position["symbol"]: position for position in state["positions"]}
        for symbol, payload in sorted(state["signals"].items()):
            position_weight = positions_by_symbol.get(symbol, {}).get("weight", 0.0)
            dynamic_sizing = payload.get("dynamic_sizing", {})
            regime = payload.get("regime", {})
            gating = payload.get("moe_gating", {})
            rows.append(
                ",".join(
                    [
                        str(symbol),
                        str(payload.get("ticker", symbol)),
                        str(payload.get("asset_quality", {}).get("quality_tier", "unknown")),
                        str(payload.get("asset_quality", {}).get("role", "unknown")),
                        str(bool(payload.get("trading_eligible", False))).lower(),
                        str(payload.get("signal", "hold")),
                        f"{float(payload.get('confidence', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('probability_up', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('baseline_probability_up', 0.0) or 0.0):.6f}",
                        f"{float(gating.get('expert_probability_up', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('predicted_return_magnitude', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('predicted_volatility', 0.0) or 0.0):.6f}",
                        str(gating.get("decision_source", "baseline")),
                        "|".join(gating.get("active_experts", [])),
                        f"{float(payload.get('base_target_weight', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('target_weight', 0.0) or 0.0):.6f}",
                        f"{float(dynamic_sizing.get('rolling_volatility', 0.0) or 0.0):.6f}",
                        f"{float(dynamic_sizing.get('annualized_volatility', 0.0) or 0.0):.6f}",
                        str(dynamic_sizing.get("volatility_regime", "unknown")),
                        str(dynamic_sizing.get("volatility_source", "rolling")),
                        str(regime.get("primary_regime", "unknown")),
                        str(regime.get("trend_regime", "unknown")),
                        str(regime.get("risk_regime", "unknown")),
                        f"{float(regime.get('confidence', 0.0) or 0.0):.6f}",
                        f"{float(dynamic_sizing.get('leverage_factor', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('close', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('features', {}).get('close_to_close_return_1d', 0.0) or 0.0):.6f}",
                        f"{float(position_weight):.6f}",
                        str(payload.get("execution_note") or payload.get("reason") or "waiting"),
                    ]
                )
            )
        return "\n".join(rows) + "\n"

    def _standard_deviation(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0

        mean_value = sum(values) / len(values)
        variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
        return math.sqrt(max(variance, 0.0))

    def _clamp_volume_change(self, raw_volume_change: float) -> float:
        """Mirrors train.py::engineer_features()'s identical clamp - a
        >2000% single-day volume jump (e.g. BTCUSD's 2018-08-14 data-feed
        unit discontinuity, see development/Problems.md) is a data-source
        artifact, not a real signal, and left unclamped it turns into a
        tens-of-thousands-of-sigma scaled feature."""
        return max(VOLUME_CHANGE_FLOOR, min(VOLUME_CHANGE_CEILING, raw_volume_change))
