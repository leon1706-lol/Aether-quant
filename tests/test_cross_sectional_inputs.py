"""features/cross_sectional_inputs.py (V6.4.4): the live (list) and offline (pandas) forms of the ranked model inputs must
agree exactly, and nothing non-finite may reach a model."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from features.cross_sectional_inputs import (
    CSR_SUFFIX,
    apply_cross_sectional_inputs,
    asset_class_by_ticker,
    asset_class_of,
    expand_input_names,
    rank_input_frame,
    rank_input_matrix,
    resolve_cross_sectional_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["a_scaled", "b_scaled", "regime_bull", "asset_class_equity"]


def _random_frame(seed: int) -> tuple[pd.DataFrame, list[str]]:
    rng = np.random.default_rng(seed)
    rows = []
    for day in range(3):
        for i in range(int(rng.integers(3, 14))):
            values = rng.integers(-3, 4, size=2).astype(float)  # small integers -> many ties
            if rng.random() < 0.15:
                values[int(rng.integers(0, 2))] = np.nan
            if rng.random() < 0.05:
                values[0] = np.inf
            rows.append({"date": f"2024-01-0{day + 1}", "ticker": f"T{i}", "a_scaled": values[0], "b_scaled": values[1],
                         "regime_bull": float(rng.integers(0, 2)), "asset_class_equity": 1.0})
    frame = pd.DataFrame(rows)
    groups = [str(rng.choice(["equity", "crypto"])) for _ in range(len(frame))]
    return frame, groups


@pytest.mark.parametrize("mode", ["replace", "append"])
def test_list_and_frame_forms_agree(mode):
    settings = {"group": "asset_class", "mode": mode, "min_group_size": 3}
    for seed in range(200):
        frame, groups = _random_frame(seed)
        offline = rank_input_frame(frame, NAMES, groups, settings)
        out_names = expand_input_names(NAMES, settings)
        for date, part in frame.groupby("date", sort=False):
            index = part.index.tolist()
            rows = part[NAMES].to_numpy(dtype=float).tolist()
            live_rows, live_names = rank_input_matrix(rows, NAMES, [groups[i] for i in index], settings)
            assert live_names == out_names
            expected = offline.loc[index, out_names].to_numpy(dtype=float)
            np.testing.assert_allclose(np.asarray(live_rows, dtype=float), expected, rtol=0, atol=1e-12)


def test_ranks_are_centred_with_average_ties_and_unranked_inputs_untouched():
    settings = {"mode": "replace", "min_group_size": 2}
    rows = [[1.0, 5.0, 1.0, 1.0], [2.0, 5.0, 0.0, 1.0], [2.0, 7.0, 1.0, 1.0], [3.0, float("nan"), 0.0, 1.0]]
    out, names = rank_input_matrix(rows, NAMES, ["equity"] * 4, settings)
    assert names == NAMES
    assert [row[0] for row in out] == pytest.approx([0.25 - 0.5, 0.625 - 0.5, 0.625 - 0.5, 1.0 - 0.5])
    assert [row[1] for row in out] == pytest.approx([0.5 - 0.5, 0.5 - 0.5, 1.0 - 0.5, 0.0])  # NaN -> centre
    assert [row[2] for row in out] == [1.0, 0.0, 1.0, 0.0]
    assert rows[3][1] != rows[3][1]  # input not mutated (still NaN)


def test_small_group_and_non_finite_give_the_centre_never_nan():
    settings = {"mode": "append", "min_group_size": 5}
    rows = [[1.0, math.inf, 0.0, 1.0], [2.0, 3.0, 0.0, 1.0]]
    out, names = rank_input_matrix(rows, NAMES, ["crypto", "crypto"], settings)
    assert names == NAMES + ["a_scaled" + CSR_SUFFIX, "b_scaled" + CSR_SUFFIX]
    assert all(math.isfinite(value) for row in out for value in row[:1] + row[2:4])
    assert [row[4:] for row in out] == [[0.0, 0.0], [0.0, 0.0]]
    assert out[0][1] == math.inf  # append mode keeps the raw input as it was


def test_resolve_defaults_and_disabled():
    assert resolve_cross_sectional_inputs(None) is None
    assert resolve_cross_sectional_inputs({"enabled": False}) is None
    assert resolve_cross_sectional_inputs({"enabled": True}) == {"group": "asset_class", "mode": "replace", "min_group_size": 5}
    assert resolve_cross_sectional_inputs({"enabled": True, "mode": "bad", "min_group_size": 0, "group": "x"}) == {
        "group": "asset_class", "mode": "replace", "min_group_size": 2}


def test_apply_is_a_no_op_when_off_and_uses_the_universe_classes_when_on():
    frame = pd.DataFrame({"date": ["2024-01-02"] * 4, "ticker": ["A", "B", "C", "D"],
                          "a_scaled": [1.0, 2.0, 3.0, 4.0], "b_scaled": [4.0, 3.0, 2.0, 1.0]})
    config = {"phase1": {"universe": {"assets": [{"ticker": "A", "asset_class": "equity"}, {"ticker": "B", "asset_class": "equity"},
                                                   {"ticker": "C", "security_type": "crypto"}, {"ticker": "D", "security_type": "crypto"}]},
                         "features": {"cross_sectional_inputs": {"enabled": False}}}}
    assert apply_cross_sectional_inputs(frame, config, ["a_scaled", "b_scaled"]) is frame
    config["phase1"]["features"]["cross_sectional_inputs"] = {"enabled": True, "min_group_size": 2}
    out = apply_cross_sectional_inputs(frame, config, ["a_scaled", "b_scaled"])
    assert out["a_scaled"].tolist() == [0.0, 0.5, 0.0, 0.5]  # ranked within equity {A,B} and crypto {C,D}
    assert frame["a_scaled"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_asset_class_mapping_covers_the_universe_and_matches_the_dataset_one_hots():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    classes = asset_class_by_ticker(config)
    assert len(classes) >= 100 and "unknown" not in classes.values()
    assert asset_class_of({"security_type": "equity", "asset_class": "bond"}) == "bond"
    dataset = ROOT / "ml" / "datasets" / "full_dataset.csv"
    if not dataset.exists():
        pytest.skip("no local dataset")
    header = pd.read_csv(dataset, nrows=0).columns
    one_hots = [column for column in header if column.startswith("asset_class_")]
    seen: dict[str, str] = {}
    for chunk in pd.read_csv(dataset, usecols=["ticker", *one_hots], chunksize=200_000):
        first = chunk.drop_duplicates("ticker")
        for _, row in first.iterrows():
            seen.setdefault(str(row["ticker"]), one_hots[int(np.argmax(row[one_hots].to_numpy(dtype=float)))][len("asset_class_"):])
        if len(seen) >= len(classes):
            break
    mismatched = {ticker: (cls, classes.get(ticker)) for ticker, cls in seen.items() if classes.get(ticker) != cls}
    assert mismatched == {}
