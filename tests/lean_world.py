"""A synthetic Lean world for `main.py` (V6.6.6, #359): the same algorithm class, run against a stand-in for `AlgorithmImports`, a temporary project root and
synthetic `ml/` artifacts, so a clean checkout (no gitignored `ml/`, `data/`) reaches the same lines a Lean run does.

`main.py` reads its root from `Path(__file__)`, so the world sets the module's `__file__` global to a file in the temporary root. Coverage still attributes the lines
to the repo's own main.py, because it follows the code object's filename, not the global. Nothing here simulates fills or Lean's API semantics (that stays the owner-run
backtest's job); it proves the decisions this repo makes around those APIs are the ones its pure functions promise.
"""

from __future__ import annotations

import copy
import datetime
import functools
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from lean_fakes import FakeLean, FakeOptionStrategies, Market, PermissiveQC, create_option  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
EXPERTS = ("bullish", "bearish", "sideways", "volatility")
FEATURES = [
    "close_to_close_return_1d", "close_to_close_return_5d", "close_to_close_return_20d", "rolling_volatility_5d", "rolling_volatility_20d", "momentum_5d", "momentum_20d",
    "high_low_range_pct", "open_close_range_pct", "volume_change_1d", "rsi_14", "atr_pct_14", "bollinger_pctb_20", "volume_zscore_20", "macd_histogram_norm", "dist_52w_high",
    "regime_signal_confidence", "regime_signal_trend_score", "regime_signal_risk_score", "liquidity_log_dollar_volume", "liquidity_spread_proxy", "topology_correlation_strength",
    "peer_rank1_return_1d", "peer_rank2_return_1d", "peer_rank3_return_1d", "peer_mean_return_1d", "cs_momentum_rank_20", "macro_yield_curve_slope_proxy", "macro_credit_spread_proxy",
    "macro_crypto_risk_appetite_proxy", "bond_yield_curve_level", "bond_yield_curve_slope", "bond_yield_curve_curvature", "bond_credit_spread_level", "bond_empirical_duration_beta",
    "bond_analytic_modified_duration", "bond_analytic_convexity", "bond_dv01", "alt_implied_volatility_level", "alt_implied_vol_term_structure", "alt_financial_conditions_change",
    "sens_vix_beta", "sens_vix_interaction", "sens_real_rate_beta", "sens_real_rate_interaction", "sens_credit_beta", "sens_credit_interaction", "sens_dollar_beta",
    "sens_dollar_interaction", "fx_carry_3m",
]
SCALED = [f"{name}_scaled" for name in FEATURES]
CATEGORICAL = ["regime_trend_bullish", "regime_trend_bearish", "regime_trend_sideways", "regime_volatility_low", "regime_volatility_normal", "regime_volatility_high", "regime_risk_on",
               "regime_risk_off", "regime_risk_neutral", "topology_risk_normal", "topology_risk_elevated", "topology_risk_isolated"]
CONTEXT = ["asset_class_equity", "asset_class_crypto", "asset_class_bond", "asset_class_future", "asset_class_option", "asset_class_forex"]
INPUTS = SCALED + CATEGORICAL + CONTEXT
HEADS = ("direction", "magnitude", "volatility", "direction_5d", "direction_20d", "rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d",
         "beta_neutral_rank_20d")
HIDDEN = 6


def _weights(rng: np.random.Generator, out_features: int, in_features: int, scale: float = 0.2) -> list:
    return (rng.normal(0.0, scale, (out_features, in_features))).round(4).tolist()


def _vector(rng: np.random.Generator, size: int, value: float | None = None) -> list:
    return ([value] * size) if value is not None else rng.normal(0.0, 0.1, size).round(4).tolist()


def mlp_export(seed: int = 0, in_features: int = len(INPUTS), hidden: int = HIDDEN) -> dict:
    rng = np.random.default_rng(seed)
    architecture = [
        {"type": "linear", "weight_key": "network.0.weight", "bias_key": "network.0.bias", "in_features": in_features, "out_features": hidden},
        {"type": "layernorm", "weight_key": "network.1.weight", "bias_key": "network.1.bias", "normalized_shape": [hidden], "eps": 1e-5},
        {"type": "relu"}, {"type": "dropout", "p": 0.15},
        {"type": "linear", "weight_key": "network.4.weight", "bias_key": "network.4.bias", "in_features": hidden, "out_features": 1}, {"type": "sigmoid"},
    ]
    state = {"network.0.weight": _weights(rng, hidden, in_features), "network.0.bias": _vector(rng, hidden), "network.1.weight": _vector(rng, hidden, 1.0), "network.1.bias": _vector(rng, hidden, 0.0),
             "network.4.weight": _weights(rng, 1, hidden), "network.4.bias": _vector(rng, 1)}
    return {"architecture": architecture, "state_dict": state}


