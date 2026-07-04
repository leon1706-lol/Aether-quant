"""
Lean algorithm for Aether Quant.

Phase 4 adds the first end-to-end inference loop:
- load the exported model JSON and scaler
- recreate the training features inside Lean
- run a forward pass locally from the exported architecture
- emit simple buy/sell/hold signals and conservative target weights
- keep the dashboard state updated with probabilities and feature readiness
"""

import json
import math
from collections import deque
from datetime import datetime
from pathlib import Path

from AlgorithmImports import *
from risk_controls import (
    active_position_limit_reached,
    assess_drawdown_lock,
    cap_target_weight,
)
from analyzer import build_market_analysis_decision
from moe import EXPERT_NAMES, build_gating_decision
from regime import build_market_regime_vector
from risk.manual_override import read_manual_trade_lock_override
from risk.position_sizing import build_dynamic_position_sizing
from liquidity import build_liquidity_decision, estimate_high_low_spread
from topology import apply_learned_topology, build_market_topology, liquidity_score_from_decision
from experience import (
    ExperienceQueue,
    SimulatedPortfolioState,
    build_experience_event,
    build_session_summary_event,
    compute_observation_summary,
)
from execution import resolve_order_permission, resolve_runtime_mode
from performance import evaluate_all_triggers


class AetherQuantAlgorithm(QCAlgorithm):
    """Lean algorithm with JSON-model inference and a basic signal engine."""

    def initialize(self) -> None:
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

        self._validate_runtime_artifacts()
        self.config = self._load_json(self.root_path / "config.json")
        self.phase1 = self.config["phase1"]
        self.phase3 = self.config["phase3"]
        self.phase5 = self.config.get("phase5", {})
        self.phase6 = self.config.get("phase6", {})
        self.phase9 = self.config.get("phase9", {})
        self.phase_v2 = self.config.get("phase_v2", {})
        self.runtime = self.config["runtime"]
        self.model_export = self._load_json(self.model_path)
        self.expert_training_metrics = self._load_json(self.expert_metrics_path) if self.expert_metrics_path.exists() else {}
        self.expert_model_exports = self._load_expert_model_exports()
        self.feature_schema = self._load_json(self.feature_schema_path)
        self.scaler_stats = self._load_json(self.scaler_stats_path)
        self.dataset_manifest = self._load_json(self.dataset_manifest_path) if self.dataset_manifest_path.exists() else {}

        self.base_feature_names = list(self.feature_schema["feature_names"])
        self.scaled_feature_names = list(self.feature_schema["scaled_feature_names"])
        self.context_feature_names = list(self.feature_schema.get("context_feature_names", []))
        self.model_input_names = list(self.feature_schema.get("model_input_names", self.scaled_feature_names))

        phase5_backtest = self.phase5.get("backtest", {})
        phase6_risk = self.phase6.get("risk", {})
        phase6_paper = self.phase6.get("paper_trading", {})
        phase9_portfolio = self.phase9.get("portfolio", {})
        phase_v2_risk = self.phase_v2.get("dynamic_risk", {})
        phase_v2_regime = self.phase_v2.get("regime_detection", {})
        phase_v2_gating = self.phase_v2.get("gating_network", {})
        phase_v2_analyzer = self.phase_v2.get("market_analyzer", {})
        phase_v2_topology = self.phase_v2.get("topology", {})

        self.decision_threshold = float(self.model_export["training"]["decision_threshold"])
        self.buy_threshold = min(0.75, self.decision_threshold + float(phase5_backtest.get("buy_threshold_offset", 0.08)))
        self.sell_threshold = max(0.25, self.decision_threshold - float(phase5_backtest.get("sell_threshold_offset", 0.08)))
        self.max_position_weight = float(phase6_risk.get("max_position_weight", 0.25))
        self.min_confidence_to_trade = float(phase6_risk.get("min_confidence_to_trade", 0.12))
        self.trade_cooldown_bars = int(phase6_risk.get("trade_cooldown_bars", 3))
        self.max_daily_drawdown_pct = float(phase6_risk.get("max_daily_drawdown_pct", 0.03))
        self.max_total_drawdown_pct = float(phase6_risk.get("max_total_drawdown_pct", 0.12))
        self.liquidate_on_risk_breach = bool(phase6_risk.get("liquidate_on_risk_breach", True))
        self.paper_brokerage = str(phase6_paper.get("brokerage", "interactive_brokers_paper"))
        self.ready_for_live_paper = bool(phase6_paper.get("ready_for_live_paper", False))
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
        self.target_daily_volatility = float(phase_v2_risk.get("target_daily_volatility", 0.015))
        self.low_volatility_threshold = float(phase_v2_risk.get("low_volatility_threshold", 0.01))
        self.high_volatility_threshold = float(phase_v2_risk.get("high_volatility_threshold", 0.03))
        self.min_volatility_multiplier = float(phase_v2_risk.get("min_volatility_multiplier", 0.35))
        self.max_volatility_multiplier = float(phase_v2_risk.get("max_volatility_multiplier", 1.25))
        self.min_dynamic_position_weight = float(phase_v2_risk.get("min_position_weight", 0.0))
        self.max_leverage = float(phase_v2_risk.get("max_leverage", 1.0))
        self.regime_bullish_threshold = float(phase_v2_regime.get("bullish_threshold", 0.02))
        self.regime_bearish_threshold = float(phase_v2_regime.get("bearish_threshold", -0.02))
        self.regime_risk_off_drawdown_threshold = float(phase_v2_regime.get("risk_off_drawdown_threshold", 0.08))
        self.regime_risk_on_drawdown_threshold = float(phase_v2_regime.get("risk_on_drawdown_threshold", 0.03))
        self.regime_high_correlation_threshold = float(phase_v2_regime.get("high_correlation_threshold", 0.75))
        self.gating_baseline_weight = float(phase_v2_gating.get("baseline_weight", 0.25))
        self.analyzer_retrain_min_regime_confidence = float(phase_v2_analyzer.get("retrain_min_regime_confidence", 0.20))
        self.analyzer_low_regime_confidence_threshold = float(phase_v2_analyzer.get("low_regime_confidence_threshold", 0.35))
        self.topology_correlation_threshold = float(phase_v2_topology.get("correlation_threshold", 0.6))
        self.topology_link_threshold = float(phase_v2_topology.get("link_threshold", 0.5))
        self.topology_min_observations = int(phase_v2_topology.get("min_observations", 5))
        self.topology_embedding_iterations = int(phase_v2_topology.get("embedding_iterations", 100))
        phase_v2_topology_learning = self.phase_v2.get("topology_learning", {})
        self.topology_learning_enabled = bool(phase_v2_topology_learning.get("enabled", True))
        self.topology_learning_temperature = float(phase_v2_topology_learning.get("temperature", 0.35))
        self.topology_learning_top_n_neighbors = int(phase_v2_topology_learning.get("top_n_neighbors", 3))
        self.topology_learning_min_confidence = float(phase_v2_topology_learning.get("min_confidence_for_learned", 0.2))
        self.topology_learning_max_offset_xy = float(phase_v2_topology_learning.get("max_offset_xy", 6.0))
        self.topology_learning_max_offset_z = float(phase_v2_topology_learning.get("max_offset_z", 0.1))
        self.learned_topology_model, self.learned_topology_feature_schema = self._load_learned_topology_model()
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
        phase_v2_experience = self.phase_v2.get("experience", {})
        phase_v2_runtime = self.phase_v2.get("runtime", {})
        raw_runtime_mode = phase_v2_runtime.get("mode")
        self.runtime_mode = resolve_runtime_mode(raw_runtime_mode)
        if self.runtime_mode != raw_runtime_mode:
            self.Debug(f"Unknown phase_v2.runtime.mode={raw_runtime_mode!r}; falling back to '{self.runtime_mode}'")
        self.allow_live_orders = bool(phase_v2_runtime.get("allow_live_orders", False))
        self._experience_mode = self.runtime_mode
        self._experience_queue = ExperienceQueue(
            enabled=bool(phase_v2_experience.get("enabled", False)),
            redis_url="redis://localhost:6380/0",
            stream_name=str(phase_v2_experience.get("redis_stream", "aether:experience")),
            maxlen=int(phase_v2_experience.get("maxlen", 100_000)),
        )
        self._simulated_portfolio = SimulatedPortfolioState(initial_cash=float(self.runtime["initial_cash"]))
        self._observation_event_log = deque(maxlen=5000)
        self._session_events: list[dict] = []
        self._performance_triggers_config = self.phase_v2.get("performance_triggers", {})
        self.bar_history_size = 25

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
        self.latest_signal_state = {}
        self.last_trade_bar_by_symbol = {}
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

        for asset in self.phase1["universe"]["assets"]:
            symbol = self._add_asset(asset)
            if symbol is None:
                continue

            ticker = asset["ticker"]
            self.symbols.append(symbol)
            self.asset_lookup[str(symbol)] = asset
            self.ticker_to_symbol[ticker] = symbol
            self.symbol_windows[symbol] = deque(maxlen=self.bar_history_size)
            self.latest_signal_state[str(symbol)] = "hold"
            self.last_trade_bar_by_symbol[symbol] = -1000000
            self.securities[symbol].fee_model = InteractiveBrokersFeeModel()

        self.set_warm_up(max(int(self.runtime["warmup_bars"]), 21), self.resolution)
        self._write_state(mode="initialize", insight="Phase 4 inference engine initialized")

    def on_data(self, slice: Slice) -> None:
        if len(slice.Bars) == 0:
            return

        self.bar_index += 1
        self._refresh_risk_state()
        self.latest_topology_payload = self._build_topology_payload()
        topology_by_symbol = {node["symbol"]: node for node in self.latest_topology_payload.get("nodes", [])}
        signals = {}

        for symbol in self.symbols:
            bar = slice.bars.get(symbol)
            if bar is None:
                continue

            self.symbol_windows[symbol].append(
                {
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
            )

            feature_payload = self._build_model_input(symbol)
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

            if feature_payload["ready"] and not self.is_warming_up:
                baseline_probability_up = self._run_model(feature_payload["model_inputs"])
                topology_payload = topology_by_symbol.get(str(symbol))
                regime_payload = self._build_regime_payload(
                    feature_payload["base_features"],
                    average_correlation=float((topology_payload or {}).get("correlation_strength", 0.0)),
                )
                expert_probabilities = self._run_expert_models(feature_payload["model_inputs"])
                gating_payload = build_gating_decision(
                    regime=regime_payload,
                    expert_training_metrics=self.expert_training_metrics,
                    expert_probabilities=expert_probabilities,
                    baseline_probability_up=baseline_probability_up,
                    baseline_weight=self.gating_baseline_weight,
                ).to_dict()
                probability_up = float(gating_payload["final_probability_up"])
                signal_name, confidence, base_target_weight = self._derive_signal(probability_up)
                sizing_payload = self._build_dynamic_sizing_payload(
                    signal_name,
                    confidence,
                    base_target_weight,
                    feature_payload["base_features"],
                )
                target_weight = float(sizing_payload["target_weight"])
                asset = self.asset_lookup[str(symbol)]
                dynamic_spread = None
                if self._spread_estimation_enabled:
                    symbol_bars = list(self.symbol_windows[symbol])
                    if len(symbol_bars) >= self._spread_estimation_min_bars:
                        dynamic_spread = estimate_high_low_spread(
                            [bar_data["high"] for bar_data in symbol_bars],
                            [bar_data["low"] for bar_data in symbol_bars],
                        )
                liquidity_payload = build_liquidity_decision(
                    close=float(bar.close),
                    volume=float(bar.volume),
                    target_weight=target_weight,
                    portfolio_value=float(self.Portfolio.TotalPortfolioValue),
                    annualized_volatility=float(sizing_payload.get("annualized_volatility", 0.0)),
                    security_type=str(asset.get("security_type", "equity")),
                    dynamic_spread=dynamic_spread,
                    **self._liquidity_thresholds,
                ).to_dict()
                if liquidity_payload["recommended_action"] == "reduce_size":
                    target_weight = float(liquidity_payload["adjusted_target_weight"])

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
                ).to_dict()

                signal_name = decision["signal"]
                target_weight = decision["target_weight"]
                close_price = float(bar.close)

                if decision["action"] == "trade":
                    execution_note = self._apply_signal(symbol, signal_name, target_weight, close_price)
                else:
                    execution_note = decision["action"]

                self._simulated_portfolio.mark_to_market({str(symbol): close_price}, bar_index=self.bar_index)

                self.latest_regime_by_symbol[str(symbol)] = regime_payload.get("trend_regime", "unknown")
                self.latest_regime_risk_score_by_symbol[str(symbol)] = float(regime_payload.get("risk_score", 0.0) or 0.0)
                self.latest_liquidity_by_symbol[str(symbol)] = liquidity_payload

                signal_payload.update(
                    {
                        "signal": signal_name,
                        "confidence": confidence,
                        "probability_up": probability_up,
                        "baseline_probability_up": baseline_probability_up,
                        "expert_probabilities": expert_probabilities,
                        "moe_gating": gating_payload,
                        "base_target_weight": base_target_weight,
                        "target_weight": target_weight,
                        "dynamic_sizing": sizing_payload,
                        "regime": regime_payload,
                        "features": feature_payload["base_features"],
                        "execution_note": execution_note,
                        "market_analysis": decision,
                        "topology": topology_payload or {},
                        "liquidity": liquidity_payload,
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
                    symbol=str(symbol),
                    ticker=self.asset_lookup[str(symbol)]["ticker"],
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
                )
                self._experience_queue.push(experience_event)
                self._observation_event_log.append(experience_event)
                self._session_events.append(experience_event)
            else:
                signal_payload["reason"] = feature_payload["reason"]

            signals[str(symbol)] = signal_payload

        if signals:
            insight = "Phase 4 model inference active" if not self.is_warming_up else "Warming up feature history"
            self._write_state(mode="runtime", insight=insight, signals=signals)

    def on_end_of_algorithm(self) -> None:
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
                except Exception as error:
                    self.Debug(f"Expert export load failed for {expert_name}: {error}")
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
                return security.symbol
            if security_type == "crypto":
                market = Market.COINBASE if asset["market"].lower() == "coinbase" else asset["market"].upper()
                security = self.add_crypto(ticker, self.resolution, market)
                return security.symbol

            self.debug(f"Unsupported asset type skipped: {security_type} {ticker}")
            return None
        except Exception as error:
            self.debug(f"{ticker} subscription skipped: {error}")
            return None

    def _build_model_input(self, symbol) -> dict:
        bars = list(self.symbol_windows[symbol])
        if len(bars) < 2:
            return {"ready": False, "reason": f"Need 2 bars, have {len(bars)}"}

        closes = [bar["close"] for bar in bars]
        volumes = [bar["volume"] for bar in bars]
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
            "volume_change_1d": 0.0 if previous_volume == 0 else current["volume"] / previous_volume - 1.0,
        }

        scaled_features = {}
        for index, base_name in enumerate(self.base_feature_names):
            scaled_name = self.scaled_feature_names[index]
            mean_value = float(self.scaler_stats["mean"][index])
            scale_value = float(self.scaler_stats["scale"][index]) if float(self.scaler_stats["scale"][index]) != 0 else 1.0
            scaled_features[scaled_name] = (base_features[base_name] - mean_value) / scale_value

        context_values = {feature_name: 0.0 for feature_name in self.context_feature_names}
        asset = self.asset_lookup[str(symbol)]
        ticker_key = f"asset_{asset['ticker']}"
        if ticker_key in context_values:
            context_values[ticker_key] = 1.0

        model_inputs = []
        for feature_name in self.model_input_names:
            if feature_name in scaled_features:
                model_inputs.append(float(scaled_features[feature_name]))
            else:
                model_inputs.append(float(context_values.get(feature_name, 0.0)))

        return {
            "ready": True,
            "reason": "ok",
            "base_features": base_features,
            "scaled_features": scaled_features,
            "context_features": context_values,
            "model_inputs": model_inputs,
        }

    def _run_exported_model(self, model_export: dict, inputs: list[float]) -> float:
        current = list(inputs)
        for layer in model_export["export"]["architecture"]:
            layer_type = layer["type"]
            if layer_type == "linear":
                weights = model_export["export"]["state_dict"][layer["weight_key"]]
                bias = model_export["export"]["state_dict"][layer["bias_key"]]
                current = self._linear(current, weights, bias)
            elif layer_type == "layernorm":
                weights = model_export["export"]["state_dict"][layer["weight_key"]]
                bias = model_export["export"]["state_dict"][layer["bias_key"]]
                current = self._layernorm(current, weights, bias, float(layer.get("eps", 1e-5)))
            elif layer_type == "relu":
                current = [max(0.0, value) for value in current]
            elif layer_type == "dropout":
                continue
            elif layer_type == "sigmoid":
                current = [self._sigmoid(value) for value in current]
            else:
                raise ValueError(f"Unsupported layer type in export: {layer_type}")

        return float(current[0])

    def _run_model(self, inputs: list[float]) -> float:
        return self._run_exported_model(self.model_export, inputs)

    def _run_expert_models(self, inputs: list[float]) -> dict:
        probabilities = {}
        for expert_name in EXPERT_NAMES:
            model_export = self.expert_model_exports.get(expert_name)
            if not model_export:
                probabilities[expert_name] = None
                continue
            try:
                probabilities[expert_name] = self._run_exported_model(model_export, inputs)
            except Exception as error:
                probabilities[expert_name] = None
                self.Debug(f"Expert inference failed for {expert_name}: {error}")
        return probabilities

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
    ) -> dict:
        if signal_name not in {"buy", "sell"}:
            base_target_weight = 0.0

        decision = build_dynamic_position_sizing(
            base_target_weight=base_target_weight,
            confidence=confidence,
            rolling_volatility=float(base_features.get("rolling_volatility_20d", 0.0) or 0.0),
            max_position_weight=self.max_position_weight,
            target_daily_volatility=self.target_daily_volatility,
            min_position_weight=self.min_dynamic_position_weight,
            low_volatility_threshold=self.low_volatility_threshold,
            high_volatility_threshold=self.high_volatility_threshold,
            min_volatility_multiplier=self.min_volatility_multiplier,
            max_volatility_multiplier=self.max_volatility_multiplier,
            max_leverage=self.max_leverage,
        )
        return decision.to_dict()

    def _build_topology_payload(self) -> dict:
        returns_by_symbol = {}
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

        deterministic_topology = build_market_topology(
            returns_by_symbol=returns_by_symbol,
            regime_labels_by_symbol=dict(self.latest_regime_by_symbol),
            correlation_threshold=self.topology_correlation_threshold,
            link_threshold=self.topology_link_threshold,
            min_observations=self.topology_min_observations,
            embedding_iterations=self.topology_embedding_iterations,
        ).to_dict()

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

    def _build_regime_payload(self, base_features: dict, average_correlation: float = 0.0) -> dict:
        vector = build_market_regime_vector(
            base_features,
            portfolio_drawdown=self.current_total_drawdown,
            average_correlation=average_correlation,
            bullish_threshold=self.regime_bullish_threshold,
            bearish_threshold=self.regime_bearish_threshold,
            low_volatility_threshold=self.low_volatility_threshold,
            high_volatility_threshold=self.high_volatility_threshold,
            risk_off_drawdown_threshold=self.regime_risk_off_drawdown_threshold,
            risk_on_drawdown_threshold=self.regime_risk_on_drawdown_threshold,
            high_correlation_threshold=self.regime_high_correlation_threshold,
        )
        return vector.to_dict()

    def _order_permission(self) -> tuple[bool, str]:
        return resolve_order_permission(
            mode=self.runtime_mode,
            allow_live_orders=self.allow_live_orders,
            broker_config_present=bool(self.paper_brokerage),
            risk_locks_healthy=not self.trade_lock_active,
        )

    def _is_invested(self, symbol, orders_allowed: bool) -> bool:
        if orders_allowed:
            return bool(self.Portfolio[symbol].Invested)
        return str(symbol) in self._simulated_portfolio.holdings

    def _apply_signal(self, symbol, signal_name: str, target_weight: float, close_price: float) -> str:
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

            exposure_cap = self.max_crypto_exposure if asset.get("security_type") == "crypto" else self.max_equity_exposure
            current_exposure = self._asset_class_exposure(asset.get("security_type"), orders_allowed, exclude_symbol=symbol)
            target_weight, cap_reached = cap_target_weight(target_weight, current_exposure, exposure_cap)
            if cap_reached:
                return f"{asset.get('security_type', 'asset')}_exposure_cap_reached"

            if previous_signal != "buy" or not self._is_invested(symbol, orders_allowed):
                if orders_allowed:
                    self.SetHoldings(symbol, target_weight)
                    self.last_trade_bar_by_symbol[symbol] = self.bar_index
                    return "entered_long"
                self._simulated_portfolio.enter_long(symbol_key, close_price, target_weight, self.bar_index)
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return f"simulated_entered_long:{permission_reason}"
            return "kept_long" if orders_allowed else "simulated_kept_long"

        if signal_name == "sell":
            if self._is_invested(symbol, orders_allowed):
                if orders_allowed:
                    self.Liquidate(symbol)
                else:
                    self._simulated_portfolio.exit(symbol_key, close_price, self.bar_index)
                self.last_trade_bar_by_symbol[symbol] = self.bar_index
                return "liquidated_on_sell" if orders_allowed else f"simulated_liquidated_on_sell:{permission_reason}"
            return "already_flat"

        if signal_name == "hold" and previous_signal != "hold" and self._is_invested(symbol, orders_allowed):
            if orders_allowed:
                self.Liquidate(symbol)
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

    def _asset_class_exposure(self, security_type: str | None, orders_allowed: bool = True, exclude_symbol=None) -> float:
        if orders_allowed:
            total_value = max(float(self.Portfolio.TotalPortfolioValue), 1.0)
            exposure = 0.0
            for holding in self.Portfolio.Values:
                if exclude_symbol is not None and holding.Symbol == exclude_symbol:
                    continue
                asset = self.asset_lookup.get(str(holding.Symbol), {})
                if asset.get("security_type") != security_type:
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
            if asset.get("security_type") != security_type:
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
            if self.trade_lock_reason != "total_drawdown_limit_breached":
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

    def _write_state(self, mode: str, insight: str, signals: dict | None = None) -> None:
        now = self.Time if hasattr(self, "Time") else datetime.utcnow()
        if self.last_state_write == now and signals is None:
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
                },
            },
            "paper_trading": {
                "brokerage": self.paper_brokerage,
                "ready_for_live_paper": self.ready_for_live_paper,
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
            self.observation_equity_curve_path.write_text(self._build_observation_equity_csv(), encoding="utf-8")
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

    def _build_observation_equity_csv(self) -> str:
        rows = ["bar_index,equity,cash,exposure,drawdown"]
        for point in self._simulated_portfolio.equity_curve:
            rows.append(
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
        return "\n".join(rows) + "\n"

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
            "symbol,ticker,quality_tier,role,trading_eligible,signal,confidence,probability_up,baseline_probability_up,expert_probability_up,gating_source,active_experts,base_target_weight,target_weight,rolling_volatility,annualized_volatility,volatility_regime,primary_regime,trend_regime,risk_regime,regime_confidence,leverage_factor,close,daily_return,position_weight,execution_note"
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
                        str(gating.get("decision_source", "baseline")),
                        "|".join(gating.get("active_experts", [])),
                        f"{float(payload.get('base_target_weight', 0.0) or 0.0):.6f}",
                        f"{float(payload.get('target_weight', 0.0) or 0.0):.6f}",
                        f"{float(dynamic_sizing.get('rolling_volatility', 0.0) or 0.0):.6f}",
                        f"{float(dynamic_sizing.get('annualized_volatility', 0.0) or 0.0):.6f}",
                        str(dynamic_sizing.get("volatility_regime", "unknown")),
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

    def _linear(self, inputs: list[float], weights: list[list[float]], bias: list[float]) -> list[float]:
        outputs = []
        for row_index, row_weights in enumerate(weights):
            total = float(bias[row_index])
            for input_value, weight in zip(inputs, row_weights):
                total += float(input_value) * float(weight)
            outputs.append(total)
        return outputs

    def _layernorm(self, values: list[float], weights: list[float], bias: list[float], eps: float) -> list[float]:
        mean_value = sum(values) / len(values)
        variance = sum((value - mean_value) ** 2 for value in values) / len(values)
        denominator = math.sqrt(variance + eps)

        normalized = []
        for index, value in enumerate(values):
            centered = (value - mean_value) / denominator
            normalized.append(centered * float(weights[index]) + float(bias[index]))
        return normalized

    def _sigmoid(self, value: float) -> float:
        clipped = max(min(value, 60.0), -60.0)
        return 1.0 / (1.0 + math.exp(-clipped))

    def _standard_deviation(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0

        mean_value = sum(values) / len(values)
        variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
        return math.sqrt(max(variance, 0.0))
