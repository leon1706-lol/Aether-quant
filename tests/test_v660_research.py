"""The V6.6.0 research path end to end on a synthetic root: a cell's context, scoring and the gate. No network, no real data."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_pipeline.yfinance_backfill import scale_for_lean, write_lean_zip
from evaluation.premia_research import score_sleeve, weights_for
from evaluation.research_cells import coin_side, name_side
from evaluation.wide_context import crypto_cell, equity_cell, liquid_mask_for_cell, signal_ic_t
from portfolio.premia_signals import sleeve_signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DATES = [day.date() for day in pd.bdate_range("2009-06-01", "2019-06-28")]


def _write_equity(root: Path, ticker: str, seed: int, *, last: int | None = None) -> dict:
    rng = np.random.default_rng(seed)
    prices = 50.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(DATES))))
    use = DATES[: last or len(DATES)]
    rows = [{"date": day, "open": float(prices[i]), "high": float(prices[i]) * 1.01, "low": float(prices[i]) * 0.99, "close": float(prices[i]), "volume": 1e6} for i, day in enumerate(use)]
    path = root / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_lean_zip(path, ticker, scale_for_lean(rows, "equity"), merge_with_existing=False)
    raw_dir = root / "reference" / "raw_closes"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{ticker.lower()}.json").write_text(json.dumps({row["date"].isoformat(): row["close"] for row in rows}), encoding="utf-8")
    return {"rows": len(rows), "first": use[0].isoformat(), "last": use[-1].isoformat(), "sha256": "x", "member": ticker not in ("SPY", "AGG", "BIL", "XLK")}


@pytest.fixture(scope="module")
def wide_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    data = root / "data_wide"
    names = [f"N{i:02d}" for i in range(44)]
    manifest = {"tickers": {}, "left_out": {}}
    for seed, ticker in enumerate(["SPY", "AGG", "BIL", "XLK", *names]):
        manifest["tickers"][ticker] = _write_equity(data, ticker, seed)
    (data / "wide_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    reference = data / "reference"
    sector_names = ["energy", "financials", "health_care", "utilities"]
    (reference / "sectors.json").write_text(json.dumps({name: sector_names[i % 4] for i, name in enumerate(names)}), encoding="utf-8")
    lines = ["ticker,start_date,end_date"] + [f"{name},2005-01-03," for name in names]
    (reference / "sp500_ticker_start_end.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rates = data / "alternative" / "interest-rate" / "usa"
    rates.mkdir(parents=True)
    (rates / "interest-rate.csv").write_text("2009-01-01,0.25\n", encoding="utf-8")
    base = {
        "phase1": {"universe": {"assets": [{"ticker": "SPY", "security_type": "equity", "data_path": "data/equity/usa/daily/spy.zip"}]}},
        "phase_v2": {
            "target_weights": {"enabled": False, "financing_enabled": True},
            "cash_sweep": {
                "enabled": False, "ticker": "BIL", "data_path": "data/equity/usa/daily/bil.zip", "max_weight": 0.9, "margin_leverage": 2.0, "margin_buffer": 0.1,
                "cash_buffer": 0.02, "min_trade_weight": 0.05, "cost_bps_per_side": 1.0, "exclude_from_risk_controls": True,
            },
        },
    }
    (root / "scripts").mkdir()
    return root, base, names


def test_a_cell_holds_only_its_side_and_stops_at_its_end(wide_root):
    root, base, names = wide_root
    cell = equity_cell(root, base, "S", with_info=False)
    held = set(cell.context.panel.known.columns)
    side_a = {name for name in names if name_side(name, ["SPY"]) == "A"}
    assert side_a and held & set(names) == side_a
    assert {"SPY", "AGG"} <= held
    assert max(cell.context.panel.known.index) <= "2018-12-31"
    assert max(cell.context.market.dates) <= "2018-12-31"
    assert cell.context.market.closes.shape[1] == len(cell.context.market.tickers)
    assert cell.member.loc["2012-01-03", sorted(side_a)[0]]
    assert not cell.member["SPY"].any(), "a benchmark isn't a member"


def test_a_held_out_cell_refuses_without_the_freeze(wide_root):
    root, base, _ = wide_root
    with pytest.raises(PermissionError):
        equity_cell(root, base, "V3", with_info=False)


def test_side_b_names_cannot_change_a_side_a_panel(wide_root, tmp_path):
    root, base, names = wide_root
    cell = equity_cell(root, base, "S", with_info=False)
    side_b = sorted(name for name in names if name_side(name, ["SPY"]) == "B")
    assert side_b
    assert not set(side_b) & set(cell.features["ret_20"].columns)
    assert not set(side_b) & set(cell.label.columns)


def test_a_trial_scores_on_the_wide_path_and_stays_in_its_window(wide_root):
    from v660_trials import W

    root, base, _ = wide_root
    cell = equity_cell(root, base, "S", with_info=False)
    spec = next(item for item in W if item.id == "w09")
    signal = sleeve_signal(spec, cell.context.panel)
    score = score_sleeve(spec, cell.context, start=cell.cell.start, split=cell.cell.split, end=cell.cell.end, signal=signal)
    assert score["sharpe"] is not None and score["phases"] == 5
    weights = weights_for(spec, cell.context, signal, start=cell.cell.start, end=cell.cell.end, phase_offset=0)
    assert max(weights) <= "2018-12-31" and min(weights) >= "2011-01-01"
    row = next(item for item in weights.values() if item)
    assert all(cell.member.loc["2012-06-01", ticker] for ticker in row), "only members"
    assert abs(sum(row.values())) < 0.05, "dollar neutral within each sector"
    assert max(abs(value) for value in row.values()) <= 0.03 + 1e-9


def test_rank_ic_of_a_perfect_signal_and_of_noise(wide_root):
    root, base, _ = wide_root
    cell = equity_cell(root, base, "S", with_info=False)
    label = cell.label
    perfect = signal_ic_t(label, label, start="2011-01-01", end="2018-06-30", min_names=5)
    assert perfect["mean_ic"] == pytest.approx(1.0, abs=1e-6)
    rng = np.random.default_rng(1)
    noise = pd.DataFrame(rng.normal(size=label.shape), index=label.index, columns=label.columns)
    assert abs(signal_ic_t(noise, label, start="2011-01-01", end="2018-06-30", min_names=5)["nonoverlap_t"]) < 3.0


def test_liquid_mask_keeps_side_a_coins_out_of_the_read_window():
    from evaluation.research_cells import CELLS

    coins = [f"C{i}USD" for i in range(20)]
    dates = ["2021-06-01", "2023-06-01"]
    liquid = pd.DataFrame(True, index=dates, columns=coins)
    mask = liquid_mask_for_cell(liquid, CELLS["CV"], [])
    a = next(coin for coin in coins if coin_side(coin) == "A")
    b = next(coin for coin in coins if coin_side(coin) == "B")
    assert mask.loc["2021-06-01", a] is np.False_ or not mask.loc["2021-06-01", a]
    assert mask.loc["2023-06-01", a] and mask.loc["2021-06-01", b]


def test_every_trial_has_a_cell_and_the_budget_holds():
    from v660_trials import ALL_SPECS, COMBINATION_IDS, PBO_COLUMNS, cell_of

    assert len(ALL_SPECS) + len(COMBINATION_IDS) == 30
    assert len({spec.id for spec in ALL_SPECS}) == len(ALL_SPECS)
    assert {cell_of(spec) for spec in ALL_SPECS} == {"S", "SV", "CS"}
    assert "w13" not in PBO_COLUMNS and not any(name.startswith("c") for name in PBO_COLUMNS)


def test_the_earlier_clauses_are_all_required():
    from v660_research import passes_earlier_clauses

    good = {"sharpe": 0.8, "sharpe_first_half": 0.7, "sharpe_second_half": 0.6, "live_names": {"median": 200.0}, "ic": {"nonoverlap_t": 2.5}}
    assert passes_earlier_clauses("w01", "W", good)
    assert not passes_earlier_clauses("w01", "W", {**good, "sharpe_first_half": 0.3})
    assert not passes_earlier_clauses("w01", "W", {**good, "live_names": {"median": 3.0}})
    assert not passes_earlier_clauses("w01", "W", {**good, "ic": {"nonoverlap_t": 1.5}})
    assert not passes_earlier_clauses("w01", "W", {**good, "ic": None})
    assert passes_earlier_clauses("e3", "E", {**good, "ic": None, "live_names": {"median": 5.0}})


def test_core_trend_table_holds_only_btc_and_eth_and_reads_no_future():
    from v660_research import core_trend_table

    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-01", periods=200)]
    known = pd.DataFrame({"BTCUSD": np.linspace(10.0, 20.0, 200), "ETHUSD": np.linspace(20.0, 10.0, 200), "SOLUSD": 5.0}, index=dates)
    table = core_trend_table(known)
    assert table["SOLUSD"].isna().all()
    assert table["BTCUSD"].iloc[-1] == 1.0 and table["ETHUSD"].iloc[-1] == 0.0
    cut = core_trend_table(known.iloc[:150])
    pd.testing.assert_series_equal(table.iloc[149], cut.iloc[149], check_names=False)


def test_the_wide_model_track_trains_on_its_panel_and_scores_the_other(tmp_path):
    import train_cross_sectional as module

    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2004-01-01", "2012-12-31", freq="5B")]
    rng = np.random.default_rng(2)
    rows = []
    for date in dates:
        for name in range(12):
            rows.append({"date": date, "ticker": f"A{name}", "sector": "energy" if name % 2 else "financials", "ret_5": rng.normal(), "target_wide_20d": rng.normal() * 0.1})
    panel = tmp_path / "a.parquet"
    pd.DataFrame(rows).to_parquet(panel)
    other = tmp_path / "b.parquet"
    pd.DataFrame(rows).assign(ticker=lambda frame: frame["ticker"].str.replace("A", "B")).to_parquet(other)

    out = tmp_path / "scores.csv"
    assert module.main([
        "--panel", str(panel), "--score-panel", str(other), "--model", "gbm", "--variant", "a", "--seeds", "1", "--feature-set", "price",
        "--first-test-year", "2011", "--purge-days", "31", "--score-end", "2011-12-31", "--out", str(out),
    ]) == 0
    scores = pd.read_csv(out)
    assert set(scores["ticker"].str[0]) == {"B"}
    assert scores["date"].min() >= "2011-01-01" and scores["date"].max() <= "2011-12-31"


def test_the_installed_network_fits_on_its_rank_head():
    pytest.importorskip("torch")
    import train_cross_sectional as module

    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2010-01-01", periods=60)]
    rng = np.random.default_rng(3)
    rows = [{"date": date, "ticker": f"A{name}", "_class": "energy", "f": float(rng.normal()), "_label": float(rng.normal())} for date in dates for name in range(10)]
    frame = pd.DataFrame(rows)
    train, test = frame[frame["date"] < dates[40]], frame[frame["date"] >= dates[40]]
    scores = module.fit_predict_mlp_multitask(train, test, ["f"], "a", 1, max_epochs=2, patience=1)
    assert scores.shape == (len(test),) and np.isfinite(scores).all()


def test_the_blend_is_a_rank_mean_of_what_exists(tmp_path, monkeypatch):
    import v660_research as module

    scores = tmp_path / "scores"
    scores.mkdir()
    for name, values in (("m2", [1.0, 2.0]), ("m4", [2.0, 1.0])):
        pd.DataFrame({"date": ["2012-01-03"] * 2, "ticker": ["A", "B"], "score": values}).to_csv(scores / f"{name}.csv", index=False)
    monkeypatch.setattr(module, "ML_SCORES", scores)
    monkeypatch.setattr(module, "check_rules", lambda: {})
    assert module.stage_blend(None) == 0
    assert pd.read_csv(scores / "m5.csv")["score"].tolist() == [0.75, 0.75]


def test_annual_windows_purge_by_31_calendar_days():
    from train_cross_sectional import annual_windows

    windows = annual_windows(["2010-01-04", "2011-06-01", "2012-06-01"], first_test_year=2011, purge_days=31)
    assert windows[0]["train_end"] == (datetime.date(2011, 1, 1) - datetime.timedelta(days=32)).isoformat()


def test_crypto_cell_refuses_an_equity_name(wide_root):
    root, base, _ = wide_root
    with pytest.raises(ValueError):
        crypto_cell(root, base, "S")
    with pytest.raises(ValueError):
        equity_cell(root, base, "CS", with_info=False)
