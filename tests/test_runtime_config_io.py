import json

from execution.runtime_config_io import read_runtime_mode


def _write_config(path, mode=None) -> None:
    config = {"phase_v2": {"runtime": {}}}
    if mode is not None:
        config["phase_v2"]["runtime"]["mode"] = mode
    path.write_text(json.dumps(config, indent=4), encoding="utf-8")


def test_read_runtime_mode_returns_observation_when_config_missing(tmp_path):
    assert read_runtime_mode(tmp_path / "does_not_exist.json") == "observation"


def test_read_runtime_mode_returns_observation_when_mode_absent(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)

    assert read_runtime_mode(config_path) == "observation"


def test_read_runtime_mode_returns_observation_for_unknown_mode(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path, mode="banana")

    assert read_runtime_mode(config_path) == "observation"


def test_read_runtime_mode_passes_through_valid_modes(tmp_path):
    for mode in ("backtest", "observation", "paper", "live"):
        config_path = tmp_path / f"config_{mode}.json"
        _write_config(config_path, mode=mode)

        assert read_runtime_mode(config_path) == mode
