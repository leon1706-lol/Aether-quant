"""scripts/v664_eos_repin.py: dropping the delisted coin touches nothing but that coin's asset entry (V6.6.4, Problems #311)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

repin = pytest.importorskip("v664_eos_repin")


def _config():
    return {"phase1": {"universe": {"assets": [{"ticker": "BTCUSD", "security_type": "crypto"}, {"ticker": "EOSUSD", "security_type": "crypto"}, {"ticker": "ETHUSD", "security_type": "crypto"}]}}, "other": {"kept": 1}}


def test_only_the_coins_asset_entry_goes():
    out = repin.drop_coin(_config())
    assert [asset["ticker"] for asset in out["phase1"]["universe"]["assets"]] == ["BTCUSD", "ETHUSD"]
    assert out["other"] == {"kept": 1}
    assert [asset["ticker"] for asset in _config()["phase1"]["universe"]["assets"]] == ["BTCUSD", "EOSUSD", "ETHUSD"], "the input is not changed"


def test_a_coin_that_is_not_there_is_an_error_and_not_a_silent_no_op():
    with pytest.raises(SystemExit):
        repin.drop_coin(_config(), "XYZUSD")


def test_the_real_config_round_trips_through_the_writer_it_uses():
    text = (ROOT / "config.json").read_text(encoding="utf-8")
    assert json.dumps(json.loads(text), indent=4) == text, "a rewrite of config.json changes only what was edited"
