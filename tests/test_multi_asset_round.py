"""V6.6.10's rules and verdicts (evaluation/multi_asset_round.py): R-LOSS1, R-INSTALL3 and R-FLIP1 decide from numbers alone."""

from __future__ import annotations

import math

import pytest

from evaluation import multi_asset_round as mar


def _score(ic, t=2.5):
    return {"class_ic": dict(zip(mar.CLASSES, ic, strict=True)), "hac_t": t}


def test_rules_payload_names_every_rule_and_the_trials():
    payload = mar.rules_payload(written="2026-11-17")
    assert set(payload["rules"]) == {"R-LOSS1", "R-ALPHA1", "R-BOOK2", "R-INSTALL3", "R-FLIP1"}
    assert payload["loss_trials"]["L0"] == "soft_spearman" and len(payload["loss_trials"]) == 6
    assert payload["flip_shares"] == {"model_book": 0.70, "crypto_sleeve": 0.30} and payload["phase"] == "v6610"


def test_mean_class_ic_needs_every_class():
    assert mar.mean_class_ic(_score([0.04, 0.02, 0.0, 0.02])["class_ic"]) == pytest.approx(0.02)
    assert mar.mean_class_ic({"equity": 0.1}) is None
    assert mar.mean_class_ic({**_score([0.1] * 4)["class_ic"], "bond": math.nan}) is None
    assert mar.mean_class_ic({**_score([0.1] * 4)["class_ic"], "bond": "x"}) is None


def test_loss_clauses_count_a_zero_ic_as_non_negative():
    verdict = mar.loss_clauses(_score([0.05, 0.0, 0.0, -0.01], t=2.0), control_mean=0.0)
    assert verdict == {"ic_margin": True, "classes": True, "hac_t": True}
    assert mar.loss_clauses(_score([0.05, -0.1, -0.1, 0.3], t=None), 0.0) == {"ic_margin": True, "classes": False, "hac_t": False}


def test_loss_gate_picks_the_best_survivor_and_names_each_failure():
    scores = {
        "L0": _score([0.02, 0.01, 0.0, 0.01]),
        "L1": _score([0.05, 0.03, 0.01, 0.03]),
        "L2": _score([0.06, 0.04, 0.02, 0.04]),
        "L3": _score([0.01, 0.01, 0.01, 0.01]),
        "L4": _score([0.06, -0.01, -0.02, 0.1], t=1.0),
    }
    gate = mar.loss_gate(scores)
    assert gate["survivors"] == ["L2", "L1"] and gate["best"] == "L2"
    assert gate["failed"] == {"L3": "ic_margin", "L4": "classes,hac_t"}
    assert mar.loss_gate({"L1": _score([0.1] * 4)})["failed"] == {"L1": "no control"}


def test_loss_verdict_keeps_the_control_unless_the_seeds_hold():
    scores = {"L0": _score([0.0] * 4), "L2": _score([0.05] * 4)}
    assert mar.loss_verdict({"L0": _score([0.0] * 4), "L1": _score([-0.1] * 4)})["kept"] == "L0"
    pending = mar.loss_verdict(scores)
    assert pending["kept"] == "L0" and "not been scored" in pending["reason"]
    held = mar.loss_verdict(scores, [_score([0.04] * 4), _score([0.03] * 4)])
    assert held["kept"] == "L2" and held["verified"] and held["seed_mean"]["class_ic"]["equity"] == pytest.approx(0.04)
    fell = mar.loss_verdict(scores, [_score([-0.02] * 4, t=0.5), _score([-0.02] * 4, t=0.5)])
    assert fell["kept"] == "L0" and not fell["verified"] and "ic_margin" in fell["reason"]


def test_seed_mean_keeps_a_missing_value_missing():
    mean = mar.seed_mean_score([_score([0.1] * 4, t=2.0), {"class_ic": {"equity": 0.1}, "hac_t": None}])
    assert mean["class_ic"]["equity"] == pytest.approx(0.1) and mean["class_ic"]["bond"] is None and mean["hac_t"] is None
    with pytest.raises(ValueError, match="no seed"):
        mar.seed_mean_score([])


