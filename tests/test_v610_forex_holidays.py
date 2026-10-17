"""V6.1.0 forex parity: Lean's market holidays drop the zip bar and are never filled forward (Problems.md #189)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import train
from features.cross_asset_timing import CrossAssetTimeline, day_ordinal, fill_forward_open_forex_days, lean_market_holidays

ROOT = Path(__file__).resolve().parents[1]
MARKET_HOURS = ROOT / "data" / "market-hours" / "market-hours-database.json"


def _ord(text: str) -> int:
    return date.fromisoformat(text).toordinal()


def test_holidays_are_read_from_the_market_hours_database(tmp_path):
    db = tmp_path / "mh.json"
    db.write_text(json.dumps({"entries": {"Forex-oanda-[*]": {"holidays": ["12/25/2022", "1/2/2023"]}}}), encoding="utf-8")
    assert lean_market_holidays(str(db)) == {_ord("2022-12-25"), _ord("2023-01-02")}
    assert lean_market_holidays(str(tmp_path / "missing.json")) == frozenset()


def test_a_holiday_gap_is_not_filled_forward():
    friday, monday = _ord("2023-12-22"), _ord("2023-12-25")
    assert fill_forward_open_forex_days([friday, monday], [1.0, 2.0]) == ([friday, friday + 2, monday], [1.0, 1.0, 2.0])
    assert fill_forward_open_forex_days([friday, monday], [1.0, 2.0], frozenset({friday + 2})) == ([friday, monday], [1.0, 2.0])


def test_holiday_bars_are_dropped_and_the_switch_defaults_off():
    frame = pd.DataFrame({"date": pd.to_datetime(["2022-12-23", "2022-12-26", "2022-12-27"]), "close": [1.0, 2.0, 3.0]})
    kept = train.drop_lean_holiday_bars(frame, frozenset({_ord("2022-12-26")}))
    assert kept["date"].dt.strftime("%Y-%m-%d").tolist() == ["2022-12-23", "2022-12-27"]
    assert train.resolve_forex_lean_holidays({"phase1": {"features": {}}}) == frozenset()


def test_the_timeline_uses_the_holiday_calendar_for_forex_only():
    frames = {"EURUSD": pd.DataFrame({"date": pd.to_datetime(["2023-12-22", "2023-12-25"]), "close": [1.0, 2.0]})}
    sunday = _ord("2023-12-24")
    plain = CrossAssetTimeline.from_frames(frames, {"EURUSD": "forex"})
    holiday = CrossAssetTimeline.from_frames(frames, {"EURUSD": "forex"}, forex_holidays=frozenset({sunday}))
    late = float(_ord("2023-12-27"))
    assert plain.closes_before(late)["EURUSD"] == [1.0, 1.0, 2.0]
    assert holiday.closes_before(late)["EURUSD"] == [1.0, 2.0]


@pytest.mark.skipif(not MARKET_HOURS.exists(), reason="Lean market-hours database not present")
def test_gbpjpy_momentum_on_the_holiday_calendar_reproduces_the_live_value():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    asset = next(a for a in config["phase1"]["universe"]["assets"] if a["ticker"] == "GBPJPY")
    try:
        bars = train.load_lean_bars(asset, config["phase1"]["universe"]["common_window"])
    except (FileNotFoundError, OSError):
        pytest.skip("GBPJPY zip not present")
    bars = bars[(bars["date"] >= "2023-10-01") & (bars["date"] <= "2024-02-10")].sort_values("date")
    holidays = lean_market_holidays(str(MARKET_HOURS))
    bars = train.drop_lean_holiday_bars(bars, holidays)
    ordinals, closes = fill_forward_open_forex_days([day_ordinal(d) for d in bars["date"]], bars["close"].tolist(), holidays)
    index = ordinals.index(_ord("2024-01-22"))
    # V6 BT2's live feature snapshot (book history, 2024-01-23 tick, previous-row convention): 0.0395302...
    assert closes[index] / closes[index - 20] - 1.0 == pytest.approx(0.03953, abs=5e-6)


def test_a_forex_tick_holding_a_fill_forward_bar_is_compared_on_its_payload_only():
    from evaluation.live_parity import forex_tick_holds_fill_forward_bar

    # Monday holds Sunday's fill-forward bar; the previous dataset row is Friday
    assert forex_tick_holds_fill_forward_bar("2024-03-04", "2024-03-01")
    # 2025-12-26 holds the 12-25 fill (no zip bar that weekday)
    assert forex_tick_holds_fill_forward_bar("2025-12-26", "2025-12-24")
    # a normal Wednesday holds Tuesday's real bar
    assert not forex_tick_holds_fill_forward_bar("2024-03-06", "2024-03-05")
    # Monday after a Lean holiday Sunday holds Friday's real bar: fully comparable
    assert not forex_tick_holds_fill_forward_bar("2024-01-01", "2023-12-29", frozenset({_ord("2023-12-31")}))
    # Sunday ticks hold Saturday: never a fill (the market is closed)
    assert not forex_tick_holds_fill_forward_bar("2024-03-03", "2024-03-01")
