"""V6.4.0 round: parity of every live-path change the phase adds (all default-off) with the offline path it must match.

- the kill switch's `trip_confirm_bars` carries its counter through the simulator the way main.py carries
  `_kill_switch_rolling_sharpe_below_run`, and is a strict no-op at its default;
- the book-history record: member probabilities (diagnostics.book_history.include_probabilities) and the paper-mode gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.rank_book_simulator import simulate_rank_book
from portfolio.book_construction import BookAllocation, book_history_mode_allowed, build_book_history_record
from risk.kill_switch import evaluate_kill_switch


def _frame(seed=5, signal_strength=-0.004) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [str(d.date()) for d in pd.bdate_range("2021-01-01", periods=140)]
    rows = []
    for date in dates:
        for ticker_index in range(30):
            score = float(rng.normal())
            rows.append({"date": date, "ticker": f"T{ticker_index:02d}", "pred": score,
                         "target_return_1d": score * signal_strength + float(rng.normal(0, 0.006))})
    return pd.DataFrame(rows)


def _run(frame, **kill_switch):
    config = {"enabled": True, "evaluation_bars": 20, "min_rolling_sharpe": -1.0, "min_return_std_for_sharpe": 0.0, **kill_switch}
    return simulate_rank_book(
        frame, prediction_column="pred", top_n=5, bottom_n=5, rebalance_every_bars=5, cost_bps_per_side=0.0,
        commission_bps=0.0, gross_exposure=1.0, dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.12,
        min_universe_size=20, entry_lag_bars=1, kill_switch_config=config,
    )


def test_confirm_bars_of_one_is_byte_identical():
    frame = _frame()
    baseline = _run(frame)
    explicit = _run(frame, trip_confirm_bars=1)
    assert baseline.per_date_net_return == explicit.per_date_net_return
    assert baseline.kill_switch_locked_date_list == explicit.kill_switch_locked_date_list
    assert baseline.num_kill_switch_locked_dates > 0


def test_confirmation_only_removes_locks_never_adds_them():
    frame = _frame()
    baseline = _run(frame)
    confirmed = _run(frame, trip_confirm_bars=3)
    assert confirmed.num_kill_switch_locked_dates < baseline.num_kill_switch_locked_dates


def test_the_simulator_threads_the_counter_like_a_bar_by_bar_replay():
    """main.py feeds evaluate_kill_switch its own previous counter every bar; so does the simulator."""
    returns = [0.01, -0.012] * 15 + [-0.02] * 8 + [0.004, -0.004] * 10
    config = {"enabled": True, "evaluation_bars": 10, "min_rolling_sharpe": -1.0, "min_return_std_for_sharpe": 0.0,
              "trip_confirm_bars": 3}
    run, confirmed = 0, []
    for end in range(10, len(returns) + 1):
        decision = evaluate_kill_switch({"recent_bar_returns": returns[:end], "rolling_sharpe_below_run_last_bar": run}, config)
        run = decision.rolling_sharpe_below_run
        confirmed.append(decision.tripped)
    plain = [evaluate_kill_switch({"recent_bar_returns": returns[:end]}, dict(config, trip_confirm_bars=1)).tripped
             for end in range(10, len(returns) + 1)]
    assert sum(confirmed) < sum(plain)
    assert all(b or not a for a, b in zip(confirmed, plain))  # every confirmed trip is also a first-bar trip


# ---------------------------------------------------------------- book history: probabilities and the paper gate


def _allocation(role="long"):
    return BookAllocation(role=role, book_role_multiplier=1.0, predicted_rank_20d=0.9, rank_head="rank_20d", book_reason="test")


def _record(**extra):
    return build_book_history_record(
        "2024-02-01", {"AAA": _allocation()}, {"AAA": 0.7}, {"AAA": 0.05}, {"AAA": "Tech"},
        {"heads": {"rank_20d": 1.0}, "model_priority": ["multitask"], "demoted": []}, **extra,
    )


def test_member_probabilities_are_absent_by_default_and_finite_when_given():
    assert "member_probabilities" not in _record()
    record = _record(member_probabilities={"AAA": {"probability_up": 0.61, "direction_prob_multitask": float("nan"),
                                                  "direction_prob_sequence": None}})
    assert record["member_probabilities"]["AAA"] == {"probability_up": 0.61, "direction_prob_multitask": None,
                                                    "direction_prob_sequence": None}


@pytest.mark.parametrize(
    ("mode", "enabled", "paper_enabled", "expected"),
    [
        ("backtest", True, False, (True, False)),
        ("backtest", False, True, (False, False)),
        ("paper", True, False, (False, False)),
        ("paper", True, True, (True, True)),
        ("live", True, True, (False, False)),
        ("observation", True, True, (False, False)),
    ],
)
def test_the_book_history_gate_logs_paper_only_when_opted_in_and_never_live(mode, enabled, paper_enabled, expected):
    assert book_history_mode_allowed(mode, enabled, paper_enabled) == expected


# ---------------------------------------------------------------- lead L4: sector-relative ranks, live path = offline path


def _sector_frame():
    rng = np.random.default_rng(3)
    dates = [str(d.date()) for d in pd.bdate_range("2022-01-03", periods=60)]
    rows = []
    for date in dates:
        for index in range(24):
            sector = "tech" if index < 12 else "energy"
            level = 0.6 if sector == "tech" else 0.2  # one sector's scores sit far above the other's
            score = level + float(rng.normal(0, 0.1))
            rows.append({"date": date, "ticker": f"T{index:02d}", "pred": score,
                         "target_return_1d": (score - level) * 0.01 + float(rng.normal(0, 0.004))})
    return pd.DataFrame(rows), {f"T{i:02d}": ("tech" if i < 12 else "energy") for i in range(24)}


def _book(frame, sectors, **extra):
    return simulate_rank_book(
        frame, prediction_column="pred", top_n=4, bottom_n=4, rebalance_every_bars=5, cost_bps_per_side=0.0, commission_bps=0.0,
        gross_exposure=1.0, dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.2, min_universe_size=20,
        entry_lag_bars=1, normalize_to_percentile=True, sector_by_ticker=sectors, log_weights=True, **extra,
    )


def test_sector_relative_rank_changes_the_book_only_when_asked():
    frame, sectors = _sector_frame()
    plain = _book(frame, sectors)
    explicit = _book(frame, sectors, sector_relative_rank=False)
    relative = _book(frame, sectors, sector_relative_rank=True)
    assert plain.per_date_net_return == explicit.per_date_net_return
    assert plain.per_date_net_return != relative.per_date_net_return


def test_build_as_live_kwargs_reads_the_normalisation_from_the_rank_signal_config():
    from evaluation.live_parity import build_as_live_kwargs

    common = dict(book_config={}, exits_config={}, max_position_weight=0.25, candidate_metadata={})
    assert build_as_live_kwargs({}, **common)["sector_relative_rank"] is False
    assert build_as_live_kwargs({}, rank_signal_config={"normalization": "cross_sectional"}, **common)["sector_relative_rank"] is False
    relative = build_as_live_kwargs({}, rank_signal_config={"normalization": "sector_relative"}, sector_relative_min_size=4, **common)
    assert relative["sector_relative_rank"] is True and relative["sector_relative_min_size"] == 4


def test_main_ranks_through_the_same_function_with_the_sector_map():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'rank_normalization in ("cross_sectional", "sector_relative")' in source
    assert 'self.sector_by_ticker if rank_normalization == "sector_relative" else None' in source


# ---------------------------------------------------------------- lead L6: partial adjustment toward the target


def test_partial_adjust_weights_moves_a_fraction_and_drops_dust():
    from portfolio.book_construction import partial_adjust_weights

    current, target = {"A": 0.10, "B": -0.10, "C": 0.0015}, {"A": 0.20, "D": 0.10}
    assert partial_adjust_weights(current, target, 1.0) == target
    half = partial_adjust_weights(current, target, 0.5)
    assert half["A"] == pytest.approx(0.15) and half["B"] == pytest.approx(-0.05) and half["D"] == pytest.approx(0.05)
    assert "C" not in half  # 0.0015 halves to 0.00075, under the 1e-3 dust floor
    assert partial_adjust_weights({"A": 0.1}, {"A": 0.1}, 0.5) == {"A": 0.1}


def test_a_fraction_of_one_leaves_the_book_byte_identical_and_less_than_one_trades_less():
    frame, sectors = _sector_frame()
    base = _book(frame, sectors)
    explicit = _book(frame, sectors, partial_adjust_fraction=1.0)
    half = _book(frame, sectors, partial_adjust_fraction=0.5)
    assert base.per_date_net_return == explicit.per_date_net_return
    assert half.annualized_turnover < base.annualized_turnover


def test_the_as_live_kwargs_read_the_adjust_fraction_from_the_book_config():
    from evaluation.live_parity import build_as_live_kwargs

    common = dict(exits_config={}, max_position_weight=0.25, candidate_metadata={})
    assert build_as_live_kwargs({}, book_config={}, **common)["partial_adjust_fraction"] == 1.0
    assert build_as_live_kwargs({}, book_config={"tranche_adjust_fraction": 0.5}, **common)["partial_adjust_fraction"] == 0.5


# ---------------------------------------------------------------- lead L2: the direction overlay hook, live function = offline function


def test_the_overlay_hook_runs_the_shared_function_on_the_normalised_ranks():
    from portfolio.direction_overlay import apply_direction_overlay, resolve_direction_overlay

    frame, sectors = _sector_frame()
    probabilities = {(row.date, row.ticker): 0.5 + 0.2 * np.sign(row.target_return_1d) for row in frame.itertuples()}  # an oracle
    params = resolve_direction_overlay({"enabled": True, "mode": "blend", "weight": 3.0})
    calls = []

    def overlay(date, ranks):
        calls.append(date)
        return apply_direction_overlay(ranks, {ticker: probabilities.get((date, ticker)) for ticker in ranks}, params)

    base = _book(frame, sectors)
    boosted = _book(frame, sectors, rank_overlay_fn=overlay)
    assert calls and len(calls) == base.num_rebalances
    assert boosted.net_total_return > base.net_total_return  # an oracle direction head can only help
    assert _book(frame, sectors, rank_overlay_fn=None).per_date_net_return == base.per_date_net_return


# ---------------------------------------------------------------- main.py reads the shared functions (on_data is not stub-tested)


def test_main_py_calls_the_shared_v640_functions():
    from pathlib import Path

    source = " ".join((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8").split())
    for needle in (
        "book_history_mode_allowed( self.runtime_mode, self.book_history_diagnostics_enabled, self.book_history_paper_enabled )",
        "member_probabilities=member_probabilities",
        '"direction_prob_multitask": multitask_payload.get("direction_20d") if multitask_payload else None',
        '"rolling_sharpe_below_run_last_bar": self._kill_switch_rolling_sharpe_below_run',
        "self._kill_switch_rolling_sharpe_below_run = kill_switch_decision.rolling_sharpe_below_run",
        "excluded_experts=self.gating_excluded_experts",
        'phase_v2_gating.get("disabled_experts", [])',
    ):
        assert needle in source, needle


def test_crypto_core_only_keeps_graduates_out_of_the_book_candidates():
    from portfolio.book_construction import crypto_core_only_settings, crypto_graduate_excluded

    caps = {"crypto": {"enabled": True, "per_name_cap": 0.005, "class_gross_cap": 0.025, "exempt": ["BTCUSD", "LTCUSD"], "core_only": True}}
    core_only, core = crypto_core_only_settings(caps)
    assert core_only is True and core == frozenset({"BTCUSD", "LTCUSD"})
    assert crypto_graduate_excluded("ETHUSD", "crypto", core_only, core) is True
    assert crypto_graduate_excluded("BTCUSD", "crypto", core_only, core) is False
    assert crypto_graduate_excluded("AAPL", "equity", core_only, core) is False
    assert crypto_core_only_settings({"crypto": {"exempt": ["BTCUSD"]}}) == (False, frozenset({"BTCUSD"}))  # off by default
    assert crypto_core_only_settings(None) == (False, frozenset())
    assert crypto_graduate_excluded("ETHUSD", "crypto", False, core) is False


def test_the_offline_candidate_metadata_applies_the_same_core_only_rule():
    import aq_cli

    assets = [{"ticker": t, "security_type": s} for t, s in (("AAPL", "equity"), ("BTCUSD", "crypto"), ("ETHUSD", "crypto"))]
    base = {"phase1": {"universe": {"assets": assets}}, "phase_v2": {"class_weight_caps": {"crypto": {"exempt": ["BTCUSD"]}}}}
    _classes, eligible_before = aq_cli._universe_asset_metadata(base)
    core_only = {"phase1": base["phase1"], "phase_v2": {"class_weight_caps": {"crypto": {"exempt": ["BTCUSD"], "core_only": True}}}}
    _classes, eligible_after = aq_cli._universe_asset_metadata(core_only)
    assert eligible_after["ETHUSD"] is False
    assert eligible_after["AAPL"] == eligible_before["AAPL"] and eligible_after["BTCUSD"] == eligible_before["BTCUSD"]


def test_main_py_filters_book_candidates_through_the_shared_core_only_function():
    from pathlib import Path

    source = " ".join((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8").split())
    assert "crypto_core_only_settings(self.phase_v2.get(\"class_weight_caps\"))" in source
    assert 'and not crypto_graduate_excluded( symbol_key, asset.get("asset_class") or asset.get("security_type"), self.crypto_core_only, self.crypto_core_names )' in source


def test_the_shipped_config_carries_exactly_the_adopted_changes_and_default_off_everything_else():
    import json
    from pathlib import Path

    config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
    v2 = config["phase_v2"]
    # adopted by the pre-registered rules (Problems #221 R-L5, #225 R-L9)
    assert (v2["portfolio_book"]["rebalance_every_bars"], v2["exits"]["max_holding_bars"]) == (10, 20)
    assert v2["class_weight_caps"]["crypto"]["core_only"] is True
    # default off: nothing else changes the trading path
    assert v2["risk"]["kill_switch"]["trip_confirm_bars"] == 1
    assert v2["gating_network"]["disabled_experts"] == []
    assert v2["diagnostics"]["book_history"]["paper_enabled"] is False
    assert v2["rank_signal"]["normalization"] == "cross_sectional" and "direction_overlay" not in v2["rank_signal"]
    assert "tranche_adjust_fraction" not in v2["portfolio_book"]
