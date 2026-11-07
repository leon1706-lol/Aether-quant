"""A run delayed past midnight UTC still records its session (V6.6.4): session 2026-11-06 was lost this way."""

import datetime

from evaluation.forward_ledger import resolve_session, session_for_outage

SESSIONS = ["2026-11-04", "2026-11-05", "2026-11-06"]


def test_a_late_run_records_the_session_it_was_for():
    assert resolve_session(SESSIONS, "2026-11-07") == "2026-11-06"


def test_a_run_on_the_day_records_that_day():
    assert resolve_session(SESSIONS, "2026-11-05") == "2026-11-05"


def test_an_override_must_be_a_real_session():
    assert resolve_session(SESSIONS, "2026-11-07", "2026-11-05") == "2026-11-05"
    assert resolve_session(SESSIONS, "2026-11-07", "2026-11-08") is None


def test_never_a_future_date_and_no_calendar_gives_nothing():
    assert resolve_session(SESSIONS, "2026-11-01") is None
    assert resolve_session([], "2026-11-07") is None


def test_an_outage_row_is_dated_by_the_last_closed_weekday():
    at = lambda day, hour: datetime.datetime(2026, 11, day, hour, tzinfo=datetime.timezone.utc)  # noqa: E731
    assert session_for_outage(at(6, 22)) == "2026-11-06"
    assert session_for_outage(at(7, 2)) == "2026-11-06"
    assert session_for_outage(at(8, 22)) == "2026-11-06"
    assert session_for_outage(at(10, 2)) == "2026-11-09"


# --- V6.6.4: one bad coin, a record that never started, a silent exit ------------------------------------------------------------------

import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from evaluation.forward_ledger import NoSessionToRecord, judge_ledger  # noqa: E402
from evaluation.research_cycle import due_actions  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_one_failing_coin_does_not_void_the_others():
    import forward_ledger

    def get(url):
        if "ETH" in url:
            raise OSError("delisted")
        return [[1_700_000_000, 0.0, 0.0, 0.0, 10.0, 1.0]]

    closes, failed = forward_ledger.crypto_closes_guarded(["BTCUSD", "ETHUSD"], get)
    assert failed == ["ETHUSD"] and closes["ETHUSD"] == {} and len(closes["BTCUSD"]) == 1


def test_a_session_with_a_failed_coin_it_does_not_hold_is_still_ok(tmp_path):
    import forward_ledger
    from test_forward_ledger import DEFINITION, _fake_api

    held_only_btc = {**DEFINITION, "initial_weights": {"BTCUSD": 0.1}, "anchor_date": "2024-09-27", "rebalance_every": 50}
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"candidates": [held_only_btc]}), encoding="utf-8")
    api = _fake_api()

    def get(url):
        if "ETH" in url:
            raise OSError("delisted")
        return api(url)

    now = datetime.datetime(2024, 9, 30, 22, 30, tzinfo=datetime.timezone.utc)
    rows = forward_ledger.run(path, tmp_path / "ledger.jsonl", get_json=get, now=now)
    assert rows[0]["payload"]["status"] == "ok"


def test_a_scheduled_run_with_no_session_to_write_exits_non_zero(tmp_path, monkeypatch):
    import forward_ledger
    from test_forward_ledger import _candidates, _fake_api

    monkeypatch.setattr(forward_ledger, "_get_json", _fake_api())
    code = forward_ledger.main(["--candidates", str(_candidates(tmp_path)), "--ledger", str(tmp_path / "ledger.jsonl"), "--session", "2030-01-01"])
    assert code == 1
    with pytest.raises(NoSessionToRecord):
        forward_ledger.run(_candidates(tmp_path), tmp_path / "ledger.jsonl", get_json=_fake_api(), now=datetime.datetime(2024, 9, 30, tzinfo=datetime.timezone.utc), session_override="2030-01-01")


def test_a_record_that_never_started_says_so():
    assert "record not started" in judge_ledger([])["warning"]
    actions = due_actions({}, {"chain_valid": True}, session=None, record_started=False)
    assert actions[0]["urgency"] == "now" and "research-cycle.yml" in actions[0]["action"]
    assert all("research-cycle.yml" not in item["action"] for item in due_actions({}, {"chain_valid": True}, session="2026-11-06"))
