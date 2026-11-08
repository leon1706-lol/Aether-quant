"""Boundary tests that kill the mutants `scripts/mutation_check.py` left alive in the admission rules, the forward ledger, the research cells and the generation blend (V6.6.4).

A threshold that is only tested far from its edge lets `>=` for `>` pass unnoticed; each rule here is tested exactly at its threshold and one step either side.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from evaluation.generation_registry import (
    CAP_LIFT_CHECKPOINTS,
    TIER2_MAX_NO_DATA,
    TIER2_MIN_SESSIONS,
    AdmissionEvidence,
    Generation,
    _book_stage,
    _tier2_forward_passes,
    append_lifecycle,
    cap_lifted,
    save_registry,
)

SHADOW_OK = dict(selection_pass=True, hold_pass=True, forward_ok_sessions=60, no_data_share=0.05, mean_diff_vs_incumbent=0.0)


def test_the_tier2_forward_test_passes_at_exactly_its_thresholds_and_fails_one_step_past():
    assert _tier2_forward_passes(AdmissionEvidence(**SHADOW_OK)), "60 sessions, a difference of exactly 0.0"
    assert not _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "forward_ok_sessions": TIER2_MIN_SESSIONS - 1}))
    assert not _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "mean_diff_vs_incumbent": -1e-9}))
    assert not _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "mean_diff_vs_incumbent": None}))
    assert not _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "mean_diff_vs_incumbent": float("nan")}))
    assert _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "no_data_share": TIER2_MAX_NO_DATA}))
    assert not _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "no_data_share": TIER2_MAX_NO_DATA + 1e-9}))
    assert not _tier2_forward_passes(AdmissionEvidence(**{**SHADOW_OK, "guard_tripped": True}))


def test_the_cap_lifts_only_at_the_first_checkpoint_with_alpha_t_two_and_a_clean_record():
    lifted = dict(forward_alpha_t=2.0, forward_ok_sessions=CAP_LIFT_CHECKPOINTS[0], no_data_share=0.0)
    assert CAP_LIFT_CHECKPOINTS == (252, 504, 756)
    assert cap_lifted(AdmissionEvidence(**lifted))
    assert not cap_lifted(AdmissionEvidence(**{**lifted, "forward_ok_sessions": 251}))
    assert not cap_lifted(AdmissionEvidence(**{**lifted, "forward_alpha_t": 1.999}))
    assert not cap_lifted(AdmissionEvidence(**{**lifted, "forward_alpha_t": None})) and not cap_lifted(AdmissionEvidence(**{**lifted, "forward_alpha_t": float("nan")}))
    assert cap_lifted(AdmissionEvidence(**{**lifted, "no_data_share": TIER2_MAX_NO_DATA}))
    assert not cap_lifted(AdmissionEvidence(**{**lifted, "no_data_share": TIER2_MAX_NO_DATA + 1e-9}))
    assert not cap_lifted(AdmissionEvidence(**{**lifted, "guard_tripped": True}))


def test_a_generation_on_the_book_keeps_earning_only_while_its_score_is_positive():
    assert _book_stage("active", AdmissionEvidence(score=1e-9)) == "active"
    assert _book_stage("active", AdmissionEvidence(score=0.0)) == "fading", "a score of exactly zero is not earning"
    assert _book_stage("active", AdmissionEvidence(score=None)) == "active", "no score yet is not a reason to fade"
    assert _book_stage("active", AdmissionEvidence(score=float("nan"))) == "fading"


def test_the_registry_types_are_immutable_and_save_makes_its_folder_and_leaves_a_sorted_lf_file(tmp_path):
    with pytest.raises(dataclasses.FrozenInstanceError):
        AdmissionEvidence().selection_pass = True  # type: ignore[misc]
    generation = Generation(id="g1", kind="k", tier="none", stage="shadow", born="2026-11-07", procedure_sha256="ab")
    with pytest.raises(dataclasses.FrozenInstanceError):
        generation.stage = "active"  # type: ignore[misc]
    target = tmp_path / "deep" / "er" / "registry.json"
    save_registry(target, {"g1": generation})
    raw = target.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    text = raw.decode("utf-8")
    assert text.index('"admission"') < text.index('"born"') < text.index('"definition"'), "keys are sorted"


def test_a_lifecycle_row_is_written_with_sorted_keys_in_a_new_folder(tmp_path):
    path = tmp_path / "new" / "dir" / "lifecycle.jsonl"
    append_lifecycle(path, event="stage_changed", payload={"zeta": 1, "alpha": 2}, created_at="2026-11-07T00:00:00Z")
    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line == json.dumps(json.loads(line), sort_keys=True)


# --- evaluation/forward_ledger.py --------------------------------------------------------------------------------------------------------------

import datetime  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from evaluation import forward_ledger as ledger  # noqa: E402


def test_the_constants_the_judge_reads_are_the_pre_registered_ones():
    assert ledger.JUDGE_AT_SESSIONS == (60, 252) and ledger.STALE_WARNING_SESSIONS == 3


def test_an_outage_row_is_dated_by_the_last_us_close_that_has_passed():
    at = lambda day, hour, minute=0: datetime.datetime(2026, 11, day, hour, minute)  # noqa: E731
    assert ledger.session_for_outage(at(6, 21, 0)) == "2026-11-06", "Friday 21:00 UTC is after the close"
    assert ledger.session_for_outage(at(6, 20, 59)) == "2026-11-05", "a minute earlier it is still Thursday's"
    assert ledger.session_for_outage(at(7, 2, 11)) == "2026-11-06", "the delayed Friday run of 2026-11-07"
    assert ledger.session_for_outage(at(9, 5, 0)) == "2026-11-06", "Monday before the close reaches back over the weekend"
    assert ledger.session_for_outage(at(8, 12, 0)) == "2026-11-06"


def test_a_session_return_needs_a_positive_finite_mark_on_both_days():
    marks = pd.DataFrame({"A": [100.0, 110.0], "B": [0.0, 5.0], "C": [-1.0, 5.0], "D": [100.0, float("nan")]}, index=["d0", "d1"])
    assert ledger.session_return({"A": 1.0}, marks, "d0", "d1", cost_bps=0.0) == pytest.approx(0.10)
    for bad in ("B", "C", "D", "Z"):
        assert ledger.session_return({bad: 1.0}, marks, "d0", "d1", cost_bps=0.0) is None, bad
    assert ledger.session_return({"A": 1.0}, marks, "d0", "d1", cost_bps=10.0, traded=0.5) == pytest.approx(0.10 - 0.5 * 10.0 / 1e4)


def test_a_ledger_row_is_written_sorted_into_a_folder_that_did_not_exist(tmp_path):
    path = tmp_path / "a" / "b" / "ledger.jsonl"
    ledger.append_row(path, session="2026-11-06", candidate="c", payload={"zeta": 1, "alpha": 2}, created_at="2026-11-07T00:00:00Z")
    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line == json.dumps(json.loads(line), sort_keys=True) and b"\r" not in path.read_bytes()


def test_the_sharpe_needs_two_readings_that_differ():
    assert ledger._sharpe(np.array([0.01])) is None and ledger._sharpe(np.array([])) is None
    assert ledger._sharpe(np.array([0.01, 0.01])) is None, "no variation, no Sharpe"
    assert ledger._sharpe(np.array([0.01, 0.03])) == pytest.approx(0.02 / np.std([0.01, 0.03], ddof=1) * np.sqrt(252.0))


def _rows(count: int, candidate: str = "c", *, with_benchmarks: bool = True) -> list[dict]:
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2026-01-05", periods=count)
    out = []
    for index, day in enumerate(days):
        payload = {"session": day.date().isoformat(), "candidate": candidate, "status": "ok", "session_return": float(rng.normal(0.001, 0.01))}
        if with_benchmarks:
            payload["benchmarks"] = {"SPY": float(rng.normal(0, 0.01)), "AGG": float(rng.normal(0, 0.003))}
        out.append({"payload": payload})
    return out


@pytest.mark.parametrize("count,judgeable,fully", [(59, False, False), (60, True, False), (251, True, False), (252, True, True)])
def test_a_candidate_is_judgeable_at_sixty_sessions_and_fully_at_a_year(count, judgeable, fully):
    report = ledger.judge_candidate(_rows(count), "c")
    assert report["sessions"] == count and report["judgeable"] is judgeable and report["fully_judgeable"] is fully


def test_the_alpha_regression_starts_at_twenty_sessions_and_a_candidate_with_none_has_no_power_figure():
    assert "alpha" not in ledger.judge_candidate(_rows(19), "c")
    assert "alpha" in ledger.judge_candidate(_rows(20), "c")
    empty = ledger.judge_candidate([], "c")
    assert empty["minimum_detectable_alpha_sharpe_at_t2"] is None and empty["sharpe"] is None and empty["first"] is None
    one = ledger.judge_candidate(_rows(1), "c")
    assert one["minimum_detectable_alpha_sharpe_at_t2"] is not None


def _chained(sessions: list[str], tmp_path) -> list[dict]:
    path = tmp_path / "chain.jsonl"
    for day in sessions:
        ledger.append_row(path, session=day, candidate="c", payload={"status": "ok", "session_return": 0.001}, created_at=f"{day}T22:30:00Z")
    return ledger.read_ledger(path)


def test_a_stale_ledger_warns_only_past_three_sessions_behind(tmp_path):
    rows = _chained(["2026-11-02"], tmp_path)
    calendar = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    three = ledger.judge_ledger(rows, today_sessions=calendar[:4])
    assert three["sessions_behind"] == 3 and "warning" not in three
    four = ledger.judge_ledger(rows, today_sessions=calendar)
    assert four["sessions_behind"] == 4 and "sessions old" in four["warning"]


def test_staleness_needs_both_rows_and_a_calendar_and_an_empty_ledger_says_not_started(tmp_path):
    rows = _chained(["2026-11-02"], tmp_path)
    assert "sessions_behind" not in ledger.judge_ledger(rows, today_sessions=())
    started = ledger.judge_ledger([], today_sessions=["2026-11-02", "2026-11-03"])
    assert "sessions_behind" not in started and "record not started" in started["warning"]


# --- evaluation/research_cells.py --------------------------------------------------------------------------------------------------------------

from evaluation import research_cells as cells  # noqa: E402


def test_the_name_and_coin_splits_are_pinned_because_they_cannot_be_tuned():
    assert cells.SALT == "aq-v660-names" and cells.WARMUP_SESSIONS == 300 and cells.STALE_ROWS == 5
    assert {t: cells.name_side(t) for t in ("AAPL", "MSFT", "XOM", "JPM", "KO", "PEP", "WMT", "T", "BRK.B", "CHTR", "ZTS", "NVDA")} == {
        "AAPL": "A", "MSFT": "B", "XOM": "B", "JPM": "B", "KO": "B", "PEP": "A", "WMT": "A", "T": "A", "BRK.B": "A", "CHTR": "B", "ZTS": "B", "NVDA": "B"}
    assert {t: cells.coin_side(t) for t in ("BTCUSD", "ETHUSDT", "XRPUSD", "ADAUSDT", "SOLUSD", "DOGEUSD", "AVAXUSDT", "LINKUSD")} == {
        "BTCUSD": "A", "ETHUSDT": "A", "XRPUSD": "A", "ADAUSDT": "B", "SOLUSD": "B", "DOGEUSD": "B", "AVAXUSDT": "A", "LINKUSD": "A"}
    assert cells.name_side("MSFT", ["MSFT"]) == "A", "a name an earlier phase read is always A"
    assert cells.coin_side("SOLUSD", ["SOLUSD"]) == "A" and cells.coin_side("ADAUSDT", ["adausd"]) == "A", "BTCUSD and BTCUSDT are one coin, in any case"
    assert cells.coin_side("ADAUSD") == cells.coin_side("ADAUSDT") == "B"


def test_a_cell_holds_the_names_of_its_own_side_and_ab_holds_all():
    equity_b = dataclasses.replace(cells.CELLS["S"], side="B")
    tickers = ["AAPL", "MSFT", "XOM", "PEP"]
    assert cells.names_in_cell(cells.CELLS["S"], tickers, []) == ["AAPL", "PEP"] and cells.names_in_cell(equity_b, tickers, []) == ["MSFT", "XOM"]
    assert cells.names_in_cell(dataclasses.replace(cells.CELLS["S"], side="AB"), tickers, []) == sorted(tickers)
    crypto = cells.CELLS["CS"]
    assert crypto.side == "A" and cells.names_in_cell(crypto, ["BTCUSD", "ADAUSDT", "SOLUSD"], []) == ["BTCUSD"]
    assert cells.names_in_cell(dataclasses.replace(crypto, side="B"), ["BTCUSD", "ADAUSDT", "SOLUSD"], []) == ["ADAUSDT", "SOLUSD"], "coins use the coin split, not the name split"
    with pytest.raises(dataclasses.FrozenInstanceError):
        cells.CELLS["S"].side = "B"  # type: ignore[misc]


def test_the_window_runs_from_the_warmup_before_the_start_to_the_end_inclusive():
    cell = dataclasses.replace(cells.CELLS["S"], start="2020-01-10", end="2020-01-20")
    days = [f"2020-01-{day:02d}" for day in range(1, 32)]
    rows = cells.window_rows(days, cell, warmup=2)
    assert rows[0] == "2020-01-08" and rows[-1] == "2020-01-20", "two sessions of history before the start, and the end day itself"
    assert "2020-01-21" not in rows
    assert cells.window_rows(days, cell, warmup=0)[0] == "2020-01-10", "the start day is the first row"
    assert cells.window_rows(days, cell, warmup=500)[0] == "2020-01-01"
    assert cells.window_rows([], cell) == []


def test_a_name_whose_bars_stopped_goes_blank_after_five_rows_and_not_before():
    index = list(range(12))
    known = pd.DataFrame({"A": 1.0}, index=index)
    closes = pd.DataFrame({"A": [1.0, 1.0, 1.0] + [float("nan")] * 9}, index=index)
    blanked = cells.blank_stale(known, closes)
    assert blanked["A"].iloc[:7].notna().all(), "the last bar was row 2: rows 2 to 6 still see one"
    assert blanked["A"].iloc[7:].isna().all(), "row 7 is five rows past it"
    assert cells.blank_stale(known, closes, rows=2)["A"].iloc[4:].isna().all()


def test_membership_is_open_at_the_start_and_closed_before_the_end():
    mask = cells.membership_mask({"A": [("2020-01-02", "2020-01-04")]}, ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"], ["A", "B"])
    assert mask["A"].tolist() == [False, True, True, False] and not mask["B"].any()


def test_the_once_only_ledgers_are_sorted_lf_files_in_folders_that_did_not_exist(tmp_path):
    ledger_path = tmp_path / "x" / "y" / "holdout_ledger.jsonl"
    cells.record_holdout_read(ledger_path, candidate="c", cells=("V1",), digest="d", created_at="2026-11-07T00:00:00Z")
    line = ledger_path.read_text(encoding="utf-8").splitlines()[0]
    assert line == json.dumps(json.loads(line), sort_keys=True)
    with pytest.raises(PermissionError):
        cells.record_holdout_read(ledger_path, candidate="c2", cells=("V1", "V2"), digest="d2", created_at="2026-11-08T00:00:00Z")
    freeze = tmp_path / "p" / "q" / "freeze.json"
    digest = cells.write_freeze(freeze, {"zeta": 1, "alpha": 2})
    assert digest == cells.freeze_digest_of(freeze) and freeze.read_text(encoding="utf-8").index('"alpha"') < freeze.read_text(encoding="utf-8").index('"zeta"')
    with pytest.raises(FileExistsError):
        cells.write_freeze(freeze, {"x": 1})


# --- portfolio/generation_blend.py -------------------------------------------------------------------------------------------------------------

from portfolio.generation_blend import GlidePolicy, dynamic_targets, update_generation_shares  # noqa: E402
from risk.kill_switch import evaluate_kill_switch  # noqa: E402

BASE = {"enabled": True, "evaluation_bars": 3, "min_bars_for_sharpe": 3}


def test_the_glide_policy_is_immutable_and_keeps_the_best_four_by_default():
    policy = GlidePolicy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.entry_share = 0.5  # type: ignore[misc]
    assert policy.max_generations == 4
    targets = dynamic_targets({f"g{n}": float(n) for n in range(1, 7)}, {}, policy)
    assert sum(1 for value in targets.values() if value > 0.0) == 4 and targets["g1"] == 0.0 and targets["g2"] == 0.0, "the two lowest scores earn nothing"


def test_a_target_search_with_no_positive_score_returns_nothing_held_and_does_not_loop():
    assert dynamic_targets({"a": -1.0, "b": 0.0}, {}, GlidePolicy()) == {"a": 0.0, "b": 0.0}
    assert dynamic_targets({}, {}, GlidePolicy()) == {}


def test_a_share_of_exactly_zero_is_valid_and_a_negative_one_is_damaged():
    policy = GlidePolicy()
    entered = update_generation_shares({"g": 0.0}, {"g": "ramping"}, {"g": "healthy"}, {"g": 1.0}, policy)
    assert entered["g"] == pytest.approx(policy.entry_share), "zero is an empty slot, so the new generation enters"
    assert update_generation_shares({"g": -0.01}, {"g": "ramping"}, {"g": "healthy"}, {"g": 1.0}, policy) == {"g": -0.01}, "damaged shares are held, not repaired"
    over = update_generation_shares({"a": 0.7, "b": 0.7}, {"a": "active", "b": "ramping"}, {"a": "healthy", "b": "healthy"}, {"a": 1.0, "b": 1.0}, policy)
    assert over == {"a": 0.7, "b": 0.7}, "shares that sum past one are held"
    at_one = update_generation_shares({"a": 0.5, "b": 0.5}, {"a": "active", "b": "active"}, {"a": "healthy", "b": "healthy"}, {"a": 1.0, "b": 1.0}, policy)
    assert at_one == {"a": 0.5, "b": 0.5}, "exactly one is valid"


def test_a_gainer_already_above_its_cap_is_not_cut_by_an_empty_older_slot():
    policy = GlidePolicy()
    shares = update_generation_shares({"g": 0.5, "old": 0.0}, {"g": "ramping", "old": "active"}, {"g": "healthy", "old": "healthy"}, {"g": 0.3, "old": 1.0}, policy)
    assert shares["g"] == pytest.approx(0.5) and shares["old"] == 0.0


def test_an_empty_older_slot_does_not_accelerate_the_gainer_but_a_held_decaying_one_does():
    policy = GlidePolicy(accelerate_on_decaying=2.0)
    base = update_generation_shares({"g": 0.4, "old": 0.0}, {"g": "ramping", "old": "active"}, {"g": "healthy", "old": "decaying"}, {"g": 1.0, "old": 1.0}, policy)
    step = (1.0 - policy.entry_share) / policy.glide_sessions
    assert base["g"] == pytest.approx(0.4 + step), "nothing is held by the decaying one, so there is nothing to hurry"
    fast = update_generation_shares({"g": 0.4, "old": 0.3}, {"g": "ramping", "old": "active"}, {"g": "healthy", "old": "decaying"}, {"g": 1.0, "old": 1.0}, policy)
    assert fast["g"] == pytest.approx(0.4 + 2.0 * step)


# --- the survivors of the second mutation run -------------------------------------------------------------------------------------------------

def test_a_crypto_cell_splits_coins_by_the_coin_hash_and_an_equity_cell_names_by_the_name_hash():
    coins = ["DOGEUSD", "AVAXUSDT", "LINKUSD", "BCHUSD", "ETCUSD"]  # each lands on a different side under the two hashes
    crypto_a, crypto_b = cells.CELLS["CS"], dataclasses.replace(cells.CELLS["CS"], side="B")
    assert cells.names_in_cell(crypto_a, coins, []) == ["AVAXUSDT", "ETCUSD", "LINKUSD"] and cells.names_in_cell(crypto_b, coins, []) == ["BCHUSD", "DOGEUSD"]
    equity = dataclasses.replace(cells.CELLS["S"], side="A")
    assert cells.names_in_cell(equity, coins, []) == ["BCHUSD", "DOGEUSD"], "the same strings through the name hash land the other way"


def test_shares_summing_to_exactly_one_plus_the_tolerance_are_still_valid():
    from portfolio.generation_blend import SHARE_TOLERANCE

    policy = GlidePolicy()
    edge = {"a": 0.5, "b": 0.5 + SHARE_TOLERANCE}
    stages, states, caps = {"a": "active", "b": "ramping"}, {"a": "healthy", "b": "healthy"}, {"a": 1.0, "b": 1.0}
    result = update_generation_shares(edge, stages, states, caps, policy)
    assert result["b"] > edge["b"] and result["a"] < edge["a"], "valid shares are processed: the ramping one gains from the older one"
    beyond = {"a": 0.5, "b": 0.5 + 1e-6}
    assert update_generation_shares(beyond, stages, states, caps, policy) == beyond, "past the tolerance the shares are held as given"


def test_a_rolling_sharpe_exactly_at_the_release_level_lets_the_lock_go():
    from risk.kill_switch import _rolling_sharpe

    returns = [0.02, -0.01, 0.03]
    exact = _rolling_sharpe(returns, min_return_std_floor=0.0005)
    config = {**BASE, "min_rolling_sharpe": -1.0, "release_rolling_sharpe": exact}
    at_level = evaluate_kill_switch({"recent_bar_returns": returns, "rolling_sharpe_tripped_last_bar": True}, config)
    assert not at_level.tripped, "released at the level exactly: held only while strictly below it"
    below = evaluate_kill_switch({"recent_bar_returns": returns, "rolling_sharpe_tripped_last_bar": True}, {**config, "release_rolling_sharpe": exact + 1e-6})
    assert below.tripped


# --- the survivors of the fresh-seed mutation run ---------------------------------------------------------------------------------------------

from portfolio.generation_blend import EW_MIN_SESSIONS, ew_sharpe, ew_update, step_toward  # noqa: E402


def test_the_policy_defaults_and_a_half_life_of_sessions_moves_exactly_half_way():
    policy = GlidePolicy()
    assert policy.half_life_sessions == 126 and policy.min_evidence_sessions == 60
    from portfolio.generation_blend import dynamic_generation_shares

    record = {"g": {"ew_sharpe": 1.0, "sessions": 100, "prior": 1.0}}
    moved = dynamic_generation_shares({"g": 0.0}, {"g": "active"}, {"g": "healthy"}, record, {}, policy, sessions=126)
    assert moved["g"] == pytest.approx(0.5), "126 sessions at a 126-session half-life"


def test_nothing_is_known_until_one_generation_has_sixty_sessions_of_record():
    from portfolio.generation_blend import dynamic_generation_shares

    policy = GlidePolicy()
    for sessions, expected in ((59, 0.5), (60, 0.25)):
        record = {"g": {"ew_sharpe": -1.0, "sessions": sessions, "prior": 0.0}}
        out = dynamic_generation_shares({"g": 0.5}, {"g": "active"}, {"g": "healthy"}, record, {}, policy, sessions=126)
        assert out["g"] == pytest.approx(expected), sessions


def test_the_exponentially_weighted_sharpe_waits_for_twenty_sessions_and_for_some_variance():
    state = (0.0, 0.0, 0.0, 0)
    for index in range(EW_MIN_SESSIONS):
        assert ew_sharpe(state) is None or index >= EW_MIN_SESSIONS
        state = ew_update(state, 0.01 if index % 2 else -0.005)
    assert state[3] == EW_MIN_SESSIONS and ew_sharpe(state) is not None
    assert ew_sharpe((state[0], state[1], state[2], EW_MIN_SESSIONS - 1)) is None
    assert ew_sharpe((0.0, 0.0, 0.0, 25)) is None, "no weight, no Sharpe"
    assert ew_sharpe((4.0, 2.0, 1.0, 25)) is None, "mean 0.5 and mean square 0.25: no variance"
    assert ew_sharpe((4.0, 2.0, 1.5, 25)) is not None
    assert ew_update((1.0, 0.0, 0.0, 0), 1.0)[0] == pytest.approx(0.5 ** (1.0 / 126.0) + 1.0), "the default half-life is 126 sessions"
    assert ew_update((1.0, 0.0, 0.0, 0), float("nan")) == (1.0, 0.0, 0.0, 0)


def test_a_small_share_with_a_zero_target_is_gone_only_strictly_below_the_retire_share():
    assert step_toward({"a": 0.05}, {"a": 0.0}, 0.0, 0.05) == {"a": 0.05}, "exactly the retire share stays"
    assert step_toward({"a": 0.04}, {"a": 0.0}, 0.0, 0.05) == {"a": 0.0}
    assert step_toward({"a": 0.04}, {"a": 0.01}, 0.0, 0.05) == {"a": 0.04}, "a positive target keeps it"


def test_cap_target_weight_blocks_only_when_nothing_is_left_under_the_cap():
    from risk_controls import cap_target_weight

    assert cap_target_weight(0.0, 1.0, 1.0) == (0.0, False), "a flat target needs no room"
    assert cap_target_weight(0.5, 1.0, 1.0) == (0.0, True), "no room left blocks it"
    assert cap_target_weight(0.5, 0.8, 1.0) == pytest.approx((0.2, False)) and cap_target_weight(-0.5, 0.8, 1.0) == pytest.approx((-0.2, False))
    assert cap_target_weight(0.2, 0.8, 1.0)[1] is False and cap_target_weight(float("nan"), 0.0, 1.0) == (0.0, True)


def test_a_flat_book_adopts_the_direction_of_the_signal_not_a_short():
    from risk_controls import compute_position_exit_tracking_update

    kwargs = dict(was_invested=True, is_invested=True, close_price=10.0, peak_price_since_entry=None, direction="long", bar_index=5, has_entry_state=False, average_entry_price=None, clear_stale_state=False)
    assert compute_position_exit_tracking_update(signal_name="buy", held_quantity=0.0, **kwargs)["direction"] == "long"
    assert compute_position_exit_tracking_update(signal_name="short", held_quantity=0.0, **kwargs)["direction"] == "short"


def test_the_last_row_of_a_candidate_is_its_own_not_another_candidates(tmp_path):
    rows = [{"payload": {"candidate": "a", "session": "d1"}}, {"payload": {"candidate": "b", "session": "d2"}}, {"payload": {"candidate": "a", "session": "d3"}}]
    assert ledger.last_row_for(rows, "a")["payload"]["session"] == "d3" and ledger.last_row_for(rows, "b")["payload"]["session"] == "d2"
    assert ledger.last_row_for(rows, "c") is None
    assert ledger.has_session(rows, "a", "d1") and not ledger.has_session(rows, "b", "d1")


def test_the_defaults_of_the_evidence_and_the_switch_are_the_safe_ones():
    assert AdmissionEvidence().holdouts_spent is False
    from evaluation.generation_registry import admitted_to_shadow

    assert not admitted_to_shadow(AdmissionEvidence(selection_pass=True, forward_ok_sessions=300)), "without a spent holdout a year of forward sessions is not enough"
    assert admitted_to_shadow(AdmissionEvidence(selection_pass=True, forward_ok_sessions=252, holdouts_spent=True))
    assert not admitted_to_shadow(AdmissionEvidence(selection_pass=True, forward_ok_sessions=251, holdouts_spent=True))
    off = evaluate_kill_switch({"model_age_days": 999.0}, {"max_model_age_days": 1.0})
    assert not off.tripped and off.reason == "kill_switch_disabled", "no `enabled` key means off"


def test_a_sharpe_exactly_at_the_floor_does_not_trip_it():
    from risk.kill_switch import _rolling_sharpe

    returns = [0.02, -0.01, 0.03]
    exact = _rolling_sharpe(returns, min_return_std_floor=0.0005)
    assert not evaluate_kill_switch({"recent_bar_returns": returns}, {**BASE, "min_rolling_sharpe": exact}).tripped
    assert evaluate_kill_switch({"recent_bar_returns": returns}, {**BASE, "min_rolling_sharpe": exact + 1e-6}).tripped
