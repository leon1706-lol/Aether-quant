"""portfolio/model_book.py: the blended definition, the one row function, and the pure pieces the in-Lean mode calls (V6.6.9)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio import model_book as mb
from portfolio.premia_signals import ResearchPanel, SleeveSpec, WeightSettings, sleeve_signal

CLASSES = {f"E{i}": "equity" for i in range(1, 7)} | {"B1": "bond", "X1": "crypto", "X2": "crypto", "F1": "forex"}
BOOK = {"id": "bk", "track": "BOOK", "kind": "cross_sectional", "family": "external_score", "universe": ["equity"], "every": 5,
        "params": {"table": "ml_a1", "optimizer": "pooled"}}
SLEEVE = {"id": "cr", "track": "T3", "kind": "time_series", "family": "crypto_trend", "universe": ["crypto"], "rebalance_every": 5,
          "params": {"lookback_a": 20, "lookback_b": 60}}
BLEND = {"kind": "blend", "history_start": "2022-06-01", "pinned_run": "run",
         "parts": [{"generation": "g0001", "share": 0.7, "sleeve": SLEEVE, "phase_index": 4}, {"generation": "g0006", "share": 0.3, "book": BOOK, "phase_index": 1}]}
SETTINGS = WeightSettings(name_cap=0.2, class_caps={"crypto": 0.15, "equity": 0.9}, name_cap_by_class={"crypto": 0.05})


def _world(count: int = 300):
    rng = np.random.default_rng(8)
    sessions = list(pd.bdate_range("2021-06-01", periods=count).strftime("%Y-%m-%d"))
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, (count, len(CLASSES))), axis=0)), index=sessions, columns=list(CLASSES))
    scores = pd.DataFrame(rng.random(known.shape), index=sessions, columns=known.columns)
    return known, scores, sessions


def test_the_blend_shape_and_the_single_rule_shape_both_parse():
    definition = mb.parse_definition(BLEND)
    assert [part.generation for part in definition.parts] == ["g0001", "g0006"] and definition.shares == {"g0001": 0.7, "g0006": 0.3}
    assert [part.kind for part in definition.parts] == ["sleeve", "book"] and definition.history_start == "2022-06-01"
    old = mb.parse_definition({"survivors": ["t3_crypto_trend_blend"], "method": None, "phase_index": 4, "history_start": "2023-07-01", "pinned_run": "r"})
    assert old.parts[0].spec == {"survivor": "t3_crypto_trend_blend"} and old.parts[0].share == 1.0 and old.parts[0].phase_index == 4
    with pytest.raises(ValueError, match="sum to 1"):
        mb.parse_definition({**BLEND, "parts": [{**BLEND["parts"][0], "share": 0.5}]})
    with pytest.raises(ValueError, match="sum to 1"):
        mb.parse_definition({**BLEND, "parts": []})
    with pytest.raises(ValueError, match="exactly one survivor"):
        mb.parse_definition({"survivors": ["a", "b"], "method": "hrp", "history_start": "2023-07-01"})


def test_a_spec_comes_from_either_spelling_of_its_cadence_and_a_rule_id_must_be_resolved_first():
    assert mb.spec_of(BOOK).rebalance_every == 5 and mb.spec_of(SLEEVE).rebalance_every == 5 and mb.spec_of(BOOK).params["optimizer"] == "pooled"
    with pytest.raises(ValueError, match="resolve it"):
        mb.spec_of({"survivor": "t3_x"})


def test_the_phase_offsets_are_the_researchs():
    assert mb.phase_offsets(20) == [0, 4, 8, 12, 16] and mb.phase_offsets(5) == [0, 1, 2, 3, 4] and mb.phase_offsets(1) == [0]


def test_spec_weights_applies_the_band_the_partial_move_and_the_guards_its_params_name():
    known, scores, _ = _world()
    panel = ResearchPanel(known, CLASSES, {}, {"ml_a1": scores})
    kwargs = {"settings": SETTINGS, "listed": None, "start": "2022-03-01", "end": "2022-06-30", "phase_offset": 0}
    base = SleeveSpec("s", "T", "cross_sectional", "external_score", ("equity",), 5, {"table": "ml_a1", "optimizer": "pooled"})
    signal = sleeve_signal(base, panel)
    plain = mb.spec_weights(base, panel, signal, **kwargs)
    banded = mb.spec_weights(SleeveSpec("s", "T", base.kind, base.family, base.universe, 5, {**base.params, "band": 0.5}), panel, signal, **kwargs)
    partial = mb.spec_weights(SleeveSpec("s", "T", base.kind, base.family, base.universe, 5, {**base.params, "partial": 0.5}), panel, signal, **kwargs)
    assert plain.keys() == banded.keys() == partial.keys() and plain != banded and plain != partial
    guarded = mb.spec_weights(
        SleeveSpec("s", "T", base.kind, base.family, base.universe, 5, {**base.params, "guard_classes": ["equity"], "guard_lookback": 10, "guard_max_loss": 0.0}), panel, signal, **kwargs,
    )
    assert all(not row for date, row in guarded.items() if list(plain).index(date) < 10)
    halved = mb.spec_weights(SleeveSpec("s", "T", base.kind, base.family, base.universe, 5, {**base.params, "vix_halve": 0.5}), panel, signal, **kwargs)
    assert halved == plain  # no VIX series in this panel: the ratio is unknown, so the row stands


def _row(known, scores, session, *, table=None):
    panel = ResearchPanel(known, CLASSES, {}, {})
    tables = mb.signal_tables(panel, {"ml_a1": scores if table is None else table})
    definition = mb.parse_definition(BLEND)
    return definition, panel, tables


def test_a_session_row_is_the_blend_of_each_parts_latest_decision_and_none_when_no_part_decides():
    known, scores, sessions = _world()
    definition, panel, tables = _row(known, scores, None)
    decided = {}
    for session in sessions[270:300]:
        row = mb.row_for_session(definition, panel, tables, session, settings=SETTINGS, sleeve_settings=WeightSettings(), listed=None, sleeve_signal=sleeve_signal)
        decided[session] = row
    rows = [session for session, row in decided.items() if row is not None]
    assert 0 < len(rows) < 30
    parts = mb.definition_rows(definition, panel, tables, settings=SETTINGS, sleeve_settings=WeightSettings(), listed=None, start=definition.history_start,
                               end=sessions[299], sleeve_signal=sleeve_signal)
    blended = mb.blend_rows(parts, definition.shares)
    for session in rows:
        assert decided[session] == blended[session]
    assert {"g0001", "g0006"} == set(parts) and any(ticker.startswith("X") for ticker in blended[rows[-1]])


def test_the_in_lean_row_equals_the_research_row_from_the_same_closes_and_scores():
    known, scores, sessions = _world()
    definition, _panel_unused, _tables_unused = _row(known, scores, None)
    upto = sessions[:290]
    expected = mb.row_for_session(definition, ResearchPanel(known.loc[upto], CLASSES, {}, {}), mb.signal_tables(ResearchPanel(known.loc[upto], CLASSES, {}, {}), {"ml_a1": scores.loc[upto]}),
                                  upto[-1], settings=SETTINGS, sleeve_settings=WeightSettings(), listed=None, sleeve_signal=sleeve_signal)
    history = {date: scores.loc[date].dropna().to_dict() for date in upto}
    lean = mb.lean_session_row(
        definition, dates=upto, closes={ticker: known.loc[upto, ticker].tolist() for ticker in known.columns}, asset_class=CLASSES, score_history=history,
        settings=SETTINGS, sleeve_settings=WeightSettings(), sleeve_signal=sleeve_signal,
    )
    assert lean == expected
    panel = mb.lean_panel(upto, {ticker: known.loc[upto, ticker].tolist() for ticker in known.columns}, CLASSES)
    pd.testing.assert_frame_equal(panel.known, known.loc[upto], check_freq=False)


def test_session_scores_equal_the_walk_forward_definition_and_skip_a_name_without_both_heads():
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"rank_20d": rng.random(9), "rank_5d": rng.random(9)}, index=list("ABCDEFGHI"))
    frame.loc["B", "rank_5d"] = frame.loc["A", "rank_5d"]  # a tie
    heads = {ticker: row.to_dict() for ticker, row in frame.iterrows()}
    heads["J"] = {"rank_20d": 0.4}
    heads["K"] = {"rank_20d": float("nan"), "rank_5d": 0.2}
    expected = (frame["rank_20d"].rank(pct=True) + frame["rank_5d"].rank(pct=True)) / 2.0
    got = mb.session_scores(heads)
    assert set(got) == set(frame.index) and all(got[ticker] == pytest.approx(expected[ticker]) for ticker in frame.index)
    assert mb.session_scores({}) == {} and mb.session_scores({"J": {"rank_20d": 0.4}}) == {}
    with pytest.raises(ValueError, match="no in-Lean definition"):
        mb.session_scores(heads, "ml_a2")


def test_a_row_is_permitted_only_with_the_pins_finite_weights_and_young_models():
    outcomes = {(a, b, c): mb.permit_model_book_row(a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)}
    assert [key for key, value in outcomes.items() if value] == [(True, True, True)]


def test_a_row_is_finite_unless_a_weight_is_nan_infinite_or_not_a_number():
    assert mb.row_is_finite({}) and mb.row_is_finite({"A": 0.1, "B": -0.2})
    assert not mb.row_is_finite({"A": float("nan")}) and not mb.row_is_finite({"A": float("inf")})
    assert not mb.row_is_finite({"A": "0.1"}) and not mb.row_is_finite({"A": True})


def test_the_holding_carries_the_latest_decision_forward_and_equals_the_decision_on_a_decision_day():
    known, scores, sessions = _world()
    definition, panel, tables = _row(known, scores, None)
    kwargs = {"settings": SETTINGS, "sleeve_settings": WeightSettings(), "listed": None, "sleeve_signal": sleeve_signal}
    decisions = {s: mb.row_for_session(definition, panel, tables, s, **kwargs) for s in sessions[270:285]}
    decision_days = [s for s, row in decisions.items() if row is not None]
    held = {s: mb.holding_for_session(definition, panel, tables, s, **kwargs) for s in sessions[270:285]}
    assert all(held[s] == decisions[s] for s in decision_days)
    in_between = [s for s in sessions[270:285] if s not in decision_days and s > decision_days[0]]
    assert in_between and all(held[s] is not None for s in in_between)
    assert mb.holding_for_session(definition, panel, tables, sessions[100], **kwargs) is None


def test_a_decision_day_is_counted_from_the_history_start_and_the_phase():
    definition = mb.parse_definition(BLEND)  # the sleeve decides at count 4, 9, ... and the book at count 1, 6, ... of the sessions from 2022-06-01
    sessions = ["2022-05-30", "2022-06-01", "2022-06-02", "2022-06-03", "2022-06-06", "2022-06-07", "2022-06-08", "2022-06-09"]
    assert [mb.decides_at(definition, sessions, day) for day in sessions] == [False, False, True, False, False, True, False, True]
    only_book = mb.parse_definition({**BLEND, "parts": [{**BLEND["parts"][1], "share": 1.0}]})
    assert [mb.decides_at(only_book, sessions, day) for day in sessions] == [False, False, True, False, False, False, False, True]


def test_the_weight_settings_are_the_definitions_for_the_book_and_the_defaults_for_the_sleeves():
    book, sleeve = mb.weight_settings(mb.parse_definition({**BLEND, "settings": {"name_cap": 0.3, "class_caps": {"equity": 0.9}}}))
    assert book.name_cap == 0.3 and book.class_caps == {"equity": 0.9} and sleeve == WeightSettings()
    assert mb.weight_settings(mb.parse_definition(BLEND))[0] == WeightSettings()