def test_install3_needs_ic_a_clean_run_sharpe_and_drawdown():
    good = {"completed": True, "log_clean": True, "sharpe": 0.6, "max_drawdown": 0.1}
    assert mar.install3_verdict(new_ic=0.03, installed_ic=0.02, lean=good) == {"install": True, "failed": []}
    assert mar.install3_verdict(new_ic=None, installed_ic=0.02, lean=None)["failed"] == ["ic", "lean_run", "sharpe", "drawdown"]
    assert mar.install3_verdict(new_ic=0.03, installed_ic=0.02, lean={**good, "sharpe": 0.5, "max_drawdown": 0.2})["failed"] == ["sharpe", "drawdown"]


def test_flip_needs_every_clause():
    holdout = {"sharpe": 0.5, "max_drawdown": 0.1, "volatility": 0.08}
    lean = {"completed": True, "log_clean": True, "sharpe": 0.7, "volatility": 0.08, "max_drawdown": 0.1}
    parity = {"correlation": 0.97, "annual_return_gap": -0.005}
    flipped = mar.flip_verdict(survivor="k01", holdout=holdout, lean=lean, parity=parity)
    assert flipped["flip"] and flipped["shares"] == {"model_book": 0.70, "crypto_sleeve": 0.30} and flipped["sharpe_floor"] == pytest.approx(0.65)
    kept = mar.flip_verdict(survivor=None, holdout=None, lean=None, parity=None)
    assert not kept["flip"] and kept["failed"] == ["a", "b", "c", "d"] and kept["shares"]["model_book"] == 0.30
    assert mar.flip_verdict(survivor="k01", holdout=holdout, lean={**lean, "sharpe": 0.66}, parity=parity, pin_sharpe=0.63)["failed"] == ["c"]
    assert mar.flip_verdict(survivor="k01", holdout={**holdout, "volatility": 0.2}, lean=lean, parity={**parity, "annual_return_gap": 0.02})["failed"] == ["b", "d"]


def test_loss_score_reads_each_class_on_non_overlapping_dates():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    rows = []
    dates = [str(day.date()) for day in pd.bdate_range("2022-01-03", periods=120)]
    tickers = {f"E{i}": "equity" for i in range(5)} | {f"B{i}": "bond" for i in range(5)} | {f"C{i}": "crypto" for i in range(4)}
    for date in dates:
        for ticker, cls in tickers.items():
            target = rng.random()
            prediction = target if cls == "equity" else (-target if cls == "bond" else rng.random())
            rows.append({"date": date, "ticker": ticker, "prediction": prediction, "target": target})
    score = mar.loss_score(pd.DataFrame(rows), tickers)
    assert score["dates"] == 6 and score["class_ic"]["equity"] == pytest.approx(1.0) and score["class_ic"]["bond"] == pytest.approx(-1.0)
    assert score["class_ic"]["forex"] is None and score["hac_t"] is not None
    thin = mar.loss_score(pd.DataFrame(rows[:14]), tickers, stride=1)
    assert thin["hac_t"] is None and thin["pooled_ic"] is not None
    empty = mar.loss_score(pd.DataFrame(rows[:2]), tickers, stride=1)
    assert empty["pooled_ic"] is None and empty["class_ic"]["equity"] is None


def test_book2_lists_nine_counted_trials_two_controls_and_a_rules_payload():
    """R-BOOK2 (V6.6.10): the list R-ALPHA1 informed, as specs the model-book stages score, and the rules file written before any score."""
    from evaluation import multi_asset_round as mar
    from evaluation.model_book_research import GUARD

    trials, controls = mar.book2_trials(), mar.book2_controls()
    assert [spec.id for spec in trials] == [f"n{n:02d}" for n in range(1, 10)] and [spec.id for spec in controls] == ["n00", "core"]
    n02, n05 = trials[1], trials[4]
    assert n02.rebalance_every == 40 and n02.params["table"] == "ml_a2" and n02.params["optimizer"] == "inverse_vol"
    assert n05.params["kappa"] == 0.25 and n05.params["guard_classes"] == GUARD["guard_classes"] and n05.track == "B2" and controls[0].track == "B2C"
    payload = mar.book2_rules_payload(written="2026-11-20", alpha={"ml_a2": {"ic_20": 0.07}})
    assert payload["counted_trials"] == 9 and payload["trials"]["n06"] == {"optimizer": "tilted_core", "every": 20, "table": "ml_a2", "kappa": 0.5}
    assert payload["controls"]["n00"]["table"] == "ml_a1" and payload["alpha_basis"]["ml_a2"]["ic_20"] == 0.07 and "R-SLEEVE2" in payload["gate"]
