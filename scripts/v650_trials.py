"""The V6.5.0 trial list: every selectable candidate, fixed before any of them is scored (rules.json carries a copy)."""

from __future__ import annotations

from portfolio.premia_signals import DIRECT, TS, XS, SleeveSpec

CRYPTO = ("crypto",)
FOREX = ("forex",)
EQUITY = ("equity",)
BOND = ("bond",)
ALL = ("equity", "bond", "forex", "crypto")

T3 = [
    SleeveSpec("t3_crypto_trend_20", "T3", TS, "crypto_trend", CRYPTO, 5, {"lookback_a": 20}),
    SleeveSpec("t3_crypto_trend_60", "T3", TS, "crypto_trend", CRYPTO, 5, {"lookback_a": 60}),
    SleeveSpec("t3_crypto_trend_blend", "T3", TS, "crypto_trend", CRYPTO, 5, {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120}),
    SleeveSpec("t3_fx_mom_21", "T3", XS, "cross_sectional_return", FOREX, 5, {"lookback": 21}),
    SleeveSpec("t3_fx_mom_63", "T3", XS, "cross_sectional_return", FOREX, 5, {"lookback": 63}),
    SleeveSpec("t3_fx_mom_126", "T3", XS, "cross_sectional_return", FOREX, 5, {"lookback": 126}),
    SleeveSpec("t3_fx_carry", "T3", XS, "fx_carry", FOREX, 20, {}),
    SleeveSpec("t3_fx_carry_mom", "T3", XS, "fx_carry", FOREX, 20, {"momentum_weight": 0.5}),
    SleeveSpec("t3_bond_slope", "T3", DIRECT, "bond_slope_timing", BOND, 20, {}),
    SleeveSpec("t3_bond_credit", "T3", DIRECT, "bond_credit_timing", BOND, 20, {}),
    SleeveSpec("t3_bond_tsmom", "T3", TS, "time_series_momentum", BOND, 20, {"lookback_a": 126}),
    SleeveSpec("t3_eq_reversal_5", "T3", XS, "residual_reversal", EQUITY, 5, {"window": 5}),
    SleeveSpec("t3_eq_reversal_10", "T3", XS, "residual_reversal", EQUITY, 5, {"window": 10}),
    SleeveSpec("t3_eq_resmom_252", "T3", XS, "residual_momentum", EQUITY, 20, {"lookback": 252, "skip": 21}),
    SleeveSpec("t3_eq_resmom_126", "T3", XS, "residual_momentum", EQUITY, 20, {"lookback": 126, "skip": 21}),
    SleeveSpec("t3_eq_lowvol", "T3", XS, "low_volatility", EQUITY, 20, {}),
    SleeveSpec("t3_trend_blend", "T3", TS, "time_series_momentum", ("equity", "bond"), 20,
               {"lookback_a": 63, "lookback_b": 126, "lookback_c": 252, "trend_set": 1}),
    SleeveSpec("t3_vix_on_off", "T3", DIRECT, "vix_term_structure", EQUITY, 5, {"threshold": 0.95}),
    SleeveSpec("t3_vix_scaled", "T3", DIRECT, "vix_term_structure", EQUITY, 5, {}),
    SleeveSpec("t3_turn_of_month", "T3", DIRECT, "turn_of_month", EQUITY, 1, {}),
]

T4 = [
    SleeveSpec("t4_cot_fx", "T4", XS, "external_score", FOREX, 5, {"table": "cot_fx"}),
    SleeveSpec("t4_cot_macro", "T4", TS, "external_score", ("equity", "bond"), 5, {"table": "cot_macro"}),
]

ML_HEADS = {"a1": "seq_rank_blend", "a2": "mt_sector_neutral", "a3": "seq_sector_neutral"}
T2 = [
    SleeveSpec(
        f"t2_{head}_{every}_{'top6' if top_k else 'full'}", "T2", XS, "external_score", ALL, every,
        {"table": f"ml_{head}", **({"top_k": top_k} if top_k else {})},
    )
    for head in ML_HEADS
    for every in (5, 20)
    for top_k in (6, 0)
]

T5 = [
    SleeveSpec(f"t5_{model}_{variant}", "T5", XS, "external_score", ALL, 20, {"table": f"t5_{model}_{variant}"})
    for model in ("st", "gbm")
    for variant in ("a", "b")
]

ALL_SPECS = [*T3, *T4, *T2, *T5]
ABLATION_IDS = ["v650_bt18", "v650_bt19", "v650_bt20", "v650_bt21", "v650_bt22", "v650_bt23"]
COMBINATION_IDS = ["t6_inverse_vol", "t6_hrp"]
