"""Fuzz targets (V6.6.7, #363): each takes raw bytes, builds an input from them and checks an invariant.

`fuzz/run_fuzz.py` hands these to Atheris in CI (`.github/workflows/fuzz.yml`); `tests/test_fuzz_targets.py` drives the
same functions with hypothesis on any machine (Atheris has no Windows wheel). A target raises AssertionError when an
invariant breaks and lets through only the errors its function documents; anything else is a finding.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # run_fuzz.py starts in fuzz/, so the repo root is not on the path

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain  # noqa: E402
from evaluation.research_cells import record_holdout_read  # noqa: E402
from execution.accounts import OVERRIDE_KEYS, Account, apply_risk_overrides  # noqa: E402
from execution.secrets import SecretValue, parse_ref, redact, redact_url  # noqa: E402
from json_safety import dumps_json_safe, sanitize_json_finite  # noqa: E402
from monitoring.auth import Role, authorize, parse_users  # noqa: E402
from portfolio.target_weights import TargetWeightsConfig, rebalance_deltas  # noqa: E402
from risk.kill_switch import evaluate_kill_switch  # noqa: E402

_SPECIAL_FLOATS = (math.nan, math.inf, -math.inf, -0.0, 0.0, 1e308, -1e308, 5e-324, 1.0, -1.0)


class Bytes:
    """A deterministic reader over fuzz input: every call consumes bytes and never fails (an exhausted input reads zeros)."""

    def __init__(self, data: bytes) -> None:
        self.data = bytes(data)
        self.pos = 0

    def _take(self, count: int) -> bytes:
        chunk = self.data[self.pos:self.pos + count]
        self.pos += count
        return chunk + bytes(count - len(chunk))

    def int(self, lo: int, hi: int) -> int:
        span = hi - lo + 1
        return lo + int.from_bytes(self._take(2), "little") % span

    def bool(self) -> bool:
        return self._take(1)[0] & 1 == 1

    def float(self) -> float:
        tag = self._take(1)[0]
        if tag < 64:
            return _SPECIAL_FLOATS[tag % len(_SPECIAL_FLOATS)]
        if tag < 160:
            return struct.unpack("<d", self._take(8))[0]
        return (int.from_bytes(self._take(2), "little") - 32768) / 256.0

    def text(self, max_len: int = 24) -> str:
        length = self.int(0, max_len)
        alphabet = "abcXYZ019:/@._-*  " + chr(0) + chr(233) + chr(0x1F600)
        return "".join(alphabet[self._take(1)[0] % len(alphabet)] for _ in range(length))

    def choice(self, items: Sequence[Any]) -> Any:
        return items[self.int(0, len(items) - 1)]

    def value(self, depth: int = 0) -> Any:
        """A JSON-like value: numbers (non-finite included), strings, booleans, None, lists and dicts."""
        kind = self.int(0, 7 if depth < 3 else 4)
        if kind == 0:
            return None
        if kind == 1:
            return self.bool()
        if kind == 2:
            return self.int(-1000, 1000)
        if kind == 3:
            return self.float()
        if kind == 4:
            return self.text()
        if kind in (5, 6):
            return [self.value(depth + 1) for _ in range(self.int(0, 4))]
        return {self.text(8): self.value(depth + 1) for _ in range(self.int(0, 4))}


def fuzz_json_safety(data: bytes) -> None:
    """Sanitized output is strict JSON, sanitizing is idempotent and keeps every key."""
    value = Bytes(data).value()
    clean = sanitize_json_finite(value)
    json.dumps(clean, allow_nan=False)
    assert sanitize_json_finite(clean) == clean
    if isinstance(value, dict):
        assert set(clean) == set(value)
    assert json.loads(dumps_json_safe(value)) == json.loads(json.dumps(clean))


def fuzz_secret_refs(data: bytes) -> None:
    """parse_ref raises only ValueError; a redacted text and a redacted URL never show the secret."""
    reader = Bytes(data)
    text = reader.choice(["env:", "file:", "keyring:", "", "envx:"]) + reader.text(40)
    try:
        ref = parse_ref(text)
    except ValueError:
        pass
    else:
        assert ref.scheme in ("env", "file", "keyring") and ref.target
    secret = reader.text(16)
    message = reader.text(12) + secret + reader.text(12)
    if len(secret) >= 4:
        assert secret not in redact(message, [SecretValue(secret)])
    user, password, host = reader.text(8).replace("/", ""), reader.text(16).replace("/", ""), reader.text(12).replace("/", "").replace("@", "")
    url = f"redis://{user}:{password}@{host}/0"
    masked = redact_url(url)
    if len(password) >= 4 and password not in f"{user}:" and password not in host and password not in "redis://:***@/0":
        assert password not in masked, (url, masked)


def fuzz_hash_chain(data: bytes) -> None:
    """A chain built from the input verifies; changing one payload or dropping a middle row is caught at that row."""
    reader = Bytes(data)
    rows: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for index in range(reader.int(1, 6)):
        payload = sanitize_json_finite({"i": index, "v": reader.value(1)})
        created = f"2026-11-{reader.int(1, 28):02d}T00:00:00+00:00"
        row = {"prev_hash": previous, "event_type": reader.text(6) or "event", "created_at": created, "payload": payload}
        row["hash"] = compute_entry_hash(previous, row["event_type"], created, payload)
        rows.append(row)
        previous = row["hash"]
    assert verify_chain(rows) == (True, None)
    assert verify_chain(rows, expected_tail_hash=previous) == (True, None)
    target = reader.int(0, len(rows) - 1)
    tampered = [dict(row) for row in rows]
    tampered[target]["payload"] = {**tampered[target]["payload"], "tampered": True}
    assert verify_chain(tampered) == (False, target)
    if len(rows) >= 3:
        cut = reader.int(1, len(rows) - 2)
        assert verify_chain(rows[:cut] + rows[cut + 1:]) == (False, cut)


_BASE_PHASE_V2: dict[str, Any] = {
    "live": {"max_allowed_daily_drawdown_pct": 3.0, "max_allowed_total_drawdown_pct": 10.0},
    "dynamic_risk": {"max_leverage": 1.0},
    "reconciliation": {"max_tolerated_drift": 0.02},
    "risk": {"kill_switch": {"min_rolling_sharpe": -1.0, "max_drawdown_velocity_pct_per_bar": 2.0, "max_consecutive_losses": 8,
                             "max_slippage_divergence_bps": 50.0, "max_model_age_days": 30}},
    "runtime": {"mode": "paper", "allow_live_orders": False},
}


def _get(tree: dict[str, Any], dotted: str) -> Any:
    node: Any = tree
    for part in dotted.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def fuzz_account_overrides(data: bytes) -> None:
    """An account override never loosens a base limit, whatever its type; a refusal is a ValueError."""
    reader = Bytes(data)
    overrides = {reader.choice(sorted(OVERRIDE_KEYS)): reader.choice([reader.float(), reader.int(-50, 50), reader.bool(), reader.text(4), None])
                 for _ in range(reader.int(1, 4))}
    account = Account("acct1", risk_overrides=overrides, mode=reader.choice([None, "observation", "paper", "live"]))
    try:
        out = apply_risk_overrides(_BASE_PHASE_V2, account)
    except ValueError:
        return
    for key, direction in OVERRIDE_KEYS.items():
        before, after = _get(_BASE_PHASE_V2, key), _get(out, key)
        if direction == "false":
            assert after is before or after is False, key
        elif isinstance(before, (int, float)) and not isinstance(before, bool):
            assert isinstance(after, (int, float)) and not isinstance(after, bool) and after == after, (key, after)
            assert after <= before if direction == "lower" else after >= before, (key, before, after)
    assert {"observation": 1, "paper": 2, "live": 3}[_get(out, "runtime.mode")] <= 2


def fuzz_users_doc(data: bytes) -> None:
    """A users file of any shape parses or raises ValueError; parsed users never act above their role or scope."""
    reader = Bytes(data)
    rows = [reader.value(1) for _ in range(reader.int(0, 3))]
    if reader.bool():
        rows.append({"name": reader.text(8), "role": reader.choice(["viewer", "operator", "admin", reader.text(5)]),
                     "salt": "0" * 32, "token_hash": "a" * 64, "accounts": reader.value(1)})
    try:
        users = parse_users({"users": rows})
    except ValueError:
        return
    account = reader.text(5) or None
    for user in users:
        for required in Role:
            allowed = authorize(user, required, account, auth_required=True)
            assert not allowed or (int(user.role) >= int(required) and user.may_access(account))
    assert not authorize(None, Role.OPERATOR, account, auth_required=reader.bool())


_KILL_SWITCH_CONFIG = {"enabled": True, "evaluation_bars": 20, "min_bars_for_sharpe": 10, "min_rolling_sharpe": -1.0,
                       "max_drawdown_velocity_pct_per_bar": 2.0, "max_consecutive_losses": 6, "max_slippage_divergence_bps": 40.0,
                       "max_model_age_days": 30, "min_live_rank_ic": -0.2}


def fuzz_kill_switch(data: bytes) -> None:
    """Any metrics, finite or not, give a decision (never an exception) whose report is strict JSON once sanitized; a
    finite velocity above the ceiling always trips."""
    reader = Bytes(data)
    metrics = {
        "recent_bar_returns": [reader.float() for _ in range(reader.int(0, 30))],
        "drawdown_velocity_pct_per_bar": reader.choice([None, reader.float()]),
        "live_rank_ic": reader.choice([None, reader.float()]),
        "consecutive_losses": reader.choice([None, reader.float(), reader.int(0, 20)]),
        "slippage_divergence_bps": reader.choice([None, reader.float()]),
        "model_age_days": reader.choice([None, reader.float()]),
        "rolling_sharpe_tripped_last_bar": reader.bool(),
        "rolling_sharpe_below_run_last_bar": reader.int(0, 5),
    }
    decision = evaluate_kill_switch(metrics, dict(_KILL_SWITCH_CONFIG))
    json.dumps(sanitize_json_finite(decision.to_dict()), allow_nan=False)
    velocity = metrics["drawdown_velocity_pct_per_bar"]
    if isinstance(velocity, float) and math.isfinite(velocity) and velocity > _KILL_SWITCH_CONFIG["max_drawdown_velocity_pct_per_bar"]:
        assert decision.tripped, metrics


def fuzz_rebalance(data: bytes) -> None:
    """Orders are finite, never overshoot the target weight, and a `reduces` order only shrinks a position."""
    reader = Bytes(data)
    tickers = ["AAA", "BBB", "CCC", "DDD"][: reader.int(1, 4)]
    held = {ticker: reader.choice([0.0, reader.float(), float(reader.int(-50, 50))]) for ticker in tickers if reader.bool()}
    prices = {ticker: reader.choice([reader.float(), float(reader.int(1, 500))]) for ticker in tickers}
    target = {ticker: reader.choice([reader.float(), reader.int(-100, 100) / 100.0]) for ticker in tickers if reader.bool()}
    nav = reader.choice([reader.float(), float(reader.int(1, 10**6))])
    lots = {ticker: reader.choice([1.0, 0.0, reader.float(), 0.001]) for ticker in tickers if reader.bool()}
    config = TargetWeightsConfig()
    orders = rebalance_deltas(held, prices, nav, target, config, lot_size=lots)
    finite = lambda value, default=0.0: value if isinstance(value, (int, float)) and math.isfinite(value) else default  # noqa: E731
    seen_growth = False
    for ticker, delta in orders:
        assert math.isfinite(delta) and delta != 0.0, (ticker, delta)
        units, price, wanted = finite(held.get(ticker, 0.0)), finite(prices[ticker]), finite(target.get(ticker, 0.0))
        after = units + delta
        shrinks = units != 0.0 and abs(after) <= abs(units) and after * units >= 0.0
        if not shrinks:
            seen_growth = True
        else:
            assert not seen_growth, ("a reduction sorted after an order that adds exposure", orders)
        nav_value = finite(nav)
        if wanted != 0.0 and nav_value > 0.0 and price > 0.0:
            current, post = units * price / nav_value, after * price / nav_value
            low, high = min(current, wanted), max(current, wanted)
            slack = 1e-9 * max(1.0, abs(low), abs(high))
            assert low - slack <= post <= high + slack, (ticker, current, wanted, post)


def fuzz_holdout_ledger(data: bytes) -> None:
    """A ledger line that names a cell, in any shape, never lets that cell be read again: the record either refuses with
    PermissionError or ValueError (a corrupt ledger fails closed) or the cell was never named."""
    reader = Bytes(data)
    cells = ("V1", "V2", "P", "CV")
    lines: list[str] = []
    named: set[str] = set()
    for _ in range(reader.int(0, 4)):
        shape = reader.int(0, 4)
        cell = reader.choice(cells)
        if shape == 0:
            entry: Any = {"candidate": "c", "cells": [cell]}
        elif shape == 1:
            entry = {"candidate": "c", "cells": cell}
        elif shape == 2:
            entry = [cell]
        elif shape == 3:
            entry = {"candidate": "c", "cells": [cell, reader.value(1)]}
        else:
            entry = reader.value(1)
        named |= {cell} if shape < 4 else set()
        text = json.dumps(entry)
        lines.append(text[: reader.int(1, len(text))] if reader.int(0, 9) == 0 else text)
    wanted = (reader.choice(cells),)
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "holdout_ledger.jsonl"
        ledger.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        try:
            record_holdout_read(ledger, candidate="fuzz", cells=wanted, digest="d", created_at="2026-11-14T00:00:00Z")
        except (PermissionError, ValueError):
            return
    assert wanted[0] not in named, (lines, wanted)


TARGETS: dict[str, Callable[[bytes], None]] = {
    "json_safety": fuzz_json_safety,
    "secret_refs": fuzz_secret_refs,
    "hash_chain": fuzz_hash_chain,
    "account_overrides": fuzz_account_overrides,
    "users_doc": fuzz_users_doc,
    "kill_switch": fuzz_kill_switch,
    "rebalance": fuzz_rebalance,
    "holdout_ledger": fuzz_holdout_ledger,
}
