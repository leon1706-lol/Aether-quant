"""train_cross_sectional.py: walk-forward windows, the score guard, inputs and labels, and that both models can learn."""

import numpy as np
import pandas as pd
import pytest

import train_cross_sectional as module


def _frame(dates: int = 500, assets: int = 24, seed: int = 0) -> tuple[pd.DataFrame, list[str]]:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2017-01-02", periods=dates).strftime("%Y-%m-%d").tolist()
    rows = []
    for day in days:
        signal = rng.normal(size=assets)
        noise = rng.normal(size=assets)
        for asset in range(assets):
            rows.append({"date": day, "ticker": f"T{asset}", "_class": "a" if asset % 2 else "b", "f0": signal[asset], "f1": noise[asset], TARGET_NAME: signal[asset] + 0.3 * rng.normal()})
    frame = pd.DataFrame(rows)
    features = ["f0", "f1"]
    frame[features] = module.rank_inputs(frame, features)
    frame["_label"] = module.centred_label(frame, TARGET_NAME)
    return frame, features


TARGET_NAME = module.TARGET


def test_windows_expand_and_purge_the_label_horizon():
    dates = pd.bdate_range("2017-01-02", "2021-06-30").strftime("%Y-%m-%d").tolist()
    windows = module.annual_windows(dates, first_test_year=2019, purge_days=20)

    assert [window["test_start"] for window in windows] == ["2019-01-01", "2020-01-01", "2021-01-01"]
    assert windows[0]["train_end"] == "2018-12-11"
    assert all(window["train_end"] < window["test_start"] for window in windows)


def test_rank_inputs_are_per_date_and_class_and_fill_missing_with_the_middle():
    frame = pd.DataFrame({"date": ["d"] * 4, "_class": ["a", "a", "b", "b"], "x": [1.0, 2.0, 100.0, np.nan]})
    ranked = module.rank_inputs(frame, ["x"])["x"].to_numpy()

    assert ranked[0] == pytest.approx(0.0)
    assert ranked[1] == pytest.approx(0.5)
    assert ranked[2] == pytest.approx(0.5)
    assert ranked[3] == 0.0


def test_centred_label_has_zero_mean_per_group():
    frame, _ = _frame(dates=5)
    means = frame.groupby(["date", "_class"])["_label"].mean()
    assert means.abs().max() < 1e-5


def test_score_guard_never_scores_past_the_end():
    frame, features = _frame(dates=700)
    fake = lambda train, test, features, variant, seed: np.zeros(len(test))  # noqa: E731
    original = module.FITTERS["gbm"]
    module.FITTERS["gbm"] = fake
    try:
        scores = module.walk_forward_scores(frame, features, "gbm", "a", [1], score_end="2019-03-15")
    finally:
        module.FITTERS["gbm"] = original

    assert scores["date"].max() <= "2019-03-15"
    assert scores["date"].min() >= "2019-01-01"


def test_training_never_sees_the_test_span():
    frame, features = _frame(dates=700)
    seen = []

    def spy(train, test, features, variant, seed):
        seen.append((train["date"].max(), test["date"].min()))
        return np.zeros(len(test))

    original = module.FITTERS["gbm"]
    module.FITTERS["gbm"] = spy
    try:
        module.walk_forward_scores(frame, features, "gbm", "a", [1], score_end=None)
    finally:
        module.FITTERS["gbm"] = original
    assert seen and all(train_end < test_start for train_end, test_start in seen)


def _ic(frame: pd.DataFrame, scores: np.ndarray) -> float:
    return float(np.mean([
        np.corrcoef(pd.Series(scores[group.index]).rank(), group["_label"].rank())[0, 1]
        for _, group in frame.reset_index(drop=True).groupby("date")
    ]))


def test_gbm_learns_a_planted_signal():
    frame, features = _frame(dates=200)
    train, test = frame[frame["date"] < "2017-08-01"], frame[frame["date"] >= "2017-08-01"].reset_index(drop=True)
    predictions = module.fit_predict_gbm(train, test, features, "a", 1)
    assert _ic(test, predictions) > 0.5


def test_set_transformer_learns_a_planted_signal_and_ignores_asset_order():
    torch = pytest.importorskip("torch")
    frame, features = _frame(dates=120)
    train, test = frame[frame["date"] < "2017-05-01"], frame[frame["date"] >= "2017-05-01"].reset_index(drop=True)
    predictions = module.fit_predict_set_transformer(train, test, features, "a", 1, max_epochs=4, patience=4, learning_rate=3e-3, accumulate=4)
    assert _ic(test, predictions) > 0.3

    ranker = module._set_ranker(2, 2, module.SET_TRANSFORMER_VARIANTS["a"]).eval()
    x = torch.rand(1, 6, 2)
    c = torch.zeros(1, 6, dtype=torch.long)
    order = torch.randperm(6)
    with torch.no_grad():
        direct = ranker(x, c).squeeze(0)
        shuffled = ranker(x[:, order], c[:, order]).squeeze(0)
    assert torch.allclose(direct[order], shuffled, atol=1e-5)