def _heads(rng: np.random.Generator, hidden: int) -> tuple[dict, dict]:
    heads, state = {}, {}
    for name in HEADS:
        heads[name] = [{"type": "linear", "weight_key": f"head_{name}.weight", "bias_key": f"head_{name}.bias", "in_features": hidden, "out_features": 1}]
        if name.startswith("direction"):
            heads[name].append({"type": "sigmoid"})
        elif name == "volatility":
            heads[name].append({"type": "softplus"})
        state[f"head_{name}.weight"] = _weights(rng, 1, hidden)
        state[f"head_{name}.bias"] = _vector(rng, 1)
    return heads, state


def multitask_export(seed: int = 1, in_features: int = len(INPUTS), hidden: int = HIDDEN) -> dict:
    rng = np.random.default_rng(seed)
    trunk = [
        {"type": "linear", "weight_key": "trunk.0.weight", "bias_key": "trunk.0.bias", "in_features": in_features, "out_features": hidden},
        {"type": "layernorm", "weight_key": "trunk.1.weight", "bias_key": "trunk.1.bias", "normalized_shape": [hidden], "eps": 1e-5}, {"type": "relu"}, {"type": "dropout", "p": 0.25},
    ]
    heads, head_state = _heads(rng, hidden)
    state = {"trunk.0.weight": _weights(rng, hidden, in_features), "trunk.0.bias": _vector(rng, hidden), "trunk.1.weight": _vector(rng, hidden, 1.0), "trunk.1.bias": _vector(rng, hidden, 0.0), **head_state}
    return {"trunk": trunk, "heads": heads, "state_dict": state}


def sequence_export(seed: int = 2, in_features: int = len(INPUTS), hidden: int = HIDDEN) -> dict:
    rng = np.random.default_rng(seed)
    trunk = [
        {"type": "conv1d_causal", "weight_key": "conv_layers.0.weight", "bias_key": "conv_layers.0.bias", "dilation": 1, "in_channels": in_features, "out_channels": hidden, "kernel_size": 3},
        {"type": "relu"}, {"type": "layernorm_axis", "weight_key": "layer_norms.0.weight", "bias_key": "layer_norms.0.bias", "eps": 1e-5}, {"type": "dropout", "p": 0.25},
    ]
    heads, head_state = _heads(rng, hidden)
    state = {"conv_layers.0.weight": (rng.normal(0.0, 0.1, (hidden, in_features, 3))).round(4).tolist(), "conv_layers.0.bias": _vector(rng, hidden),
             "layer_norms.0.weight": _vector(rng, hidden, 1.0), "layer_norms.0.bias": _vector(rng, hidden, 0.0), **head_state}
    return {"trunk": trunk, "heads": heads, "state_dict": state}


def asset_quality(assets: list[dict], *, observation_only: tuple[str, ...] = ()) -> dict:
    """`ml/feature_schema.json`'s per-asset quality block: every asset a core, trading-eligible name unless it is listed as observation-only."""
    return {
        asset["ticker"]: {"ticker": asset["ticker"], "security_type": asset["security_type"], "market": asset.get("market"), "quality_tier": "core",
                          "role": "observation_only" if asset["ticker"] in observation_only else "model_training_and_trading", "training_eligible": True,
                          "trading_eligible": asset["ticker"] not in observation_only, "available_rows": 2000, "feature_rows": 1990,
                          "split_rows": {"train": 1500, "validation": 200, "backtest": 290}, "date_start": "2014-12-01", "date_end": "2025-06-30", "reason": "synthetic"}
        for asset in assets
    }


