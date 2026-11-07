"""evaluation/forward_ledger.py and scripts/forward_ledger.py: a chain nobody can quietly edit, on fixtures with no network."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation.forward_ledger import (
    append_row,
    decide,
    definition_sha256,
    has_session,
    is_rebalance,
    judge_ledger,
    read_ledger,
    session_return,
    turnover,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DEFINITION = {
    "id": "t3_crypto_trend_blend", "kind": "time_series", "family": "crypto_trend", "universe": ["crypto"], "rebalance_every": 5,
    "params": {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120}, "tickers": ["BTCUSD", "ETHUSD"],
    "asset_class": {"BTCUSD": "crypto", "ETHUSD": "crypto"}, "anchor_date": "2024-01-02", "cost_class": "crypto", "initial_weights": {"BTCUSD": 0.05},
    "data_sources": ["coinbase candles", "yahoo chart"],
}


def _row(path, session, weight=0.1, value=0.001, status="ok", candidate="c"):
    payload = {"status": status, "weights": {"A": weight}, "session_return": value if status == "ok" else None, "benchmarks": {"SPY": 0.001}}
    return append_row(path, session=session, candidate=candidate, payload=payload, created_at=f"{session}T22:30:00+00:00")


def test_a_written_chain_verifies(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for session in ("2026-11-03", "2026-11-04"):
        _row(path, session)
    report = judge_ledger(read_ledger(path))
    assert report["chain_valid"] is True and report["rows"] == 2


@pytest.mark.parametrize("edit", ["return", "session", "weights", "delete_first", "swap"])
def test_a_tampered_row_is_caught(tmp_path, edit):
    path = tmp_path / "ledger.jsonl"
    for session in ("2026-11-03", "2026-11-04", "2026-11-05"):
        _row(path, session)
    rows = read_ledger(path)
    if edit == "return":
        rows[1]["payload"]["session_return"] = 0.5
    elif edit == "session":
        rows[1]["payload"]["session"] = "2026-10-01"
    elif edit == "weights":
        rows[0]["payload"]["weights"] = {"A": 0.9}
    elif edit == "delete_first":
        rows = rows[1:]
    else:
        rows[0], rows[1] = rows[1], rows[0]
    report = judge_ledger(rows)
    assert report["chain_valid"] is False and "candidates" not in report


def test_rebalance_days_count_sessions_from_the_frozen_anchor():
    sessions = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=12)]
    flags = [is_rebalance(sessions, day, anchor=sessions[0], every=5) for day in sessions]
    assert [day for day, flag in zip(sessions, flags) if flag] == [sessions[5], sessions[10]]
    assert not is_rebalance(sessions, sessions[0], anchor=sessions[0], every=5)


def test_decide_runs_the_research_pipeline_on_known_prices_only():
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2023-01-02", periods=220)]
    known = pd.DataFrame({"BTCUSD": 100.0 * np.exp(np.arange(220) * 0.01), "ETHUSD": 100.0 * np.exp(-np.arange(220) * 0.01)}, index=dates)
    known = known * (1.0 + np.random.default_rng(1).normal(0.0, 0.01, known.shape))
    weights = decide(DEFINITION, known, dates[-1])
    assert weights.get("BTCUSD", 0.0) > 0.0 and "ETHUSD" not in weights, "long while the trend is up, flat otherwise"
    assert weights["BTCUSD"] <= 0.05 + 1e-9, "crypto's name cap"
    later = known.copy()
    later.iloc[-1] = later.iloc[-1] * 1.0
    assert decide(DEFINITION, later, dates[-1]) == weights


def test_session_return_needs_every_held_mark():
    marks = pd.DataFrame({"A": [100.0, 110.0], "B": [100.0, np.nan]}, index=["d1", "d2"])
    assert session_return({"A": 0.5}, marks, "d1", "d2", cost_bps=0.0) == pytest.approx(0.05)
    assert session_return({"A": 0.5}, marks, "d1", "d2", cost_bps=100.0, traded=0.2) == pytest.approx(0.05 - 0.002)
    assert session_return({"A": 0.5, "B": 0.1}, marks, "d1", "d2", cost_bps=0.0) is None
    assert session_return({"C": 0.1}, marks, "d1", "d2", cost_bps=0.0) is None


def test_turnover_counts_both_sides():
    assert turnover({"A": 0.1, "B": 0.2}, {"A": 0.3}) == pytest.approx(0.4)


def test_the_definition_hash_changes_with_the_rule():
    assert definition_sha256(DEFINITION) != definition_sha256({**DEFINITION, "rebalance_every": 6})
    assert definition_sha256(DEFINITION) == definition_sha256(dict(reversed(list(DEFINITION.items()))))


def test_judging_reports_sessions_and_says_when_too_few(tmp_path):
    path = tmp_path / "ledger.jsonl"
    rng = np.random.default_rng(2)
    for day in pd.bdate_range("2026-11-03", periods=25):
        _row(path, day.strftime("%Y-%m-%d"), value=float(rng.normal(0.001, 0.01)))
    _row(path, "2026-12-30", status="no_data")
    judged = judge_ledger(read_ledger(path))["candidates"]["c"]
    assert judged["sessions"] == 25 and judged["no_data_sessions"] == 1
    assert judged["judgeable"] is False and judged["sharpe"] is not None and "alpha" in judged
    assert judged["minimum_detectable_alpha_sharpe_at_t2"] == pytest.approx(2.0 / (25 / 252) ** 0.5)


def test_a_stopped_schedule_is_flagged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _row(path, "2026-11-03")
    sessions = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2026-11-03", periods=8)]
    assert "warning" in judge_ledger(read_ledger(path), today_sessions=sessions)
    assert "warning" not in judge_ledger(read_ledger(path), today_sessions=sessions[:3])


# --- the runner ------------------------------------------------------------------------------------------------------


def _fake_api(*, block=None, last_session="2024-09-30"):
    sessions = [day for day in pd.bdate_range("2022-10-03", last_session)]
    days = pd.date_range("2024-01-01", last_session)
    stamp = lambda day: int(pd.Timestamp(day, tz="UTC").timestamp())  # noqa: E731
    rng = np.random.default_rng(3)
    btc = 100.0 * np.exp(np.cumsum(rng.normal(0.002, 0.02, len(days))))
    eth = 50.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, len(days))))

    def get(url):
        if block and block in url:
            raise OSError("blocked")
        if "finance.yahoo" in url:
            base = 400.0 if "SPY" in url else 100.0
            closes = [base + i * 0.1 for i in range(len(sessions))]
            return {"chart": {"result": [{"timestamp": [stamp(day) for day in sessions], "indicators": {"adjclose": [{"adjclose": closes}]}}]}}
        series = btc if "BTC" in url else eth
        return [[stamp(day), 0.0, 0.0, 0.0, float(value), 1.0] for day, value in reversed(list(zip(days, series)))]

    return get


def _candidates(tmp_path, *extra, anchor="2024-09-16"):
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"candidates": [{**DEFINITION, "anchor_date": anchor}, *extra]}), encoding="utf-8")
    return path


NOW = datetime.datetime(2024, 9, 30, 22, 30, tzinfo=datetime.timezone.utc)


def test_a_run_writes_one_verified_row_and_a_rerun_writes_none(tmp_path):
    import forward_ledger

    ledger = tmp_path / "ledger.jsonl"
    written = forward_ledger.run(_candidates(tmp_path), ledger, get_json=_fake_api(), now=NOW)
    assert len(written) == 1
    payload = written[0]["payload"]
    assert payload["status"] == "ok" and payload["session"] == "2024-09-30" and payload["session_return"] is not None
    assert {"SPY", "AGG", "BTCUSD"} <= set(payload["benchmarks"])
    assert len(payload["definition_sha256"]) == 64
    assert forward_ledger.run(_candidates(tmp_path), ledger, get_json=_fake_api(), now=NOW) == []
    assert judge_ledger(read_ledger(ledger))["chain_valid"]


def test_a_blocked_price_source_is_a_row_not_a_gap_or_a_crash(tmp_path):
    import forward_ledger

    ledger = tmp_path / "ledger.jsonl"
    written = forward_ledger.run(_candidates(tmp_path), ledger, get_json=_fake_api(block="finance.yahoo"), now=NOW)
    assert written[0]["payload"]["status"] == "no_data" and "Yahoo" in written[0]["payload"]["reason"]
    assert has_session(read_ledger(ledger), DEFINITION["id"], "2024-09-30")


def test_coinbase_blocked_keeps_the_weights_held(tmp_path):
    import forward_ledger

    ledger = tmp_path / "ledger.jsonl"
    written = forward_ledger.run(_candidates(tmp_path), ledger, get_json=_fake_api(block="coinbase"), now=NOW)
    assert written[0]["payload"]["status"] == "no_data"
    assert written[0]["payload"]["weights"] == DEFINITION["initial_weights"]


def test_a_candidate_this_runner_cannot_compute_logs_why(tmp_path):
    import forward_ledger

    ledger = tmp_path / "ledger.jsonl"
    needs_model = {**DEFINITION, "id": "m5", "needs": "torch and a walk-forward model"}
    written = forward_ledger.run(_candidates(tmp_path, needs_model), ledger, get_json=_fake_api(), now=NOW)
    by_name = {row["payload"]["candidate"]: row["payload"] for row in written}
    assert by_name["m5"]["status"] == "no_data" and "torch" in by_name["m5"]["reason"]
    assert by_name[DEFINITION["id"]]["status"] == "ok"


def test_a_weekend_run_records_the_last_session_once(tmp_path):
    import forward_ledger

    ledger = tmp_path / "ledger.jsonl"
    saturday = datetime.datetime(2024, 9, 28, 22, 30, tzinfo=datetime.timezone.utc)
    written = forward_ledger.run(_candidates(tmp_path), ledger, get_json=_fake_api(), now=saturday)
    assert [row["payload"]["session"] for row in written] == ["2024-09-27"]
    assert forward_ledger.run(_candidates(tmp_path), ledger, get_json=_fake_api(), now=saturday) == []


def test_a_rebalance_day_decides_and_charges_its_turnover(tmp_path):
    import forward_ledger

    ledger = tmp_path / "ledger.jsonl"
    sessions = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-09-16", "2024-09-30")]
    anchor = sessions[len(sessions) - 1 - 5]
    written = forward_ledger.run(_candidates(tmp_path, anchor=anchor), ledger, get_json=_fake_api(), now=NOW)
    payload = written[0]["payload"]
    assert payload["rebalance"] is True and payload["turnover"] > 0.0


def test_todays_unfinished_bar_is_not_read():
    import forward_ledger

    closes = {"BTCUSD": {"2024-09-27": 100.0, "2024-09-28": 101.0, "2024-09-29": 102.0, "2024-09-30": 999.0}}
    marks = forward_ledger.known_crypto(closes, ["2024-09-27", "2024-09-30"])
    assert marks.at["2024-09-30", "BTCUSD"] == 102.0, "the session's mark is the bar dated before it"


def test_the_installed_candidate_file_is_the_frozen_rule():
    path = ROOT / "ml" / "forward" / "candidates.json"
    candidates = json.loads(path.read_text(encoding="utf-8"))["candidates"]
    installed = next(item for item in candidates if item["id"] == "t3_crypto_trend_blend_x_eos")
    assert installed["anchor_date"] == "2026-10-28" and installed["rebalance_every"] == 5
    assert len(installed["tickers"]) == 11 and "EOSUSD" not in installed["tickers"] and installed["params"] == {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120}


def test_the_newest_session_counts_before_yahoo_has_adjusted_it():
    import forward_ledger as module

    stamps = [1793629800, 1793716200]  # 2026-11-02 and 2026-11-03, 14:30 UTC
    payload = {"chart": {"result": [{"timestamp": stamps, "indicators": {"quote": [{"close": [100.0, 101.0]}], "adjclose": [{"adjclose": [99.0, None]}]}}]}}
    closes = module.yahoo_closes("SPY", lambda url: payload)
    assert closes == {"2026-11-02": 99.0, "2026-11-03": 101.0}


def test_the_newest_session_counts_when_yahoo_has_left_its_closes_empty():
    import forward_ledger as module

    stamps = [1793629800, 1793716200]  # 2026-11-02 and 2026-11-03, 14:30 UTC
    indicators = {"quote": [{"close": [100.0, None]}], "adjclose": [{"adjclose": [99.0, None]}]}
    closes_at = 1793736000  # 2026-11-03 20:00 UTC
    payload = {"chart": {"result": [{"timestamp": stamps, "indicators": indicators, "meta": {"regularMarketPrice": 101.5, "regularMarketTime": closes_at}}]}}
    assert module.yahoo_closes("SPY", lambda url: payload) == {"2026-11-02": 99.0, "2026-11-03": 101.5}

    # yesterday's last price is not today's close
    stale = {"chart": {"result": [{"timestamp": stamps, "indicators": indicators, "meta": {"regularMarketPrice": 100.0, "regularMarketTime": 1793649600}}]}}
    assert module.yahoo_closes("SPY", lambda url: stale) == {"2026-11-02": 99.0}
