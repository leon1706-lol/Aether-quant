"""Tests for data_pipeline.factor_file_backfill - pure factor-math and
write/read round-trip tests only. yfinance is never imported/invoked in
this file (fetch_corporate_actions() is exercised only via mocking the
deferred `import yfinance` at the call site, matching
test_dividend_backfill.py's own convention) - no real network access
happens here."""

import pandas as pd
import pytest

import train
from data_pipeline.factor_file_backfill import (
    compute_lean_factor_rows,
    configured_equity_tickers,
    fetch_corporate_actions,
    tickers_missing_factor_file,
    write_factor_file,
)


# ---------------------------------------------------------------------------
# compute_lean_factor_rows - pure factor-math, no network
# ---------------------------------------------------------------------------


def _history(rows: dict) -> pd.DataFrame:
    """rows: {date_str: (close, dividend, split)}. Builds a DatetimeIndex
    frame matching yfinance's own Ticker.history(actions=True) column
    names/shape exactly."""
    index = pd.to_datetime(list(rows.keys()))
    return pd.DataFrame(
        {
            "Close": [v[0] for v in rows.values()],
            "Dividends": [v[1] for v in rows.values()],
            "Stock Splits": [v[2] for v in rows.values()],
        },
        index=index,
    )


def test_compute_lean_factor_rows_zero_events_returns_empty():
    history = _history({"2020-01-01": (100.0, 0.0, 0.0), "2020-01-02": (101.0, 0.0, 0.0)})
    assert compute_lean_factor_rows(history) == []


def test_compute_lean_factor_rows_single_dividend_event():
    history = _history(
        {
            "2020-01-01": (100.0, 0.0, 0.0),
            "2020-01-02": (98.0, 2.0, 0.0),  # ex-div: $2 dividend, prior close $100
        }
    )
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2  # the one real event + terminal sentinel
    event_row = rows[0]
    assert event_row["factor_date"] == "20200102"
    assert event_row["price_factor"] == pytest.approx(1.0 - 2.0 / 100.0)
    assert event_row["split_factor"] == pytest.approx(1.0)
    assert event_row["reference_price"] == pytest.approx(98.0)
    assert rows[-1] == {"factor_date": "20501231", "price_factor": 1.0, "split_factor": 1.0, "reference_price": 0.0}


def test_compute_lean_factor_rows_single_split_event():
    history = _history(
        {
            "2020-01-01": (400.0, 0.0, 0.0),
            "2020-01-02": (100.0, 0.0, 4.0),  # 4-for-1 split
        }
    )
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2
    event_row = rows[0]
    assert event_row["factor_date"] == "20200102"
    assert event_row["price_factor"] == pytest.approx(1.0)
    assert event_row["split_factor"] == pytest.approx(0.25)


def test_compute_lean_factor_rows_accumulates_newest_to_oldest():
    # An older dividend's cumulative price_factor must include a NEWER
    # split's contribution too - a raw price at the older date needs
    # adjusting for every corporate action between it and today.
    history = _history(
        {
            "2020-01-01": (100.0, 0.0, 0.0),
            "2020-01-02": (98.0, 2.0, 0.0),  # older: dividend only
            "2020-06-01": (200.0, 0.0, 0.0),
            "2020-06-02": (50.0, 0.0, 4.0),  # newer: 4-for-1 split
        }
    )
    rows = compute_lean_factor_rows(history)
    # 2 real events (oldest-first output order) + terminal sentinel
    assert len(rows) == 3
    dividend_row = next(r for r in rows if r["factor_date"] == "20200102")
    split_row = next(r for r in rows if r["factor_date"] == "20200602")
    # The older dividend row's price_factor must already include the
    # newer split's split_factor being applied to price_factor's own
    # dividend-only computation is untouched by the split (separate
    # columns) - but its split_factor must equal the newer split's own
    # cumulative split_factor, since no split occurred between them.
    assert dividend_row["split_factor"] == pytest.approx(split_row["split_factor"])
    assert dividend_row["split_factor"] == pytest.approx(0.25)
    assert dividend_row["price_factor"] == pytest.approx(1.0 - 2.0 / 100.0)


