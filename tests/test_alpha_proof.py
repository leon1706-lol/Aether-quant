"""evaluation/alpha_proof.py (V6.4.4): alpha regression, session compounding, bootstrap and the R-ALPHA1 verdict."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.alpha_proof import alpha_regression, r_alpha1, sharpe_bootstrap_ci, to_sessions


def test_alpha_regression_recovers_a_known_alpha_and_beta():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2020-01-01", periods=1500).strftime("%Y-%m-%d")
    market = pd.Series(rng.normal(0.0004, 0.01, len(dates)), index=dates)
    y = 0.001 + 0.5 * market + pd.Series(rng.normal(0, 0.002, len(dates)), index=dates)
    out = alpha_regression(y, pd.DataFrame({"SPY": market}))
    assert out["alpha_daily"] == pytest.approx(0.001, abs=1.5e-4)
    assert out["betas"]["SPY"] == pytest.approx(0.5, abs=0.03)
    assert out["t_hac"] > 5.0
    assert out["alpha_annual"] == pytest.approx(out["alpha_daily"] * 252)


def test_crypto_benchmark_is_on_the_timeline_of_a_runs_daily_sample(monkeypatch, tmp_path):
    # a bar dated D ends at the midnight after the equity close of D, so session D sees the bar dated before it; on its own
    # date BTC led the strategy by a day, hiding a crypto book's beta and booking it as alpha
    import data_pipeline.data_audit as audit
    from evaluation.alpha_proof import benchmark_daily_returns

    dates = pd.date_range("2024-01-01", periods=6)
    prices = {"SPY": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0], "BTCUSD": [10.0, 20.0, 40.0, 80.0, 160.0, 320.0]}
    monkeypatch.setattr(audit, "asset_zip_paths", lambda asset, root: {"trade": asset["ticker"]})
    monkeypatch.setattr(audit, "read_lean_daily_zip", lambda path, kind: pd.DataFrame({"date": dates, "close": prices[path]}))
    config = {"phase1": {"universe": {"assets": [{"ticker": "SPY", "security_type": "equity"}, {"ticker": "BTCUSD", "security_type": "crypto"}]}}}

    out = benchmark_daily_returns(tmp_path, config, start="2024-01-03", end="2024-01-05")

    assert out.loc["2024-01-03", "SPY"] == pytest.approx(102.0 / 101.0 - 1.0)
    # on session 01-03 the latest BTC bar is the one dated 01-02: 10 -> 20
    assert out.loc["2024-01-03", "BTCUSD"] == pytest.approx(1.0)
    assert out.index.max() == "2024-01-05"


def test_noise_has_no_alpha():
    rng = np.random.default_rng(2)
    dates = pd.bdate_range("2020-01-01", periods=800).strftime("%Y-%m-%d")
    market = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    y = pd.Series(rng.normal(0, 0.005, len(dates)), index=dates)
    assert abs(alpha_regression(y, pd.DataFrame({"SPY": market}))["t_hac"]) < 2.5


def test_to_sessions_compounds_weekend_returns_onto_the_next_session():
    daily = pd.Series({"2024-01-05": 0.01, "2024-01-06": 0.02, "2024-01-07": -0.01, "2024-01-08": 0.03, "2024-01-09": 0.0})
    out = to_sessions(daily, ["2024-01-05", "2024-01-08", "2024-01-09"])
    assert out["2024-01-05"] == pytest.approx(0.01)
    assert out["2024-01-08"] == pytest.approx(1.02 * 0.99 * 1.03 - 1.0)
    assert out["2024-01-09"] == pytest.approx(0.0)


def test_bootstrap_is_deterministic_and_brackets_the_sample_sharpe():
    rng = np.random.default_rng(3)
    y = pd.Series(rng.normal(0.001, 0.01, 700))
    first = sharpe_bootstrap_ci(y, annualization=365, draws=300)
    assert first == sharpe_bootstrap_ci(y, annualization=365, draws=300)
    sample = y.mean() / y.std(ddof=1) * np.sqrt(365)
    assert first[0] < sample < first[1]
    assert sharpe_bootstrap_ci(pd.Series([0.01] * 5), annualization=365) == (None, None)


def _report(full_t, dsr, holdout_alpha, fresh_alpha, judgeable=True):
    return {"periods": {
        "full": {"alpha": {"t_hac": full_t}, "dsr": dsr},
        "holdout": {"alpha": {"alpha_annual": holdout_alpha}},
        "fresh": {"alpha": {"alpha_annual": fresh_alpha}, "judgeable": judgeable},
    }}


def test_r_alpha1_needs_every_clause_and_skips_a_short_fresh_period():
    assert r_alpha1(_report(2.5, 0.97, 0.02, 0.01))["verdict"] == "demonstrated"
    verdict = r_alpha1(_report(1.2, 0.30, -0.01, -0.02))
    assert verdict["verdict"] == "not demonstrated" and len(verdict["failed"]) == 4
    short = r_alpha1(_report(2.5, 0.97, 0.02, -0.5, judgeable=False))
    assert short["verdict"] == "demonstrated" and short["fresh_judged"] is False
