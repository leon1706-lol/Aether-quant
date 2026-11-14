"""evaluation/premia_research.py on a synthetic project root (V6.6.6, #359): the context built from Lean zips, CFTC positioning and a listing guard, and a sleeve scored and placebo-tested on it."""

from __future__ import annotations

import datetime
import json

import pandas as pd
import pytest

import train_world as world
from evaluation import premia_research
from portfolio.premia_signals import DIRECT, SleeveSpec, TS


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = world.build_root(tmp_path_factory.mktemp("premia"))
    config = world.build_config()
    reference = root / "data" / "reference"
    reference.mkdir(parents=True)
    sessions = pd.bdate_range("2018-01-05", periods=90, freq="W-FRI")
    rows = [{"report_date": day.strftime("%Y-%m-%d"), "publication_date": (day + datetime.timedelta(days=3)).strftime("%Y-%m-%d"), "market": market, "net_pct_oi": float(index * 0.1 + order)}
            for order, day in enumerate(sessions.to_pydatetime()) for index, market in enumerate(("EUR", "GBP", "JPY", "SPX", "UST10"))]
    pd.DataFrame(rows).to_csv(reference / "cot_positioning.csv", index=False)
    (reference / "listing.json").write_text(json.dumps({"assets": {"BTCUSD": {"listed": "2018-01-01", "suspended": []}}}), encoding="utf-8")
    config["phase_v2"]["venue_listing_guard"] = {"enabled": True, "path": "data/reference/listing.json"}
    return premia_research.build_context(root, config, data_dir="data")


def test_the_context_carries_the_market_the_carry_the_positioning_and_the_listing_guard(context):
    assert set(world.EQUITIES) <= set(context.market.tickers) and {"fx_carry", "cot_fx", "cot_macro"} <= set(context.panel.extras)
    assert context.listed("BTCUSD", "2019-01-02") is True


def test_a_crypto_only_sleeve_is_scored_on_every_day_and_the_rest_on_equity_sessions(context):
    crypto = SleeveSpec("c", "T", DIRECT, "time_series_momentum", ("crypto",), 10, {"lookback_a": 20, "lookback_b": 60})
    equity = SleeveSpec("e", "T", TS, "time_series_momentum", ("equity",), 10, {"lookback_a": 20, "lookback_b": 60})
    assert context.sessions_for(crypto) is None and context.sessions_for(equity) == context.market.sessions


def test_a_sleeve_is_scored_over_its_phases_and_placebos_are_drawn_over_the_same_window(context):
    spec = SleeveSpec("e", "T", TS, "time_series_momentum", ("equity",), 5, {"lookback_a": 20, "lookback_b": 60})
    score = premia_research.score_sleeve(spec, context, start="2018-06-01", split="2019-01-01", end="2019-09-30")
    assert score["id"] == "e" and score["phases"] == 5 and set(score["daily"]) == {0, 1, 2, 3, 4}
    sharpes = premia_research.placebo_sharpes(spec, context, "sign_block", start="2018-06-01", end="2019-09-30", draws=3)
    assert 0 < len(sharpes) <= 3 and all(isinstance(value, float) for value in sharpes)
