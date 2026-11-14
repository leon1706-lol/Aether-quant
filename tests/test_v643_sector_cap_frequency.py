"""scripts/v643_sector_cap_frequency.py (V6.6.6): replays logged rebalances through the book's neutrality, as shipped and
with the sector cap reapplied, and counts the rebalances that end above the cap."""

from __future__ import annotations

import json

from script_loader import load_script, run_script


def _run(tmp_path, *, cap=0.15, with_config=True):
    run_dir = tmp_path / "backtests" / "run_a"
    run_dir.mkdir(parents=True)
    config = {"phase_v2": {"portfolio_book": {"neutrality": {"sector_max_net_weight": cap, "dollar_neutral": False, "sector_neutral": False}}}, "phase6": {"risk": {"max_position_weight": 0.25}}}
    config_path = tmp_path / "run_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    entry = {"role": "long", "book_role_multiplier": 1.0, "predicted_rank_20d": 0.9}
    records = [
        {"date": "2024-01-02", "allocations": {"AAA": {**entry, "sector": "Tech"}, "BBB": entry, "CCC": {**entry, "role": "short", "predicted_rank_20d": 0.1}}},
        {"date": "2024-01-03", "allocations": {}},
    ]
    history = tmp_path / "book.jsonl"
    history.write_text("\n".join(json.dumps(record) for record in records) + "\n\n", encoding="utf-8")
    return run_dir, config_path if with_config else None, history


def _patch(monkeypatch, config_path, history):
    import evaluation.lean_attribution as attribution
    import features

    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: config_path)
    monkeypatch.setattr(attribution, "find_book_history_for_run", lambda run_dir, folder: history)
    monkeypatch.setattr(features, "load_sector_mapping", lambda config: {"BBB": "Tech", "CCC": "Energy"})


def test_a_tight_cap_counts_a_breach(tmp_path, monkeypatch):
    module = load_script("v643_sector_cap_frequency")
    run_dir, config_path, history = _run(tmp_path, cap=0.01)
    _patch(monkeypatch, config_path, history)
    row = module.replay_run(run_dir)
    assert row["run"] == "run_a" and row["rebalances"] == 1 and row["breaching_rebalances"] == 1 and row["worst_excess_over_cap"] > 0
    assert row["breach_share"] == 1.0 and row["mean_l1_change_with_reapply"] >= 0.0


def test_no_rebalance_gives_no_share_and_the_default_config_is_read(tmp_path, monkeypatch):
    module = load_script("v643_sector_cap_frequency")
    run_dir, _config_path, _history = _run(tmp_path, with_config=False)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    _patch(monkeypatch, None, empty)
    row = module.replay_run(run_dir)
    assert row["rebalances"] == 0 and row["breach_share"] is None and row["mean_l1_change_with_reapply"] is None
    assert row["config"].endswith("config.json")


def test_main_writes_every_run_and_runs_as_a_script(tmp_path, monkeypatch, capsys):
    run_dir, config_path, history = _run(tmp_path, cap=0.5)
    _patch(monkeypatch, config_path, history)
    out = tmp_path / "report" / "freq.json"
    assert run_script("v643_sector_cap_frequency", ["--run", str(run_dir), "--out", str(out)], monkeypatch) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["runs"][0]["breaching_rebalances"] == 0 and '"run": "run_a"' in capsys.readouterr().out