def write_ml(root: Path, *, experts: bool = True, multitask: bool = True, sequence: bool = True, window: int = 30, assets: list[dict] | None = None,
             observation_only: tuple[str, ...] = ()) -> None:
    """The artifacts `main.py` loads, with small random weights: the baseline, four regime experts, a multitask and a sequence model."""
    ml = root / "ml"
    ml.mkdir(parents=True, exist_ok=True)
    quality = asset_quality(assets or [], observation_only=observation_only)
    eligible = sorted(ticker for ticker, entry in quality.items() if entry["trading_eligible"])

    def write(name: str, payload: dict) -> None:
        (ml / name).parent.mkdir(parents=True, exist_ok=True)
        (ml / name).write_text(json.dumps(payload), encoding="utf-8")

    model_block = {"type": "robust_mlp_classifier", "input_features": FEATURES, "scaled_input_features": SCALED, "context_input_features": CONTEXT, "model_input_features": INPUTS,
                   "hidden_layers": [HIDDEN], "dropout": 0.15, "activation": "relu", "normalization": "layernorm", "use_asset_context": True, "output_activation": "sigmoid"}
    write("model_weights.json", {"project": "Aether Quant", "status": "trained", "model": model_block, "training": {"decision_threshold": 0.5}, "export": mlp_export(0)})
    write("feature_schema.json", {"feature_names": FEATURES, "scaled_feature_names": SCALED, "categorical_feature_names": CATEGORICAL, "context_feature_names": CONTEXT, "model_input_names": INPUTS,
                                  "target_column": "target_direction", "split_column": "split", "asset_quality": quality, "trading_eligible_assets": eligible})
    write("scaler_stats.json", {"feature_names": FEATURES, "mean": [0.0] * len(FEATURES), "scale": [1.0] * len(FEATURES), "clip_sigma": 10.0})
    write("dataset_manifest.json", {"asset_quality": quality, "trading_eligible_assets": eligible, "model_input_names": INPUTS})
    if experts:
        for index, name in enumerate(EXPERTS):
            write(f"expert_models/{name}/model_weights.json", {"model": model_block, "training": {"decision_threshold": 0.5}, "export": mlp_export(10 + index)})
        write("expert_training_metrics.json", {"experts": {name: {"expert": name, "status": "trained", "quality_status": "promotable", "backtest": {"balanced_accuracy": 0.55, "mcc": 0.1}}
                                                          for name in EXPERTS}, "trained_experts": list(EXPERTS), "gating_eligible_experts": list(EXPERTS)})
    if multitask:
        write("multitask_model.json", {"model": {"type": "multitask", "model_input_features": INPUTS, "decision_threshold": 0.5}, "export": multitask_export(1)})
        write("multitask_feature_schema.json", {"model_input_names": INPUTS})
    if sequence:
        write("sequence_model.json", {"model": {"type": "sequence", "model_input_features": INPUTS, "window_size": window, "decision_threshold": 0.5}, "export": sequence_export(2)})
        write("sequence_feature_schema.json", {"model_input_names": INPUTS, "window_size": window})


def merge(base: dict, changes: dict) -> dict:
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def write_config(root: Path, *, tickers: tuple[str, ...] = ("SPY", "AAPL", "MSFT", "TLT", "BTCUSD", "EURUSD"), overrides: dict | None = None, extra_assets: tuple[dict, ...] = ()) -> dict:
    """A copy of the repo's config.json cut down to a few assets (one of each class that trades), with `overrides` merged on top."""
    config = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    kept = [asset for asset in config["phase1"]["universe"]["assets"] if asset["ticker"] in tickers]
    config["phase1"]["universe"]["assets"] = kept + [dict(asset) for asset in extra_assets]
    config["runtime"]["warmup_bars"] = 5
    merge(config, overrides or {})
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return config


FRED_LEVELS = {"treasury_3mo": 2.3, "treasury_2yr": 2.5, "treasury_5yr": 2.6, "treasury_10yr": 2.7, "treasury_30yr": 3.0, "credit_spread_baa10y": 2.0, "implied_volatility_vix": 18.0,
               "implied_volatility_3m": 19.0, "financial_conditions_nfci": -0.3, "treasury_10yr_real": 0.9, "breakeven_inflation_10y": 1.8, "dollar_index": 115.0, "interbank_3m_eur": -0.3,
               "interbank_3m_gbp": 0.8, "interbank_3m_jpy": -0.1, "interbank_3m_aud": 1.9, "interbank_3m_cad": 1.9, "interbank_3m_chf": -0.7, "interbank_3m_nzd": 1.9}


@functools.lru_cache(maxsize=2)
def _fred_cached(days: int = 800) -> dict:
    """What `load_cached_fred_series()` returns: one list of {date, value} per series key, a seeded wobble around a plausible level."""
    start = datetime.date(2018, 1, 1)
    rng = np.random.default_rng(7)
    out = {}
    for key, level in FRED_LEVELS.items():
        values = level + np.cumsum(rng.normal(0.0, 0.01 * max(abs(level), 1.0), days))
        out[key] = [{"date": start + datetime.timedelta(days=offset), "value": float(value)} for offset, value in enumerate(values)]
    return out


def synthetic_fred(*args, **kwargs) -> dict:
    return _fred_cached()


