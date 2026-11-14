"""scripts/promotion_gate_null_gate_scheme.py (V6.6.6): the era sign-flip fraction of the real scores against permuted
targets, on a small synthetic dataset."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from script_loader import Stop, load_script, run_script


def _datasets(root):
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2019-01-01", periods=320).strftime("%Y-%m-%d")
    tickers = [f"T{index:02d}" for index in range(12)]
    rows, scored = [], []
    for position, day in enumerate(dates):
        names = tickers[:5] if position % 40 == 7 else tickers  # a thin date the gate skips
        sign = 1.0 if (position // 65) % 2 == 0 else -1.0  # eras that flip sign
        for rank, ticker in enumerate(names):
            target = rng.normal()
            rows.append({"date": day, "ticker": ticker, "target_rank_20d": target})
            score = 1.0 if position == 3 else sign * target + 0.1 * rng.normal()  # one date of constant scores
            scored.append({"date": day, "ticker": ticker, "raw_blended_score": score})
    rows.append({"date": "2018-12-31", "ticker": "T00", "target_rank_20d": 0.0})
    (root / "ml" / "datasets").mkdir(parents=True)
    (root / "ml" / "evaluation").mkdir(parents=True)
    pd.DataFrame(rows).to_csv(root / "ml" / "datasets" / "full_dataset.csv", index=False)
    pd.DataFrame(scored).to_csv(root / "ml" / "evaluation" / "gate_sweep_scored.csv", index=False)


def test_the_null_distribution_and_the_real_fraction_are_reported(tmp_path, monkeypatch, capsys):
    module = load_script("promotion_gate_null_gate_scheme")
    _datasets(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "N_PERMS", 3)
    assert module.main() == 0
    summary = json.loads((tmp_path / "ml" / "evaluation" / "promotion_gate_null_gate_scheme.json").read_text(encoding="utf-8"))
    assert summary["n_perms"] == 3 and summary["n_eras_eligible_real"] >= 3 and summary["real_flip_fraction"] > 0
    assert 0.0 <= summary["null_flip_fraction"]["p50"] <= summary["null_flip_fraction"]["max"] <= 1.0
    assert summary["recommended_max"] <= 0.49 and '"n_perms": 3' in capsys.readouterr().out


def test_with_too_few_observations_no_era_is_eligible(tmp_path, monkeypatch):
    module = load_script("promotion_gate_null_gate_scheme")
    _datasets(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "N_PERMS", 1)
    monkeypatch.setattr(module, "ERA_MIN_OBSERVATIONS", 10_000)
    assert module.main() == 0
    summary = json.loads((tmp_path / "ml" / "evaluation" / "promotion_gate_null_gate_scheme.json").read_text(encoding="utf-8"))
    assert summary["n_eras_eligible_real"] == 0 and summary["real_flip_fraction"] == 0.0


def test_run_as_a_script_it_stops_at_its_first_read(monkeypatch):
    def stop(path, *args, **kwargs):
        raise Stop(str(path))

    monkeypatch.setattr(pd, "read_csv", stop)
    with pytest.raises(Stop, match="full_dataset.csv"):
        run_script("promotion_gate_null_gate_scheme", [], monkeypatch)