def test_compute_lean_factor_rows_output_is_oldest_first_with_sentinel_last():
    history = _history(
        {
            "2019-01-01": (100.0, 0.0, 0.0),
            "2019-01-02": (98.0, 2.0, 0.0),
            "2021-01-01": (100.0, 0.0, 0.0),
            "2021-01-02": (98.0, 2.0, 0.0),
        }
    )
    rows = compute_lean_factor_rows(history)
    dates = [row["factor_date"] for row in rows]
    assert dates == ["20190102", "20210102", "20501231"]


def test_compute_lean_factor_rows_zero_dividend_and_zero_split_rows_ignored():
    history = _history(
        {
            "2020-01-01": (100.0, 0.0, 0.0),
            "2020-01-02": (100.5, 0.0, 0.0),  # ordinary trading day, no event
            "2020-01-03": (98.0, 2.0, 0.0),
        }
    )
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2  # only the real event + sentinel
    assert rows[0]["factor_date"] == "20200103"


def test_compute_lean_factor_rows_first_row_dividend_falls_back_to_own_close():
    # An event on the very first row of history has no prior session to
    # look up - must degrade gracefully (use its own close), never raise
    # or crash on an empty prior-close slice.
    history = _history({"2020-01-01": (98.0, 2.0, 0.0)})
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2
    assert rows[0]["price_factor"] == pytest.approx(1.0 - 2.0 / 98.0)


# ---------------------------------------------------------------------------
# configured_equity_tickers / tickers_missing_factor_file
# ---------------------------------------------------------------------------


def test_configured_equity_tickers_resolves_equity_assets_only():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "AAPL_OPT", "security_type": "option", "underlying_ticker": "AAPL"},
                    {"ticker": "MSFT", "security_type": "equity"},
                    {"ticker": "EURUSD", "security_type": "forex"},
                    {"ticker": "MSFT", "security_type": "equity"},  # duplicate
                ]
            }
        }
    }
    assert configured_equity_tickers(config) == ["MSFT"]


def test_configured_equity_tickers_empty_config_returns_empty():
    assert configured_equity_tickers({}) == []


def test_configured_equity_tickers_skips_malformed_entries_without_raising():
    config = {"phase1": {"universe": {"assets": [{"security_type": "equity"}, {"ticker": "MSFT", "security_type": "equity"}]}}}
    assert configured_equity_tickers(config) == ["MSFT"]


def test_tickers_missing_factor_file_filters_to_absent_files(tmp_path):
    (tmp_path / "aapl.csv").write_text("20501231,1,1,0\n", encoding="utf-8")
    result = tickers_missing_factor_file(["AAPL", "NVDA", "GE"], tmp_path)
    assert result == ["NVDA", "GE"]


# ---------------------------------------------------------------------------
# write_factor_file - round-tripped directly against train.py's own reader,
# the real consumer contract this whole module exists to satisfy.
# ---------------------------------------------------------------------------


def test_write_factor_file_round_trips_through_train_load_factor_file(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)
    rows = [
        {"factor_date": "20200102", "price_factor": 0.98, "split_factor": 1.0, "reference_price": 98.0},
        {"factor_date": "20501231", "price_factor": 1.0, "split_factor": 1.0, "reference_price": 0.0},
    ]
    write_factor_file(tmp_path, "TEST", rows)

    factors = train.load_factor_file("TEST")
    assert factors is not None
    assert len(factors) == 2
    assert factors.iloc[0]["price_factor"] == pytest.approx(0.98)
    assert factors.iloc[0]["split_factor"] == pytest.approx(1.0)
    assert factors.iloc[1]["price_factor"] == pytest.approx(1.0)


def test_write_factor_file_writes_lowercase_ticker_filename(tmp_path):
    path = write_factor_file(tmp_path, "NVDA", [dict(factor_date="20501231", price_factor=1.0, split_factor=1.0, reference_price=0.0)])
    assert path.name == "nvda.csv"
    assert path.exists()


# ---------------------------------------------------------------------------
# fetch_corporate_actions - deferred `import yfinance` mocked, never real
# network access.
# ---------------------------------------------------------------------------


def test_fetch_corporate_actions_never_raises_when_yfinance_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    assert fetch_corporate_actions("AAPL") is None
