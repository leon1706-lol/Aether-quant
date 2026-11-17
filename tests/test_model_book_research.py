"""evaluation/model_book_research.py: the aligned score loader, the composites, the trial lists and the rules' pure verdicts (V6.6.9)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation import model_book_research as mbr
from portfolio.premia_signals import ResearchPanel

CLASSES = {"E1": "equity", "E2": "equity", "E3": "equity", "E4": "equity", "B1": "bond", "B2": "bond", "X1": "crypto", "X2": "crypto", "F1": "forex", "F2": "forex"}


def _sessions(count: int = 320) -> list[str]:
    return list(pd.bdate_range("2022-01-03", periods=count).strftime("%Y-%m-%d"))


def _panel(count: int = 320) -> ResearchPanel:
    rng = np.random.default_rng(5)
    sessions = _sessions(count)
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, (count, len(CLASSES))), axis=0)), index=sessions, columns=list(CLASSES))
    carry = pd.DataFrame(rng.normal(size=(count, 2)), index=sessions, columns=["F1", "F2"])
    return ResearchPanel(known, CLASSES, {}, {"fx_carry": carry})


def test_the_universe_is_the_configs_tickers():
    config = {"phase1": {"universe": {"assets": [{"ticker": "A"}, {"ticker": "B"}]}}}
    assert mbr.universe_tickers(config) == ["A", "B"]


def _write_scores(path, rows):
    pd.DataFrame(rows, columns=["date", "ticker", "score"]).to_csv(path, index=False)


def test_a_crypto_score_dated_the_session_is_used_the_next_session_and_an_equity_score_the_same_day(tmp_path):
    path = tmp_path / "s.csv"
    sessions = ["2024-01-02", "2024-01-03", "2024-01-04"]
    _write_scores(path, [
        ("2024-01-02", "E1", 0.1), ("2024-01-03", "E1", 0.2), ("2024-01-04", "E1", 0.3),
        ("2024-01-02", "X1", 0.4), ("2024-01-03", "X1", 0.5), ("2024-01-04", "X1", 0.6),
    ])
    table = mbr.load_score_table(path, sessions, CLASSES)
    assert table["E1"].tolist() == [0.1, 0.2, 0.3]
    assert np.isnan(table["X1"].iloc[0]) and table["X1"].iloc[1:].tolist() == [0.4, 0.5]


def test_changing_the_crypto_bar_of_the_session_does_not_change_that_sessions_row(tmp_path):
    """The truncation test (#390): the crypto score dated D reads a bar that closes after D's decision, so row D may not depend on it."""
    sessions = ["2024-01-02", "2024-01-03", "2024-01-04"]
    base = [("2024-01-02", "X1", 0.4), ("2024-01-03", "X1", 0.5), ("2024-01-04", "X1", 0.6)]
    changed = [*base[:2], ("2024-01-04", "X1", 0.99)]
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    _write_scores(first, base)
    _write_scores(second, changed)
    a = mbr.load_score_table(first, sessions, CLASSES)
    b = mbr.load_score_table(second, sessions, CLASSES)
    assert a["X1"].iloc[2] == b["X1"].iloc[2] == 0.5


def test_a_friday_forex_score_serves_monday_and_the_weekend_rows_are_not_sessions(tmp_path):
    path = tmp_path / "s.csv"
    sessions = ["2024-01-05", "2024-01-08"]  # Friday, Monday
    _write_scores(path, [("2024-01-04", "F1", 0.1), ("2024-01-05", "F1", 0.2), ("2024-01-07", "X1", 0.7)])
    table = mbr.load_score_table(path, sessions, CLASSES)
    assert table["F1"].tolist() == [0.1, 0.2]
    assert table["X1"].iloc[1] == 0.7  # Sunday's bar is the one known at Monday's decision


def test_a_stale_score_is_not_carried_forever_and_the_universe_and_end_filter_rows(tmp_path):
    path = tmp_path / "s.csv"
    sessions = _sessions(12)
    _write_scores(path, [(sessions[0], "F1", 0.1), (sessions[0], "ZZZ", 0.9), (sessions[11], "E1", 0.5)])
    table = mbr.load_score_table(path, sessions, CLASSES, universe=["F1", "E1"], end=sessions[10])
    assert "ZZZ" not in table.columns and "E1" not in table.columns
    assert table["F1"].iloc[1] == 0.1 and np.isnan(table["F1"].iloc[-1])


def test_within_class_z_and_the_composite_ignore_a_part_without_a_view():
    index = ["d1", "d2"]
    table = pd.DataFrame({"E1": [1.0, 5.0], "E2": [3.0, 5.0], "B1": [1.0, 1.0], "B2": [2.0, 1.0]}, index=index)
    classes = {"E1": "equity", "E2": "equity", "B1": "bond", "B2": "bond"}
    z = mbr.within_class_z(table, classes)
    assert z.loc["d1", "E1"] == pytest.approx(-1.0) and z.loc["d1", "E2"] == pytest.approx(1.0)
    assert z.loc["d2"].isna().all()  # no spread, no view
    solo = pd.DataFrame({"E1": [1.0], "B1": [2.0]}, index=["d1"])
    assert mbr.within_class_z(solo, {"E1": "equity", "B1": "bond"}).isna().all().all()
    other = pd.DataFrame({"E1": [np.nan, 1.0], "E2": [np.nan, 2.0], "B1": [2.0, 1.0], "B2": [1.0, 2.0]}, index=index)
    combined = mbr.composite_signal([(0.5, table), (0.5, other)], classes)
    assert combined.loc["d1", "E1"] == pytest.approx(-1.0)  # only the first part has a view of d1's equities
    assert combined.loc["d2", "B1"] == pytest.approx(-1.0)  # table has no view on d2, the other does
    assert combined.loc["d2", "E1"] == pytest.approx(-1.0)


def test_the_trend_vote_momentum_and_low_volatility_read_only_the_past():
    known = _panel().known
    vote = mbr.trend_vote(known)
    assert vote.iloc[:252].isna().all().all() and vote.iloc[252:].notna().any().any()
    assert vote.abs().max().max() <= 1.0
    assert mbr.momentum_12_1(known).iloc[:252].isna().all().all()
    calm = mbr.low_volatility_score(known)
    assert (calm.dropna() <= 0.0).all().all()
    cut = known.iloc[:300]
    pd.testing.assert_frame_equal(mbr.trend_vote(cut), vote.iloc[:300])


def test_signal_tables_name_every_table_the_trials_use():
    panel = _panel()
    rng = np.random.default_rng(1)
    score = pd.DataFrame(rng.random(panel.known.shape), index=panel.known.index, columns=panel.known.columns)
    tables = mbr.signal_tables(panel, {"ml_a1": score, "ml_a2": score, "ml_a3": score * 0.5})
    needed = {spec.params["table"] for spec in [*mbr.candidate_pool(), *mbr.control_trials()]}
    assert needed <= set(tables)
    assert (tables["const"] == 1.0).all().all()
    without_carry = mbr.signal_tables(ResearchPanel(panel.known, CLASSES, {}, {}), {"ml_a1": score})
    assert "mix_a23" not in without_carry and without_carry["mix_all4"].notna().any().any()


def test_the_trial_lists_are_the_registered_sizes_and_only_the_book_names_an_optimizer():
    assert [spec.id for spec in mbr.book_trials()] == [f"b{n:02d}" for n in range(2, 14)]
    assert [spec.id for spec in mbr.mix_trials()] == [f"m{n:02d}" for n in range(1, 7)]
    assert len(mbr.candidate_pool()) == 18 and {spec.id for spec in mbr.control_trials()} == set(mbr.CONTROL_IDS)
    from portfolio.book_optimizer import OPTIMIZERS

    assert {spec.params["optimizer"] for spec in mbr.candidate_pool()} <= set(OPTIMIZERS)
    assert all(spec.params["guard_classes"] == ["forex"] for spec in mbr.candidate_pool())
    assert mbr.model_settings().name_cap_by_class["forex"] * 100_000 >= 5_000


GOOD = {"id": "b02", "sharpe": 0.4, "turnover": 5.0, "max_drawdown": 0.10, "volatility": 0.08, "mean_gross": 1.2, "class_breadth": 0.9}


def test_eligibility_names_every_failed_clause():
    assert mbr.is_eligible(GOOD) == (True, [])
    bad = {**GOOD, "max_drawdown": 0.2, "volatility": None, "mean_gross": float("nan"), "class_breadth": 0.5}
    assert mbr.is_eligible(bad) == (False, ["max_drawdown", "volatility", "mean_gross", "class_breadth"])
    assert mbr.is_eligible({**GOOD, "class_breadth": None})[1] == ["class_breadth"]


def test_the_candidate_is_the_best_eligible_sharpe_and_ties_go_to_the_lower_turnover():
    scores = [
        {**GOOD, "id": "b02", "sharpe": 0.3}, {**GOOD, "id": "b03", "sharpe": 0.5, "turnover": 9.0},
        {**GOOD, "id": "b04", "sharpe": 0.5, "turnover": 4.0}, {**GOOD, "id": "b05", "sharpe": 0.9, "volatility": 0.2},
        {**GOOD, "id": "core", "sharpe": 2.0}, {**GOOD, "id": "b01", "sharpe": 3.0},
    ]
    pick = mbr.pick_candidate(scores)
    assert pick["candidate"] == "b04" and pick["eligible"] == ["b02", "b03", "b04"] and pick["ineligible"] == {"b05": ["volatility"]}


def test_with_nothing_eligible_the_core_stands_in():
    pick = mbr.pick_candidate([{**GOOD, "volatility": 0.5}, {**GOOD, "id": "b03", "sharpe": None}])
    assert pick["candidate"] == "core" and pick["eligible"] == [] and set(pick["ineligible"]) == {"b02"}
    assert "stands in" in pick["reason"]


LEAN = {"completed": True, "engine_log_clean": True, "correlation": 0.95, "annual_return_gap": 0.004}


def test_the_install_rule_needs_every_clause_and_the_share_is_the_fixed_one_for_a_non_survivor():
    verification = {"volatility": 0.07, "max_drawdown": 0.1, "mean_gross": 1.0, "sharpe": -0.1}
    verdict = mbr.install_verdict(verification, LEAN)
    assert verdict["install"] and verdict["share"] == mbr.NON_SURVIVOR_SHARE and verdict["failed"] == [] and verdict["sharpe_reported"] == -0.1
    assert mbr.install_verdict(verification, LEAN, survivor=True)["share"] is None
    worse = mbr.install_verdict({**verification, "max_drawdown": 0.2}, {**LEAN, "correlation": 0.5, "annual_return_gap": -0.05})
    assert not worse["install"] and worse["share"] is None and worse["failed"] == ["lean_correlation", "lean_return_gap", "max_drawdown"]
    no_run = mbr.install_verdict(verification, None)
    assert no_run["failed"] == ["lean_completed", "lean_correlation", "lean_return_gap"]
    assert mbr.install_verdict({}, LEAN)["failed"] == ["max_drawdown", "mean_gross", "volatility"]
    dirty = mbr.install_verdict(verification, {**LEAN, "engine_log_clean": False})
    assert dirty["failed"] == ["lean_completed"]


def test_rows_carry_forward_between_decisions_and_blend_by_share():
    rows = {"2024-01-02": {"A": 1.0}, "2024-01-10": {"A": 2.0}}
    assert mbr.forward_fill_rows(rows, ["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-10"]) == {
        "2024-01-02": {"A": 1.0}, "2024-01-05": {"A": 1.0}, "2024-01-10": {"A": 2.0},
    }
    blended = mbr.blend_rows({"g1": {"2024-01-02": {"A": 0.1}, "2024-01-09": {"A": 0.2}}, "g6": {"2024-01-05": {"B": 0.3}}}, {"g1": 0.7, "g6": 0.3})
    assert blended["2024-01-02"] == {"A": pytest.approx(0.07)}  # g6 has no row yet: flat
    assert blended["2024-01-05"] == {"A": pytest.approx(0.07), "B": pytest.approx(0.09)}
    assert blended["2024-01-09"] == {"A": pytest.approx(0.14), "B": pytest.approx(0.09)}


def test_rank_ic_is_positive_for_a_score_that_knows_the_future_and_blind_to_one_that_does_not():
    panel = _panel()
    known, classes = panel.known, panel.asset_class
    foresight = (known.shift(-5) / known - 1.0).iloc[:-5]
    rng = np.random.default_rng(2)
    noise = pd.DataFrame(rng.normal(size=known.shape), index=known.index, columns=known.columns)
    start, end = known.index[10], known.index[-30]
    good = mbr.rank_ic_diagnostics(foresight, known, classes, horizons=(5,), start=start, end=end)
    bad = mbr.rank_ic_diagnostics(noise, known, classes, horizons=(5,), start=start, end=end)
    assert set(good) == {f"{name}_5d" for name in mbr.CLASSES}
    assert good["equity_5d"]["mean_ic"] > 0.9 and abs(bad["equity_5d"]["mean_ic"]) < 0.3
    assert good["equity_5d"]["n_independent"] < good["equity_5d"]["n_dates"]
    empty = mbr.rank_ic_diagnostics(noise.iloc[:0], known, classes, horizons=(5,), start=start, end=end)
    assert empty["equity_5d"]["mean_ic"] is None and empty["equity_5d"]["t_hac"] is None


def test_installed_tables_follow_the_walk_forward_definitions_and_skip_names_outside_the_universe():
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    dataset = pd.DataFrame({"date": dates * 3, "ticker": ["A"] * 3 + ["B"] * 3 + ["Z"] * 3, "f": range(9)})
    calls = []

    def predictor(frame, export, names, heads, **kwargs):
        calls.append(kwargs["model_kind"])
        size = len(frame)
        base = np.arange(size, dtype=float)
        return {"rank_20d": base, "rank_5d": base[::-1].copy(), "sector_neutral_rank_20d": base / 10.0}

    exports = {"sequence": ({}, {"model_input_names": ["f"]}), "multitask": ({}, {"model_input_names": ["f"]})}
    tables = mbr.installed_score_tables(dataset, exports, start="2024-01-03", end="2024-01-04", universe=["A", "B"], predictor=predictor)
    assert set(tables) == {"inst_a1", "inst_a2", "inst_a3"} and calls == ["sequence", "multitask"]
    assert set(tables["inst_a1"]["ticker"]) == {"A", "B"} and tables["inst_a1"]["date"].min() == "2024-01-03"
    assert len(tables["inst_a1"]) == 4 and tables["inst_a1"]["score"].between(0, 1).all()
    assert tables["inst_a2"]["score"].iloc[0] == pytest.approx(0.1)
    assert mbr.installed_score_tables(dataset, exports, start="2030-01-01", end="2030-02-01", predictor=predictor) == {}
    only_multitask = mbr.installed_score_tables(dataset, {"multitask": exports["multitask"]}, start=dates[0], end=dates[-1], predictor=predictor)
    assert set(only_multitask) == {"inst_a2"}


def test_the_default_predictor_is_the_real_one(monkeypatch):
    import evaluation.model_predictions as predictions

    seen = {}

    def fake(frame, export, names, heads, **kwargs):
        seen["called"] = True
        return {head: np.zeros(len(frame)) for head in heads}

    monkeypatch.setattr(predictions, "predict_heads", fake)
    dataset = pd.DataFrame({"date": ["2024-01-02"], "ticker": ["A"]})
    mbr.installed_score_tables(dataset, {"multitask": ({}, {"model_input_names": []})}, start="2024-01-02", end="2024-01-02")
    assert seen["called"]
