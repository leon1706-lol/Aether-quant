"""scripts/v664_write_rounds.py: both rule files are valid, loadable, hashed once and never overwritten (V6.6.4).

Needs round 3's stored rule file (`ml/evaluation/` is gitignored), so it skips in a checkout that lacks it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(not (ROOT / "ml" / "evaluation" / "v661" / "round3.json").exists(), reason="round 3's stored rules are not in this checkout")


def _written(tmp_path, monkeypatch):
    import v664_write_rounds as module

    monkeypatch.setattr(module, "OUT", tmp_path)
    assert module.main() == 0
    return module


def test_both_rounds_load_with_their_hashes_and_the_expected_trials(tmp_path, monkeypatch):
    from evaluation.research_round import clause_overrides, load_round

    _written(tmp_path, monkeypatch)
    crypto = load_round(tmp_path / "round4c.json", root=ROOT)
    equity = load_round(tmp_path / "round4e.json", root=ROOT)
    assert list(crypto.trials) == [f"x{n:02d}" for n in range(1, 15)] and crypto.cell == "CS" and crypto.track == "C"
    assert list(equity.trials) == ["q01", "q02", "q03", "q04", "q05", "q06", "q07", "e4", "e5"] and equity.cell == "S" and equity.track == "W"
    assert crypto.no_ic_clause == ("x09", "x10", "x11") and equity.no_ic_clause == ("e4", "e5")
    assert clause_overrides(crypto) == {"x09": {"no_ic": True}, "x10": {"min_live_names": 2, "no_ic": True}, "x11": {"min_live_names": 2, "no_ic": True}}
    assert clause_overrides(equity)["e4"] == {"min_live_names": 5, "no_ic": True} and clause_overrides(equity)["e5"] == {"min_live_names": 1, "no_ic": True}
    assert crypto.min_live_names == 12 and crypto.min_ic_names == 8 and equity.min_live_names == 150
    assert crypto.pbo_blocks == 16 and equity.pbo_blocks == 16 and "pooled >= 0.50" in crypto.bar and crypto.bar == equity.bar and "R-SLEEVE3" in crypto.rule


def test_every_trial_is_one_the_runner_can_build(tmp_path, monkeypatch):
    from evaluation.research_round import KINDS
    from evaluation.round_builders import BUILDERS

    module = _written(tmp_path, monkeypatch)
    for trials in (module.crypto_trials(), module.equity_trials()):
        for name, entry in trials.items():
            assert entry["kind"] in KINDS, name
            assert "builder" not in entry or entry["builder"] in BUILDERS, name
            assert entry.get("gate") in (None, "regime"), name


def test_a_rule_file_is_written_once(tmp_path, monkeypatch):
    module = _written(tmp_path, monkeypatch)
    for name in ("round4c", "round4e", "observers"):
        assert (tmp_path / f"{name}.sha256").read_text(encoding="utf-8").strip()
    with pytest.raises(FileExistsError):
        module.main()


def test_the_prior_columns_name_every_earlier_trial_the_pbo_needs(tmp_path, monkeypatch):
    import json

    _written(tmp_path, monkeypatch)
    crypto = json.loads((tmp_path / "round4c.json").read_text(encoding="utf-8"))
    equity = json.loads((tmp_path / "round4e.json").read_text(encoding="utf-8"))
    assert crypto["prior_columns"] == ["c1", "c2", "c3", "c4", "c5"]
    assert {"w04", "r03", "k09", "k10", "e3"} <= set(equity["prior_columns"]) and len(equity["prior_daily"]) == 3


def test_round4f_re_registers_the_two_voided_trials_unchanged_and_counts_them_separately(tmp_path, monkeypatch):
    from evaluation.research_round import clause_overrides, load_round

    module = _written(tmp_path, monkeypatch)
    assert module.main(["--only", "round4f"]) == 0
    spec = load_round(tmp_path / "round4f.json", root=ROOT)
    equity = load_round(tmp_path / "round4e.json", root=ROOT)
    assert list(spec.trials) == ["e4b", "e5b"] and spec.no_ic_clause == ("e4b", "e5b") and spec.cell == "S"
    for new, old in (("e4b", "e4"), ("e5b", "e5")):
        for key in ("kind", "rebalance_every", "min_live_names", "builder", "params", "universe"):
            assert spec.trials[new][key] == equity.trials[old][key], (new, key)
    assert clause_overrides(spec) == {"e4b": {"min_live_names": 5, "no_ic": True}, "e5b": {"min_live_names": 1, "no_ic": True}}
    assert "q07" in spec.prior_columns and "e4" not in spec.prior_columns and spec.bar == equity.bar and "voided" in spec.rule
    with pytest.raises(FileExistsError):
        module.main(["--only", "round4f"])
