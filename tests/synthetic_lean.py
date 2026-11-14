"""A small synthetic Lean world for tests of the run-based evaluation flows (V6.6.6, #359): a data root with daily zips, a run folder with its
result and order events, a per-run book history that carries member probabilities, and a config that names it all. Nothing here is real data."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

SESSIONS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=60)]
PROBABILITY_SOURCE = "direction_prob_multitask"


def stamp(day: str, hour: int = 20) -> float:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=timezone.utc).timestamp()


def write_zip(path: Path, closes, *, scale: int = 1, days=SESSIONS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"{day.replace('-', '')} 00:00,{int(p * scale)},{int(p * scale)},{int(p * scale)},{int(p * scale)},1000" for day, p in zip(days, closes))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{path.stem}.csv", rows)
    path.write_bytes(buffer.getvalue())


def build_world(root: Path, *, seed: int = 1) -> SimpleNamespace:
    """Returns root, run_dir, config, history_path, closes (ticker -> list)."""
    rng = np.random.default_rng(seed)
    closes = {
        "AAA": list(100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.01, len(SESSIONS))))),
        "BTCUSD": list(30000.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, len(SESSIONS))))),
        "BIL": list(np.linspace(91.0, 92.0, len(SESSIONS))),
    }
    write_zip(root / "data" / "equity" / "usa" / "daily" / "aaa.zip", closes["AAA"], scale=10000)
    write_zip(root / "data" / "equity" / "usa" / "daily" / "bil.zip", closes["BIL"], scale=10000)
    write_zip(root / "data" / "crypto" / "coinbase" / "daily" / "btcusd_trade.zip", closes["BTCUSD"])
    config = {
        "runtime": {"trading_days_per_year": 365},
        "phase1": {"universe": {"assets": [
            {"ticker": "AAA", "security_type": "equity", "asset_class": "equity", "data_path": "data/equity/usa/daily/aaa.zip"},
            {"ticker": "BTCUSD", "security_type": "crypto", "asset_class": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"},
        ]}},
        "phase_v2": {"cash_sweep": {"ticker": "BIL", "data_path": "data/equity/usa/daily/bil.zip"}},
    }
    nav = list(100000.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.004, len(SESSIONS)))))
    events, order_id = [], 0
    for index, day in enumerate(SESSIONS):
        if index % 10 == 0:
            for ticker, quantity in (("AAA", 50.0), ("BTCUSD", 0.1)):
                order_id += 1
                events.append({"orderId": order_id, "orderEventId": order_id, "symbolValue": ticker, "status": "filled", "time": stamp(day, 20 if ticker == "AAA" else 0),
                               "fillQuantity": quantity if (index // 10) % 2 == 0 else -quantity, "fillPrice": closes[ticker][index], "orderFeeAmount": 1.0, "direction": "buy"})
    result = {
        "statistics": {"Sharpe Ratio": "0.5", "Total Fees": "$10.00"},
        "charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamp(day), value, value, value, value] for day, value in zip(SESSIONS, nav)]}}},
                   "Benchmark": {"series": {"Benchmark": {"values": [[stamp(day), 400.0 + i] for i, day in enumerate(SESSIONS)]}}}},
        "orders": {str(event["orderId"]): {"securityType": 1 if event["symbolValue"] == "AAA" else 7, "type": 0} for event in events},
        "totalPerformance": {"closedTrades": []},
    }
    run_dir = root / "backtests" / "2024-04-01_00-00-00"
    run_dir.mkdir(parents=True)
    (run_dir / "1.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "1-order-events.json").write_text(json.dumps(events), encoding="utf-8")
    (run_dir / "log.txt").write_text("2024-04-01T00:00:00.1Z TRACE:: start\n", encoding="utf-8")
    history_dir = root / "visualization" / "book_history"
    history_dir.mkdir(parents=True)
    history_path = history_dir / "20240401T000000Z.jsonl"
    records = []
    for index in range(0, 30, 5):
        records.append({"date": SESSIONS[index], "allocations": {"AAA": {"role": "long", "weight": 0.1}, "BTCUSD": {"role": "long", "weight": 0.1}},
                        "member_probabilities": {"AAA": {PROBABILITY_SOURCE: 0.6}, "BTCUSD": {PROBABILITY_SOURCE: 0.4}}})
    history_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return SimpleNamespace(root=root, run_dir=run_dir, config=config, history_path=history_path, closes=closes, events=events, result=result)
