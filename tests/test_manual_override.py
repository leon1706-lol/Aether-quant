import json

from risk.manual_override import read_manual_trade_lock_override, write_manual_trade_lock_override


def _write_config(path, phase_v2_overrides=None) -> None:
    config = {
        "name": "Aether Quant",
        "phase1": {"universe": {"name": "test"}},
        "phase_v2": {"risk": {}, **(phase_v2_overrides or {})},
    }
    path.write_text(json.dumps(config, indent=4), encoding="utf-8")


def test_read_returns_none_when_key_absent(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)

    assert read_manual_trade_lock_override(config_path) is None


def test_read_returns_none_when_config_file_missing(tmp_path):
    assert read_manual_trade_lock_override(tmp_path / "does_not_exist.json") is None


def test_write_true_then_read_round_trips(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)

    write_manual_trade_lock_override(True, config_path)

    assert read_manual_trade_lock_override(config_path) is True


def test_write_false_then_read_round_trips(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)

    write_manual_trade_lock_override(False, config_path)

    assert read_manual_trade_lock_override(config_path) is False


def test_write_none_removes_the_key(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    write_manual_trade_lock_override(True, config_path)

    write_manual_trade_lock_override(None, config_path)

    assert read_manual_trade_lock_override(config_path) is None
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "manual_trade_lock_override" not in config["phase_v2"]["risk"]


def test_write_preserves_every_other_key_untouched(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path, phase_v2_overrides={"retraining": {"enabled": True, "min_observations": 500}})

    write_manual_trade_lock_override(True, config_path)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["name"] == "Aether Quant"
    assert config["phase1"]["universe"]["name"] == "test"
    assert config["phase_v2"]["retraining"] == {"enabled": True, "min_observations": 500}
    assert config["phase_v2"]["risk"]["manual_trade_lock_override"] is True


def test_write_creates_missing_phase_v2_and_risk_blocks(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"name": "Aether Quant"}), encoding="utf-8")

    write_manual_trade_lock_override(False, config_path)

    assert read_manual_trade_lock_override(config_path) is False
