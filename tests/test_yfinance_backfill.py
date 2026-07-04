"""Tests for data_pipeline.yfinance_backfill — V2-19.5.

Conventions: no test classes, module-level helpers. yfinance is never
imported or called here — fetch_yahoo_ohlcv is always replaced via the
fetch_fn injection point, so zero real network access happens in this file.
"""

from datetime import date
from pathlib import Path
from zipfile import ZipFile

from data_pipeline.yfinance_backfill import (
    detect_gap,
    plan_backfill,
    rows_to_lean_csv,
    run_backfill,
    scale_for_lean,
    write_lean_zip,
    yahoo_symbol_for,
)


def _sample_asset(data_path: str, **overrides) -> dict:
    defaults = {
        "ticker": "ETHUSD",
        "security_type": "crypto",
        "market": "coinbase",
        "data_path": data_path,
        "available_from": "2017-09-03",
        "available_to": "2018-04-05",
        "backfill": {
            "source": "yfinance",
            "symbol": "ETH-USD",
            "backfill_from": "2016-01-01",
            "backfill_to": "2017-09-02",
        },
    }
    defaults.update(overrides)
    return defaults


def _sample_yahoo_rows() -> list[dict]:
    return [
        {"date": date(2016, 1, 1), "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000.0},
        {"date": date(2016, 1, 2), "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 1500.0},
    ]


# ---------------------------------------------------------------------------
# yahoo_symbol_for
# ---------------------------------------------------------------------------


def test_yahoo_symbol_for_uses_explicit_config_symbol():
    assert yahoo_symbol_for("ETHUSD", {"symbol": "ETH-USD"}) == "ETH-USD"


def test_yahoo_symbol_for_falls_back_to_ticker_override():
    assert yahoo_symbol_for("BTCUSD", {}) == "BTC-USD"


def test_yahoo_symbol_for_equity_passthrough():
    assert yahoo_symbol_for("AAPL", {}) == "AAPL"


# ---------------------------------------------------------------------------
# detect_gap
# ---------------------------------------------------------------------------


def test_detect_gap_no_backfill_config_returns_false():
    asset = _sample_asset("ethusd.zip", backfill=None)
    gap = detect_gap(asset, existing_rows=[])
    assert gap["needs_backfill"] is False


def test_detect_gap_no_existing_rows_needs_full_range():
    asset = _sample_asset("ethusd.zip")
    gap = detect_gap(asset, existing_rows=[])
    assert gap["needs_backfill"] is True
    assert gap["missing_before"] == date(2016, 1, 1)
    assert gap["fetch_start"] == date(2016, 1, 1)
    assert gap["fetch_end"] == date(2017, 9, 2)


def test_detect_gap_no_gap_when_existing_already_covers_range():
    asset = _sample_asset("ethusd.zip")
    existing_rows = [{"date": date(2015, 1, 1)}, {"date": date(2017, 9, 2)}]
    gap = detect_gap(asset, existing_rows)
    assert gap["needs_backfill"] is False
    assert gap["missing_before"] is None
    assert gap["missing_after"] is None


def test_detect_gap_partial_gap_before_existing_data():
    asset = _sample_asset("ethusd.zip")
    existing_rows = [{"date": date(2017, 9, 3)}, {"date": date(2018, 1, 1)}]
    gap = detect_gap(asset, existing_rows)
    assert gap["needs_backfill"] is True
    assert gap["missing_before"] == date(2016, 1, 1)


# ---------------------------------------------------------------------------
# scale_for_lean
# ---------------------------------------------------------------------------


def test_scale_for_lean_equity_multiplies_prices_by_10000():
    rows = [{"date": date(2020, 1, 1), "open": 16.25, "high": 16.5, "low": 16.0, "close": 16.3, "volume": 1000.0}]
    scaled = scale_for_lean(rows, "equity")
    assert scaled[0]["open"] == 162500
    assert scaled[0]["close"] == 163000
    assert scaled[0]["volume"] == 1000.0  # volume is never scaled


def test_scale_for_lean_crypto_passthrough_unscaled():
    rows = _sample_yahoo_rows()
    scaled = scale_for_lean(rows, "crypto")
    assert scaled[0]["open"] == 1.0
    assert scaled == rows


# ---------------------------------------------------------------------------
# rows_to_lean_csv
# ---------------------------------------------------------------------------


def test_rows_to_lean_csv_format_matches_lean_convention():
    rows = [{"date": date(2016, 1, 1), "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000.0}]
    csv_text = rows_to_lean_csv(rows)
    assert csv_text == "20160101 00:00,1.0,1.2,0.9,1.1,1000.0\n"


def test_rows_to_lean_csv_sorts_by_date():
    rows = [
        {"date": date(2016, 1, 2), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"date": date(2016, 1, 1), "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2},
    ]
    lines = rows_to_lean_csv(rows).splitlines()
    assert lines[0].startswith("20160101")
    assert lines[1].startswith("20160102")


def test_rows_to_lean_csv_empty_input_returns_empty_string():
    assert rows_to_lean_csv([]) == ""


# ---------------------------------------------------------------------------
# write_lean_zip
# ---------------------------------------------------------------------------


def test_write_lean_zip_creates_new_zip(tmp_path):
    output_zip = tmp_path / "ethusd_trade.zip"
    write_lean_zip(output_zip, "ETHUSD", _sample_yahoo_rows(), merge_with_existing=True)

    assert output_zip.exists()
    with ZipFile(output_zip) as archive:
        assert archive.namelist() == ["ethusd.csv"]
        content = archive.read("ethusd.csv").decode("utf-8")
    assert "20160101 00:00,1.0,1.2,0.9,1.1,1000.0" in content


def test_write_lean_zip_existing_rows_win_on_overlapping_dates(tmp_path):
    output_zip = tmp_path / "ethusd_trade.zip"
    # Seed a "real" existing row for 2016-01-01 with a distinctive close price.
    write_lean_zip(output_zip, "ETHUSD", [{"date": date(2016, 1, 1), "open": 9, "high": 9, "low": 9, "close": 9, "volume": 9}], merge_with_existing=False)

    new_rows = _sample_yahoo_rows()  # also has a 2016-01-01 row (close=1.1) and a new 2016-01-02 row
    write_lean_zip(output_zip, "ETHUSD", new_rows, merge_with_existing=True)

    with ZipFile(output_zip) as archive:
        content = archive.read("ethusd.csv").decode("utf-8")
    lines = content.splitlines()
    assert any(line.startswith("20160101 00:00,9,9,9,9,9") for line in lines), "existing row must win, not be overwritten"
    assert any(line.startswith("20160102") for line in lines), "genuinely new date must still be filled in"


# ---------------------------------------------------------------------------
# plan_backfill / run_backfill
# ---------------------------------------------------------------------------


def _config_with_asset(data_path: str, **asset_overrides) -> dict:
    return {"phase1": {"universe": {"assets": [_sample_asset(data_path, **asset_overrides)]}}}


def test_plan_backfill_skips_assets_without_backfill_block(tmp_path):
    config = _config_with_asset(str(tmp_path / "ethusd.zip"), backfill=None)
    assert plan_backfill(config) == []


def test_plan_backfill_filters_by_tickers(tmp_path):
    config = _config_with_asset(str(tmp_path / "ethusd.zip"))
    assert plan_backfill(config, tickers=["LTCUSD"]) == []
    assert len(plan_backfill(config, tickers=["ETHUSD"])) == 1


def test_run_backfill_dry_run_writes_nothing(tmp_path):
    output_zip = tmp_path / "ethusd_trade.zip"
    config = _config_with_asset(str(output_zip))
    plan = plan_backfill(config)

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    report = run_backfill(config, plan, apply=False, fetch_fn=fake_fetch)

    assert not output_zip.exists()
    assert report["entries"][0]["action"] == "dry_run"
    assert report["entries"][0]["rows_fetched"] == 2


def test_run_backfill_apply_writes_zip(tmp_path):
    output_zip = tmp_path / "ethusd_trade.zip"
    config = _config_with_asset(str(output_zip))
    plan = plan_backfill(config)

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    report = run_backfill(config, plan, apply=True, fetch_fn=fake_fetch)

    assert output_zip.exists()
    assert report["entries"][0]["action"] == "written"


def test_run_backfill_skips_when_no_gap(tmp_path):
    output_zip = tmp_path / "ethusd_trade.zip"
    write_lean_zip(
        output_zip,
        "ETHUSD",
        [{"date": date(2015, 1, 1), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, {"date": date(2017, 9, 2), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        merge_with_existing=False,
    )
    config = _config_with_asset(str(output_zip))
    plan = plan_backfill(config)

    calls = []

    def fake_fetch(symbol, start, end):
        calls.append((symbol, start, end))
        return _sample_yahoo_rows()

    report = run_backfill(config, plan, apply=True, fetch_fn=fake_fetch)

    assert report["entries"][0]["action"] == "skipped_no_gap"
    assert calls == []


def test_run_backfill_never_imports_yfinance_when_fetch_fn_injected(tmp_path):
    """fetch_fn replaces fetch_yahoo_ohlcv entirely — yfinance is never
    imported by this test module."""
    import sys

    assert "yfinance" not in sys.modules
