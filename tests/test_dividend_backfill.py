"""Tests for data_pipeline.dividend_backfill - pure cadence-math and
cache round-trip tests only. yfinance is never imported/invoked in this
file (fetch_dividend_history() is exercised only via mocking the deferred
`import yfinance` at the call site, matching test_yfinance_backfill.py's
own convention) - no real network access happens here."""

from datetime import date

from data_pipeline.dividend_backfill import (
    dividend_schedule_payload,
    estimate_next_ex_dividend_date,
    load_cached_dividend_schedule,
    option_underlying_tickers,
    write_dividend_schedule,
)


# ---------------------------------------------------------------------------
# estimate_next_ex_dividend_date - pure cadence-math
# ---------------------------------------------------------------------------


def test_estimate_next_ex_dividend_date_insufficient_history_returns_none_confidence():
    result = estimate_next_ex_dividend_date([], date(2024, 1, 1))
    assert result == {
        "estimated_next_ex_date": None,
        "estimated_amount": None,
        "cadence_days": None,
        "confidence": "none",
        "method": "insufficient_history",
    }


def test_estimate_next_ex_dividend_date_single_event_is_none_confidence():
    history = [{"ex_date": date(2023, 11, 1), "amount": 0.24}]
    result = estimate_next_ex_dividend_date(history, date(2024, 1, 1))
    assert result["confidence"] == "none"
    assert result["estimated_next_ex_date"] is None


def test_estimate_next_ex_dividend_date_regular_quarterly_cadence():
    # Four quarterly events, ~91 days apart - a clean regular cadence.
    history = [
        {"ex_date": date(2023, 2, 1), "amount": 0.23},
        {"ex_date": date(2023, 5, 1), "amount": 0.23},
        {"ex_date": date(2023, 8, 1), "amount": 0.24},
        {"ex_date": date(2023, 11, 1), "amount": 0.24},
    ]
    result = estimate_next_ex_dividend_date(history, date(2023, 12, 1))
    assert result["confidence"] == "medium"
    assert result["cadence_days"] == 92
    assert result["estimated_amount"] == 0.24
    # Projected forward one cadence step from the most recent event.
    assert result["estimated_next_ex_date"] == "2024-02-01"


def test_estimate_next_ex_dividend_date_rolls_forward_past_stale_as_of():
    # as_of is well past the last known event - must roll forward by whole
    # cadence steps, never return a date already in the past.
    history = [
        {"ex_date": date(2022, 1, 1), "amount": 0.20},
        {"ex_date": date(2022, 4, 1), "amount": 0.20},
        {"ex_date": date(2022, 7, 1), "amount": 0.20},
    ]
    result = estimate_next_ex_dividend_date(history, date(2023, 6, 1))
    estimated = date.fromisoformat(result["estimated_next_ex_date"])
    assert estimated > date(2023, 6, 1)


def test_estimate_next_ex_dividend_date_irregular_cadence_is_low_confidence():
    history = [
        {"ex_date": date(2023, 1, 1), "amount": 0.20},
        {"ex_date": date(2023, 2, 15), "amount": 0.20},
        {"ex_date": date(2023, 9, 1), "amount": 0.20},
    ]
    result = estimate_next_ex_dividend_date(history, date(2023, 10, 1))
    assert result["confidence"] == "low"


def test_estimate_next_ex_dividend_date_ignores_future_events():
    history = [
        {"ex_date": date(2023, 1, 1), "amount": 0.20},
        {"ex_date": date(2023, 4, 1), "amount": 0.20},
        {"ex_date": date(2099, 1, 1), "amount": 99.0},  # must never be treated as "past"
    ]
    result = estimate_next_ex_dividend_date(history, date(2023, 5, 1))
    assert result["estimated_amount"] == 0.20


def test_estimate_next_ex_dividend_date_never_raises_on_empty_history():
    assert estimate_next_ex_dividend_date([], date(2020, 1, 1))["confidence"] == "none"


# ---------------------------------------------------------------------------
# dividend_schedule_payload
# ---------------------------------------------------------------------------


def test_dividend_schedule_payload_shape():
    history = [{"ex_date": date(2023, 1, 1), "amount": 0.2}, {"ex_date": date(2023, 4, 1), "amount": 0.2}]
    payload = dividend_schedule_payload("AAPL", history, date(2023, 5, 1))
    assert payload["ticker"] == "AAPL"
    assert payload["fetched_at"] == "2023-05-01"
    assert payload["history"] == [
        {"ex_date": "2023-01-01", "amount": 0.2},
        {"ex_date": "2023-04-01", "amount": 0.2},
    ]
    assert "next_ex_dividend_estimate" in payload


# ---------------------------------------------------------------------------
# write_dividend_schedule / load_cached_dividend_schedule round trip
# ---------------------------------------------------------------------------


def test_write_and_load_dividend_schedule_round_trip(tmp_path):
    history = [{"ex_date": date(2023, 1, 1), "amount": 0.2}, {"ex_date": date(2023, 4, 1), "amount": 0.2}]
    write_dividend_schedule(tmp_path, "AAPL", history, date(2023, 5, 1))
    loaded = load_cached_dividend_schedule("AAPL", tmp_path)
    assert loaded["ticker"] == "AAPL"
    assert len(loaded["history"]) == 2


def test_load_cached_dividend_schedule_missing_file_returns_empty(tmp_path):
    assert load_cached_dividend_schedule("NOPE", tmp_path) == {}


def test_load_cached_dividend_schedule_unreadable_file_returns_empty_not_raise(tmp_path):
    bad_path = tmp_path / "AAPL.json"
    bad_path.write_text("not valid json{{{", encoding="utf-8")
    assert load_cached_dividend_schedule("AAPL", tmp_path) == {}


# ---------------------------------------------------------------------------
# option_underlying_tickers
# ---------------------------------------------------------------------------


def test_option_underlying_tickers_resolves_option_and_equity_assets():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "AAPL_OPT", "security_type": "option", "underlying_ticker": "AAPL"},
                    {"ticker": "MSFT", "security_type": "equity"},
                    {"ticker": "AAPL", "security_type": "equity"},  # duplicate of the option's underlying
                ]
            }
        }
    }
    tickers = option_underlying_tickers(config)
    assert tickers == ["AAPL", "MSFT"]


def test_option_underlying_tickers_empty_config_returns_empty():
    assert option_underlying_tickers({}) == []


def test_option_underlying_tickers_skips_malformed_entries_without_raising():
    config = {"phase1": {"universe": {"assets": [{"security_type": "option"}, {"ticker": "MSFT"}]}}}
    assert option_underlying_tickers(config) == ["MSFT"]


# ---------------------------------------------------------------------------
# fetch_dividend_history - deferred `import yfinance` mocked, never real
# network access.
# ---------------------------------------------------------------------------


def test_fetch_dividend_history_never_raises_when_yfinance_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    from data_pipeline.dividend_backfill import fetch_dividend_history

    assert fetch_dividend_history("AAPL") == []
