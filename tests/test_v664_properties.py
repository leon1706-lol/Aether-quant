"""Property-based tests (V6.6.4): the invariants a safety, admission or ledger path must hold for every input, not just the ones someone thought of.

`derandomize=True` makes every run the same on every host, so a failure here is reproducible and never a CI flake. A failure is a real finding: fix it with a regression test and log it.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain  # noqa: E402
from evaluation.forward_ledger import resolve_session  # noqa: E402
from evaluation.generation_registry import STAGES, TIERS, AdmissionEvidence, Generation, next_stage, share_cap  # noqa: E402
from execution.order_gate import resolve_cash_sweep_order_permission, resolve_order_permission, resolve_risk_exit_permission  # noqa: E402
from json_safety import sanitize_json_finite  # noqa: E402
from portfolio.generation_blend import GlidePolicy, dynamic_generation_shares, update_generation_shares  # noqa: E402
from portfolio.premia_signals import ResearchPanel, WeightSettings, scale_and_cap, signal_to_weights  # noqa: E402

PROFILE = settings(derandomize=True, max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
booleans = st.booleans()
finite = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
anything = st.floats(allow_nan=True, allow_infinity=True)
HEAVY = settings(PROFILE, max_examples=30)  # builds pandas frames per example


# --- the order gate -------------------------------------------------------------------------------------------------------

@PROFILE
@given(booleans, booleans, booleans)
def test_observation_mode_never_permits_an_order(allow_live, broker, healthy):
    assert resolve_order_permission("observation", allow_live, broker, healthy)[0] is False
    assert resolve_risk_exit_permission("observation", allow_live, broker)[0] is False
    assert resolve_cash_sweep_order_permission("observation", allow_live, broker)[0] is False


@PROFILE
@given(st.text(max_size=12), booleans, booleans, booleans)
def test_an_unknown_mode_never_permits_an_order(mode, allow_live, broker, healthy):
    if mode in ("backtest", "observation", "paper", "live"):
        return
    assert resolve_order_permission(mode, allow_live, broker, healthy)[0] is False


@PROFILE
@given(st.sampled_from(["paper", "live"]), booleans, booleans)
def test_a_tripped_risk_lock_stops_new_orders_in_paper_and_live(mode, allow_live, broker):
    assert resolve_order_permission(mode, allow_live, broker, False)[0] is False


@PROFILE
@given(st.sampled_from(["paper", "live"]), booleans, booleans, booleans)
def test_real_orders_need_the_flag_and_the_broker(mode, allow_live, broker, healthy):
    allowed = resolve_order_permission(mode, allow_live, broker, healthy)[0]
    assert allowed == (allow_live and broker and healthy)


# --- admission (R-ADMIT1) ----------------------------------------------------------------------------------------------------

evidence = st.builds(
    AdmissionEvidence, selection_pass=booleans, hold_pass=booleans, edge_pass=booleans, holdouts_spent=booleans, forward_ok_sessions=st.integers(0, 1500),
    no_data_share=st.floats(0.0, 1.0), mean_diff_vs_incumbent=st.one_of(st.none(), anything), guard_tripped=booleans,
    decay_state=st.sampled_from(["healthy", "watch", "decaying", "dead"]), forward_alpha_t=st.one_of(st.none(), anything), score=st.one_of(st.none(), anything),
)


def _generation(tier: str, stage: str) -> Generation:
    return Generation(id="g", kind="rule", tier=tier, stage=stage, born="2026-11-07", procedure_sha256="p")


@PROFILE
@given(st.sampled_from(STAGES), evidence)
def test_a_tier_none_generation_never_holds_capital_whatever_the_evidence(stage, ev):
    assert share_cap(_generation("none", stage), ev) == 0.0


@PROFILE
@given(st.sampled_from(["candidate", "frozen", "shadow"]), evidence)
def test_a_tier_none_generation_never_ramps(stage, ev):
    assert next_stage(_generation("none", stage), ev) in (stage, "rejected", "shadow") and next_stage(_generation("none", stage), ev) != "ramping"


@PROFILE
@given(st.sampled_from(TIERS), st.sampled_from(["candidate", "frozen", "shadow"]), evidence)
def test_a_generation_not_yet_on_the_book_holds_nothing(tier, stage, ev):
    assert share_cap(_generation(tier, stage), ev) == 0.0


@PROFILE
@given(st.sampled_from(TIERS), st.sampled_from(["retired", "rejected"]), evidence)
def test_retired_and_rejected_are_absorbing(tier, stage, ev):
    assert next_stage(_generation(tier, stage), ev) == stage and share_cap(_generation(tier, stage), ev) == 0.0


@PROFILE
@given(st.sampled_from(TIERS), st.sampled_from(["ramping", "active", "fading", "winding_down"]), evidence)
def test_a_guard_trip_or_a_dead_state_takes_a_generation_off_the_book(tier, stage, ev):
    if ev.guard_tripped or ev.decay_state == "dead":
        assert next_stage(_generation(tier, stage), ev) == "retired"


@PROFILE
@given(st.sampled_from(["tier2"]), st.sampled_from(["ramping", "active", "fading"]), evidence)
def test_a_tier_two_generation_is_capped_until_its_forward_alpha_lifts_it(tier, stage, ev):
    cap = share_cap(_generation(tier, stage), ev, tier2_cap=0.3)
    assert cap in (0.3, 1.0) and (cap == 1.0) == (ev.edge_pass or (ev.forward_alpha_t is not None and ev.forward_alpha_t == ev.forward_alpha_t and ev.forward_alpha_t >= 2.0
                                                                   and ev.forward_ok_sessions >= 252 and ev.no_data_share <= 0.10 and not ev.guard_tripped))


# --- sessions ---------------------------------------------------------------------------------------------------------------

iso_days = st.integers(0, 3000).map(lambda number: (pd.Timestamp("2015-01-01") + pd.Timedelta(days=number)).strftime("%Y-%m-%d"))


@PROFILE
@given(st.lists(iso_days, max_size=40, unique=True), iso_days)
def test_resolve_session_is_a_session_on_or_before_today_and_the_newest_such(sessions, now_date):
    sessions = sorted(sessions)
    result = resolve_session(sessions, now_date)
    eligible = [day for day in sessions if day <= now_date]
    if not eligible:
        assert result is None
    else:
        assert result == max(eligible) and result in sessions and result <= now_date
    assert resolve_session(sessions, now_date) == result, "a rerun resolves to the same session"


@PROFILE
@given(st.lists(iso_days, max_size=40, unique=True), iso_days, iso_days)
def test_an_override_is_honoured_only_if_it_is_a_session(sessions, now_date, override):
    assert resolve_session(sorted(sessions), now_date, override) == (override if override in sessions else None)


# --- generation shares ----------------------------------------------------------------------------------------------------

names = st.sampled_from(["a", "b", "c", "d"])
stages_strategy = st.dictionaries(names, st.sampled_from(["shadow", "ramping", "active", "fading", "winding_down", "retired"]), min_size=1)
states_strategy = st.dictionaries(names, st.sampled_from(["healthy", "watch", "decaying", "dead", "tripped"]))


@st.composite
def _valid_shares(draw):
    keys = draw(st.lists(names, min_size=1, max_size=4, unique=True))
    raw = [draw(st.floats(0.0, 1.0)) for _ in keys]
    total = sum(raw)
    scale = 1.0 / total if total > 1.0 else 1.0
    return {key: value * scale for key, value in zip(keys, raw)}


@PROFILE
@given(_valid_shares(), stages_strategy, states_strategy, st.dictionaries(names, st.floats(0.0, 1.0)), st.integers(1, 60))
def test_ladder_shares_are_never_negative_and_never_exceed_the_book(shares, stages, states, caps, sessions):
    out = update_generation_shares(shares, stages, states, caps, GlidePolicy(), sessions=sessions)
    assert all(0.0 <= value <= 1.0 + 1e-9 for value in out.values()) and sum(out.values()) <= 1.0 + 1e-6
    for name, stage in stages.items():
        if stage in ("shadow", "retired") or states.get(name) in ("dead", "tripped"):
            assert out.get(name, 0.0) == 0.0, "off the book means no share"


@PROFILE
@given(
    _valid_shares(), stages_strategy, states_strategy, st.dictionaries(names, st.floats(0.0, 1.0)),
    st.dictionaries(names, st.fixed_dictionaries({"ew_sharpe": st.one_of(st.none(), finite), "sessions": st.integers(0, 600), "prior": finite})), st.integers(1, 60),
)
def test_dynamic_shares_are_never_negative_and_never_exceed_the_book(shares, stages, states, caps, evidence_by_name, sessions):
    out = dynamic_generation_shares(shares, stages, states, evidence_by_name, caps, GlidePolicy(mode="dynamic"), sessions=sessions)
    assert all(0.0 <= value <= 1.0 + 1e-9 for value in out.values()) and sum(out.values()) <= 1.0 + 1e-6
    for name, stage in stages.items():
        if stage in ("shadow", "retired") or states.get(name) in ("dead", "tripped"):
            assert out.get(name, 0.0) == 0.0


# --- weights ------------------------------------------------------------------------------------------------------------------

@st.composite
def _book(draw):
    count = draw(st.integers(2, 8))
    tickers = [f"T{index}" for index in range(count)]
    classes = {ticker: draw(st.sampled_from(["crypto", "equity", "bond"])) for ticker in tickers}
    raw = pd.Series([draw(st.floats(-5.0, 5.0)) for _ in tickers], index=tickers)
    matrix = np.array([[draw(st.floats(-1.0, 1.0)) for _ in tickers] for _ in tickers])
    covariance = pd.DataFrame(matrix @ matrix.T * 1e-4 + np.eye(count) * 1e-5, index=tickers, columns=tickers)
    return raw, covariance, classes


@HEAVY
@given(_book())
def test_scale_and_cap_respects_every_cap_and_never_shorts_crypto(book):
    raw, covariance, classes = book
    settings_ = WeightSettings()
    weights = scale_and_cap(raw, covariance, classes, settings_)
    for ticker, weight in weights.items():
        assert math.isfinite(weight)
        assert abs(weight) <= settings_.name_cap_by_class.get(classes[ticker], settings_.name_cap) + 1e-9
        if classes[ticker] == "crypto":
            assert weight >= 0.0
    for name, cap in settings_.class_caps.items():
        assert sum(abs(weight) for ticker, weight in weights.items() if classes[ticker] == name) <= cap + 1e-9
    assert sum(abs(weight) for weight in weights.values()) <= settings_.gross_cap + 1e-9


@HEAVY
@given(st.integers(0, 10_000), st.integers(120, 190))
def test_a_changed_future_value_changes_no_earlier_weight_row(seed, cut):
    rng = np.random.default_rng(seed)
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-01", periods=220)]
    coins = ["BTCUSD", "ETHUSD", "AAAUSD", "BBBUSD", "CCCUSD"]
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0, 0.03, (220, 5)), axis=0)), index=days, columns=coins)
    signal = known.pct_change(20, fill_method=None)
    classes = {coin: "crypto" for coin in coins}
    base = signal_to_weights(signal, ResearchPanel(known, classes, {}, {}), kind="cross_sectional", rebalance_every=5, settings=WeightSettings(), start=days[60], end=days[-1], top_k=3)
    changed_known = known.copy()
    changed_known.iloc[cut:] *= rng.uniform(0.3, 3.0, (220 - cut, 5))
    changed = signal_to_weights(changed_known.pct_change(20, fill_method=None), ResearchPanel(changed_known, classes, {}, {}), kind="cross_sectional", rebalance_every=5, settings=WeightSettings(), start=days[60], end=days[-1], top_k=3)
    for day, row in base.items():
        if day < days[cut]:
            assert row == changed[day], f"{day} saw the future"


# --- the hash chain and finite-safe JSON ------------------------------------------------------------------------------------

def _chain(payloads: list[dict]) -> list[dict]:
    rows, previous = [], GENESIS_HASH
    for index, payload in enumerate(payloads):
        created = f"2026-11-07T00:00:{index:02d}+00:00"
        digest = compute_entry_hash(previous, "event", created, payload)
        rows.append({"prev_hash": previous, "hash": digest, "event_type": "event", "created_at": created, "payload": payload})
        previous = digest
    return rows


payloads = st.lists(st.dictionaries(st.text("abc", min_size=1, max_size=3), st.integers(-100, 100), max_size=3), min_size=1, max_size=8)


@PROFILE
@given(payloads)
def test_an_untouched_chain_verifies(items):
    assert verify_chain(_chain(items)) == (True, None)


@PROFILE
@given(payloads, st.data())
def test_any_edit_to_a_payload_is_detected_at_or_after_the_edit(items, data):
    rows = _chain(items)
    index = data.draw(st.integers(0, len(rows) - 1))
    rows[index] = {**rows[index], "payload": {**rows[index]["payload"], "tampered": 1}}
    valid, broken = verify_chain(rows)
    assert valid is False and broken is not None and broken <= index


@PROFILE
@given(payloads, st.data())
def test_deleting_a_middle_row_is_detected(items, data):
    if len(items) < 3:
        return
    rows = _chain(items)
    index = data.draw(st.integers(1, len(rows) - 2))
    del rows[index]
    assert verify_chain(rows)[0] is False


json_values = st.recursive(
    st.one_of(st.none(), booleans, anything, st.text(max_size=5)),
    lambda children: st.one_of(st.lists(children, max_size=4), st.dictionaries(st.text(max_size=4), children, max_size=4)), max_leaves=12,
)


@PROFILE
@given(json_values)
def test_sanitize_json_finite_is_finite_idempotent_and_serialisable(value):
    import json

    once = sanitize_json_finite(value)
    json.dumps(once, allow_nan=False)
    assert sanitize_json_finite(once) == once
