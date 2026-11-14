"""A synthetic project root for running `train.py` end to end on a CPU (V6.6.6, #359): Lean-format daily zips for twelve assets (equity, bond ETFs, crypto, forex), a config trimmed to them with
windows over 2018-2019, and `repoint()`, which moves every module-level path under the repo root to the temporary root so no run touches the real `data/` or `ml/`."""

from __future__ import annotations

import copy
import datetime
import json
import zipfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]

EQUITIES = ["SPY", "AAPL", "MSFT", "XOM", "JPM", "KO"]
BONDS = ["TLT", "IEF"]
CRYPTO = ["BTCUSD", "ETHUSD"]
FOREX = ["EURUSD", "GBPUSD"]
START = datetime.date(2018, 1, 1)
END = datetime.date(2019, 12, 31)
WINDOWS = {"training": {"start": "2018-01-01", "end": "2018-12-31"}, "validation": {"start": "2019-01-01", "end": "2019-05-31"}, "backtest": {"start": "2019-06-01", "end": "2019-09-30"},
           "holdout": {"start": "2019-10-01", "end": "2019-12-31"}, "purge_label_horizon_days": 5}


def days(weekdays_only: bool) -> list[datetime.date]:
    out = []
    day = START
    while day <= END:
        if not weekdays_only or day.weekday() < 5:
            out.append(day)
        day += datetime.timedelta(days=1)
    return out


def path_walk(seed: int, count: int, start: float, vol: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(rng.normal(0.0003, vol, count)))


def write_zip(path: Path, member: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, "\n".join(lines) + "\n")


def bar(close: float, previous: float, rng) -> tuple[float, float, float, float]:
    high = max(close, previous) * (1.0 + abs(rng.normal(0, 0.004)))
    low = min(close, previous) * (1.0 - abs(rng.normal(0, 0.004)))
    return previous, high, low, close


def write_asset(root: Path, asset: dict, seed: int, first_day: datetime.date | None = None) -> None:
    kind = asset["security_type"]
    dates = [day for day in days(kind == "equity" or kind == "forex") if first_day is None or day >= first_day]
    start = 100.0 + seed * 7 if kind != "forex" else 1.1
    closes = path_walk(seed, len(dates), start, 0.012 if kind != "forex" else 0.003)
    rng = np.random.default_rng(seed + 100)
    lines = []
    previous = closes[0]
    for date, close in zip(dates, closes):
        open_, high, low, close = bar(float(close), float(previous), rng)
        previous = close
        stamp = date.strftime("%Y%m%d") + " 00:00"
        volume = float(abs(rng.normal(2_000_000, 400_000)))
        if kind == "equity":
            lines.append(f"{stamp},{int(open_ * 10000)},{int(high * 10000)},{int(low * 10000)},{int(close * 10000)},{volume}")
        elif kind == "crypto":
            lines.append(f"{stamp},{open_},{high},{low},{close},{volume}")
        else:
            quote = f"{open_},{high},{low},{close},0"
            lines.append(f"{stamp},{quote},{quote}")
    write_zip(root / asset["data_path"], Path(asset["data_path"]).stem + ".csv", lines)


def assets() -> list[dict]:
    out = []
    for ticker in EQUITIES + BONDS:
        entry = {"ticker": ticker, "security_type": "equity", "market": "usa", "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip", "available_from": "2018-01-01", "available_to": "2019-12-31"}
        if ticker in BONDS:
            entry["asset_class"] = "bond"
            entry["bond_metadata"] = {"duration_proxy_years": 17.0 if ticker == "TLT" else 7.5, "yield_curve_bucket": "long_duration", "credit_quality": "treasury"}
        out.append(entry)
    for ticker in CRYPTO:
        out.append({"ticker": ticker, "security_type": "crypto", "market": "coinbase", "data_path": f"data/crypto/coinbase/daily/{ticker.lower()}_trade.zip", "available_from": "2018-01-01", "available_to": "2019-12-31"})
    for ticker in FOREX:
        out.append({"ticker": ticker, "security_type": "forex", "market": "oanda", "data_path": f"data/forex/oanda/daily/{ticker.lower()}.zip", "available_from": "2018-01-01", "available_to": "2019-12-31"})
    return out


def merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def build_config(**overrides) -> dict:
    config = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    universe = config["phase1"]["universe"]
    universe["assets"] = assets()
    universe["common_window"] = {"start": "2018-01-01", "end": "2019-12-31"}
    config["phase1"]["windows"] = copy.deepcopy(WINDOWS)
    config["phase1"]["target"]["ranking"]["min_universe_size"] = 5
    config["phase3"]["training"].update({"epochs": 10, "patience": 1, "batch_size": 128})
    config["phase3"]["model"]["hidden_layers"] = [8]
    retraining = config["phase_v2"]["retraining"]
    small = {"epochs": 2, "patience": 2, "hidden_layers": [8], "batch_size": 128, "min_train_rows": 100, "min_validation_rows": 20, "min_backtest_rows": 20, "min_best_epoch": 1}
    retraining["multitask_training"].update(small)
    retraining["sequence_training"].update({**small, "window_size": 5, "channels": [8, 8]})
    merge(config, overrides)
    return config


def build_root(tmp_path: Path, late_assets: dict[str, datetime.date] | None = None, **config_overrides) -> Path:
    root = tmp_path / "project"
    (root / "ml").mkdir(parents=True)
    (root / "data").mkdir()
    config = build_config(**config_overrides)
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    for index, asset in enumerate(config["phase1"]["universe"]["assets"]):
        write_asset(root, asset, index + 1, (late_assets or {}).get(asset["ticker"]))
    return root


def repoint(monkeypatch, module, root: Path) -> None:
    """Every module-level `Path` under the real repo root, and every function default that is one, moves to the same place under `root`."""
    real = module.ROOT if hasattr(module, "ROOT") else REPO

    def moved(value):
        if isinstance(value, Path):
            try:
                return root / value.relative_to(real)
            except ValueError:
                return value
        return value

    for name, value in list(vars(module).items()):
        if isinstance(value, Path):
            monkeypatch.setattr(module, name, moved(value))
        elif callable(value) and getattr(value, "__module__", None) == module.__name__ and hasattr(value, "__defaults__"):
            if value.__defaults__ and any(isinstance(item, Path) for item in value.__defaults__):
                monkeypatch.setattr(value, "__defaults__", tuple(moved(item) for item in value.__defaults__))
            if value.__kwdefaults__ and any(isinstance(item, Path) for item in value.__kwdefaults__.values()):
                monkeypatch.setattr(value, "__kwdefaults__", {key: moved(item) for key, item in value.__kwdefaults__.items()})
    if hasattr(module, "ROOT"):
        monkeypatch.setattr(module, "ROOT", root)
