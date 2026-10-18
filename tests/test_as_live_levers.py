"""scripts/as_live_levers.py: the score cache key separates model directories (V6.0.0 `ml_dir`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("as_live_levers", ROOT / "scripts" / "as_live_levers.py")
levers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(levers)


def test_scores_of_a_candidate_directory_never_share_the_installed_models_cache(tmp_path):
    dataset = tmp_path / "d.csv"
    dataset.write_text("x\n1\n", encoding="utf-8")
    config = {"phase_v2": {"rank_signal": {"heads": {"rank_20d": 1.0}}}}
    installed = levers._fingerprint(config, dataset)
    assert installed == levers._fingerprint(config, dataset, levers.ML_DIR)
    assert installed != levers._fingerprint(config, dataset, tmp_path / "ml" / "versions" / "candidate")
    assert installed != levers._fingerprint({"phase_v2": {"rank_signal": {"heads": {"rank_60d": 1.0}}}}, dataset)


def _synthetic_dataset(path, tickers, start="2021-11-01", end="2022-03-31", seed=3):
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    rows = []
    for date in pd.bdate_range(start, end):
        split = "validation" if date >= pd.Timestamp("2022-01-01") else "train"
        for index, ticker in enumerate(tickers):
            close = 100.0 + index + rng.normal(0, 1)
            rows.append({
                "date": date.strftime("%Y-%m-%d"), "ticker": ticker, "split": split, "training_eligible": True,
                "target_return_1d": rng.normal(0.0005 * (index % 5 - 2), 0.01), "target_rank_20d": rng.random(),
                "open": close * 0.999, "close": close, "high": close * 1.01, "low": close * 0.99, "volume": 2_000_000.0,
                "rolling_volatility_20d": 0.015, "liquidity_spread_proxy": 0.0005, "liquidity_log_dollar_volume": 19.0,
                "regime_risk_on": 1.0, "regime_risk_off": 0.0, "regime_signal_risk_score": 0.2, "regime_signal_confidence": 0.7,
                "topology_risk_normal": 1.0, "topology_risk_isolated": 0.0, "topology_risk_elevated": 0.0,
                "topology_correlation_strength": 0.6,
            })
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False)
    return frame


def test_v610_harness_warms_the_gate_on_earlier_rows_and_models_the_legacy_signal(tmp_path, monkeypatch):
    import json

    import numpy as np
    import pandas as pd

    import aq_cli

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    equities = [a["ticker"] for a in config["phase1"]["universe"]["assets"] if a.get("asset_class", a["security_type"]) == "equity"][:24]
    dataset = _synthetic_dataset(tmp_path / "d.csv", equities)
    probability = dataset[["date", "ticker"]].assign(final_probability_up=np.where(dataset["ticker"] == equities[12], 0.6, 0.5))
    probability.to_csv(tmp_path / "p.csv", index=False)
    monkeypatch.setattr(aq_cli, "_blend_raw_scores_for_dataset",
                        lambda frame, *a, **k: (np.asarray([hash(t) % 1000 / 1000 for t in frame["ticker"]], dtype=float), {}))
    # ml/model_weights.json is gitignored: a clean checkout (CI) has none, so the test brings its own.
    ml_stub = tmp_path / "ml"
    ml_stub.mkdir()
    (ml_stub / "model_weights.json").write_text(json.dumps({"training": {"decision_threshold": 0.5}}), encoding="utf-8")
    monkeypatch.setattr(levers, "CACHE_DIR", tmp_path / "cache")

    harness = levers.AsLiveHarness("validation", dataset_path=tmp_path / "d.csv", use_cache=False, gate_warmup_days=45,
                                   legacy_probability_path=tmp_path / "p.csv", ml_dir=ml_stub)
    assert harness.context_frame is not None and harness.context_frame["date"].max() < "2022-01-01"
    assert harness.frame["date"].min() >= "2022-01-01"
    assert levers.LEGACY_PROBABILITY_COLUMN in harness.frame.columns
    options = harness.v610_mechanisms()
    assert options["mid_cycle_member_updates"] and options["accrue_skipped_dates"] and options["max_active_positions"] == 12
    result = harness.as_live(gate="off", **options)
    components = result.per_date_component_returns
    assert set(components) == {"main_book", "legacy"} and set(components["legacy"]) == set(result.per_date)
    assert pd.Series(result.per_date_net_return).notna().all()


def test_a_run_starts_with_a_clean_rl_guard_so_identical_runs_match():
    def member_fn():
        pass

    member_fn.rl_state = {"history": [0.1, -0.2], "positions": {"AAA": (0.1, 1.0)}, "last_date": "2024-01-02", "allows": False}

    def legacy_fn():
        pass

    legacy_fn.rl_state = {"history": [1.0], "positions": {"BBB": (0.02, 1.0)}, "last_date": "2024-01-03", "allows": False}
    kwargs = {"member_weight_fn": member_fn, "legacy_component": {"weight_fn": legacy_fn}}
    levers.reset_member_state(kwargs)
    for function in (member_fn, legacy_fn):
        assert function.rl_state == {"history": [], "positions": {}, "last_date": None, "allows": True}
    levers.reset_member_state({})  # no mechanisms: nothing to reset, no error
