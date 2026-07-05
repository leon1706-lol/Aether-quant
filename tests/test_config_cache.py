import os

from execution.config_cache import read_cached


def _counting_loader(calls: list):
    def loader(path):
        calls.append(path)
        return path.read_text(encoding="utf-8")

    return loader


def _bump_mtime(path) -> None:
    """Forces a detectable mtime change regardless of filesystem timestamp
    resolution, so the test doesn't flake on fast successive writes."""
    current = os.stat(path).st_mtime
    os.utime(path, (current + 1.0, current + 1.0))


def test_loader_invoked_once_when_file_untouched(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("v1", encoding="utf-8")
    calls: list = []
    loader = _counting_loader(calls)

    first = read_cached(config_path, loader)
    second = read_cached(config_path, loader)

    assert first == "v1"
    assert second == "v1"
    assert len(calls) == 1


def test_loader_invoked_again_after_mtime_changes(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("v1", encoding="utf-8")
    calls: list = []
    loader = _counting_loader(calls)

    read_cached(config_path, loader)
    config_path.write_text("v2", encoding="utf-8")
    _bump_mtime(config_path)
    second = read_cached(config_path, loader)

    assert second == "v2"
    assert len(calls) == 2


def test_two_different_loaders_on_the_same_path_do_not_collide(tmp_path):
    """Regression guard for the exact bug caught by the Lean backtest
    integration test: main.py reads several distinct config keys
    (manual_trade_lock_override, paper_trading, ...) from the same
    config.json in the same bar. Keying the cache by path alone let one
    reader's cached value leak into a different reader's result."""
    config_path = tmp_path / "config.json"
    config_path.write_text("shared file content", encoding="utf-8")

    def loader_a(path):
        return {"kind": "a"}

    def loader_b(path):
        return None

    result_b_first = read_cached(config_path, loader_b)
    result_a = read_cached(config_path, loader_a)
    result_b_second = read_cached(config_path, loader_b)

    assert result_b_first is None
    assert result_a == {"kind": "a"}
    assert result_b_second is None


def test_missing_file_passes_through_to_loader_uncached(tmp_path):
    config_path = tmp_path / "does_not_exist.json"
    calls: list = []

    def loader(path):
        calls.append(path)
        return "fallback"

    first = read_cached(config_path, loader)
    second = read_cached(config_path, loader)

    assert first == "fallback"
    assert second == "fallback"
    assert len(calls) == 2
