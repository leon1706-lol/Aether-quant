"""evaluation/leakage_audit.py (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.leakage_audit import audit_leakage, identity_check, label_shuffle_check, tail_nan_check


def _frame(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    dates = pd.date_range("2020-01-01", periods=200, freq="D").strftime("%Y-%m-%d")
    for t, date in enumerate(dates):
        future = rng.normal(size=30)
        ranks = pd.Series(future).rank(pct=True).to_numpy()
        for i in range(30):
            rows.append({"date": date, "ticker": f"T{i}", "split": "train" if t < 120 else "validation",
                         "honest": rng.normal(), "leaky": future[i] + 0.1 * rng.normal(),
                         "forward_window": np.nan if t >= 190 else rng.normal(), "target_rank_20d": ranks[i],
                         "asset_class_equity": float(i % 2 == 0), "asset_class_crypto": float(i % 2 == 1)})
    return pd.DataFrame(rows)


def test_tail_nan_flags_a_forward_looking_feature_only():
    report = tail_nan_check(_frame(), ["honest", "forward_window"], horizon=10)
    assert report["forward_window"]["flag"] is True
    assert report["honest"]["flag"] is False


def test_label_shuffle_leaves_no_feature_ic():
    report = label_shuffle_check(_frame(), ["honest", "leaky"], "target_rank_20d")
    assert not any(row["flag"] for row in report.values())


def test_audit_flags_the_implausible_feature():
    report = audit_leakage(_frame(), feature_columns=["honest", "leaky", "forward_window"], horizon=10,
                           class_columns=("asset_class_equity", "asset_class_crypto"))
    assert "leaky" in report["flagged"] and "forward_window" in report["flagged"]
    assert "honest" not in report["flagged"]
    assert report["single_feature_ic"]["leaky"]["ic"] > 0.5


def test_identity_prior_has_no_ic_when_targets_are_iid():
    frame = _frame(seed=3)
    out = identity_check(frame[frame["split"] == "train"], frame[frame["split"] == "validation"], "target_rank_20d",
                         class_columns=("asset_class_equity", "asset_class_crypto"), model_score_column="leaky")
    assert abs(out["identity_prior_ic"]) < 0.05
    assert out["model_minus_identity"] > 0.5
    assert "class_prior_ic" in out