def lean_names() -> dict:
    """Lean's enums and model classes that main.py names. Models are MagicMocks (their behaviour is Lean's); enums are the member names main.py reads."""
    enum = lambda **members: SimpleNamespace(**members)  # noqa: E731
    return {
        "Resolution": enum(DAILY="Daily", HOUR="Hour", MINUTE="Minute"), "Market": enum(COINBASE="coinbase", USA="usa", OANDA="oanda"),
        "SecurityType": enum(Equity="Equity", Option="Option", Crypto="Crypto", Forex="Forex", Future="Future"), "OptionRight": enum(CALL="Call", PUT="Put"),
        "OrderStatus": enum(Filled="Filled", Submitted="Submitted", PartiallyFilled="PartiallyFilled", Canceled="Canceled", Invalid="Invalid", New="New"),
        "AccountType": enum(Margin="Margin", Cash="Cash"), "InteractiveBrokersFeeModel": MagicMock(name="InteractiveBrokersFeeModel"), "CoinbaseFeeModel": MagicMock(name="CoinbaseFeeModel"),
        "ConstantSlippageModel": MagicMock(name="ConstantSlippageModel"), "InteractiveBrokersBrokerageModel": MagicMock(name="InteractiveBrokersBrokerageModel"),
        "OptionStrategies": FakeOptionStrategies(), "Leg": SimpleNamespace(Create=lambda symbol, quantity: SimpleNamespace(Symbol=symbol, Quantity=quantity)), "Symbol": SimpleNamespace(CreateOption=create_option), "InitialMarginParameters": MagicMock(name="InitialMarginParameters"),
        "BrokerageName": enum(InteractiveBrokersBrokerage="IB"), "timedelta": datetime.timedelta,
    }


def install_stub(monkeypatch, base=None):
    """Install the stand-in `AlgorithmImports`, import a fresh `main`, and return it."""
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = base or FakeLean
    stub.Slice = object  # evaluated at def time by main.py's annotations on Python < 3.14 (CI runs 3.11)
    stub.time = datetime.time  # Lean's star import exports this and shadows the stdlib `time` module
    stub.Exception = type("ClrException", (Exception,), {})  # and System.Exception the same way
    for name, value in lean_names().items():
        setattr(stub, name, value)
    monkeypatch.setitem(sys.modules, "AlgorithmImports", stub)
    redis_stub = types.ModuleType("redis")
    redis_stub.from_url = lambda *args, **kwargs: MagicMock(name="redis_client")
    monkeypatch.setitem(sys.modules, "redis", redis_stub)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415 - must come after the stub is installed

    monkeypatch.setattr(main, "load_cached_fred_series", synthetic_fred)  # the repo's own data/ would make every bar read megabytes
    return main


def build_algorithm(main, root: Path, *, ready: bool = True, now: datetime.datetime | None = None):
    """An initialised algorithm whose root is `root`. Lean-only names main.py reaches during setup get a MagicMock stand-in on the first NameError."""
    main.__dict__["__file__"] = str(root / "main.py")
    algorithm = main.AetherQuantAlgorithm()
    algorithm.messages = []
    algorithm.Debug = algorithm.debug = lambda message: algorithm.messages.append(str(message))
    algorithm.Log = algorithm.log = lambda message: algorithm.messages.append(str(message))
    algorithm.Time = now or datetime.datetime(2019, 1, 2)
    steps = [algorithm.initialize] + ([algorithm._ensure_ready] if ready else [])
    for step in steps:
        for _ in range(120):
            try:
                step()
                break
            except NameError as error:
                match = re.search(r"name '(\w+)' is not defined", str(error))
                if not match:
                    raise
                main.__dict__[match.group(1)] = MagicMock(name=match.group(1))
        else:
            raise AssertionError("setup kept raising NameError")
    return algorithm


def finish_setup(main, algorithm) -> None:
    """Run `_ensure_ready` on an initialised algorithm, giving Lean-only names it reaches a stand-in on the first NameError."""
    for _ in range(120):
        try:
            algorithm._ensure_ready()
            return
        except NameError as error:
            match = re.search(r"name '(\w+)' is not defined", str(error))
            if not match:
                raise
            main.__dict__[match.group(1)] = MagicMock(name=match.group(1))
    raise AssertionError("setup kept raising NameError")


def make_root(tmp_path: Path, **config_kwargs) -> Path:
    root = tmp_path / "world"
    root.mkdir(exist_ok=True)
    config = write_config(root, **config_kwargs)
    write_ml(root, assets=config["phase1"]["universe"]["assets"])
    return root


def fresh(base_config: dict | None = None) -> dict:
    return copy.deepcopy(base_config or {})


__all__ = ["SimpleNamespace", "build_algorithm", "install_stub", "make_root", "write_config", "write_ml"]
