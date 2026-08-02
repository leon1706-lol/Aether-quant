"""Per-asset macro sensitivities (V5.1 Phase 2, item 8 / F2 of the plan) -
additive sibling to features/bond_features.py, features/macro_features.py,
features/alt_data_features.py.

F2's finding: every existing macro_*/bond_*/alt_* feature (except
bond_empirical_duration_beta) is written IDENTICALLY to every asset's row
on a date - a per-date constant that shifts every asset's score equally,
which a cross-sectional ranker is by construction invariant to (Spearman/
ListNet ignore any transform that preserves relative order within a date).
"Add more macro features," taken literally, is near-worthless for a rank
model. The version that works is a per-asset SENSITIVITY: how much does
THIS asset's return move per unit of macro change - a quantity that varies
across the cross-section, plus the interaction term (sensitivity x today's
macro move), which is the closest thing to a forward-looking macro-driven
return prediction that stays scale-consistent asset to asset.

Imported by BOTH train.py (offline, per-date/per-asset rolling regression
over the full history) and main.py (runtime, once per symbol per bar using
the same rolling-deque pattern main.py's
_bond_empirical_duration_beta_for_symbol() already established) for
train/inference parity by construction - same convention as every other
features/ module. main.py cannot import train.py (torch), which is the
whole reason this module lives here rather than in train.py alongside
build_cross_asset_sensitivity_features().
"""

from __future__ import annotations

from features.bond_features import empirical_duration_beta

CROSS_ASSET_SENSITIVITY_FEATURE_NAMES = [
    "sens_vix_beta",
    "sens_vix_interaction",
    "sens_real_rate_beta",
    "sens_real_rate_interaction",
    "sens_credit_beta",
    "sens_credit_interaction",
    "sens_dollar_beta",
    "sens_dollar_interaction",
]


def rolling_sensitivity(
    asset_returns: list[float | None],
    macro_changes: list[float | None],
    *,
    lookback: int,
    min_observations: int,
) -> float | None:
    """Trailing-window OLS slope of asset_returns on macro_changes,
    restricted to the last `lookback` positions of each series (positionally
    paired - callers are responsible for date alignment, the same contract
    empirical_duration_beta() itself already documents). A thin wrapper -
    REUSES empirical_duration_beta() rather than reimplementing OLS, exactly
    as bond_empirical_duration_beta already does for a whole-history
    (non-rolling) beta.

    lookback <= 0 disables windowing (uses the full series - a whole-history
    beta, matching bond_empirical_duration_beta's convention). Returns None
    (not 0.0) when fewer than min_observations valid pairs exist in the
    window - a missing/insufficient-history sensitivity must stay
    distinguishable from a genuinely-zero one, same as
    empirical_duration_beta()'s own return contract."""
    if lookback > 0:
        asset_returns = asset_returns[-lookback:]
        macro_changes = macro_changes[-lookback:]
    return empirical_duration_beta(asset_returns, macro_changes, min_observations=min_observations)


def sensitivity_interaction(sensitivity: float | None, macro_change: float | None) -> float:
    """beta_i * delta_macro_t - the interaction term that turns a per-date
    constant macro move into a per-asset-varying signal a cross-sectional
    ranker can actually use. Neutral 0.0 on any missing input, the same
    "None input -> 0.0 neutral output" convention every features/*.py
    interaction/composite function already follows (e.g.
    features/alt_data_features.py's own neutral defaults)."""
    if sensitivity is None or macro_change is None:
        return 0.0
    return float(sensitivity) * float(macro_change)
