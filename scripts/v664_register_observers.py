"""Registers the forward observers of V6.6.4's pre-registered rule (`ml/evaluation/v664/observers.json`), at zero capital.

Time is the only evidence that can't be overfit and a missed session can't be backfilled, so the three highest-Sharpe trials of round 4C on cell CS (by that rule alone, a tie to the lower trial
number) are recorded forward from the first session, beside k09, which needs a host that has fundamentals. Each enters the registry as tier `none`, stage `shadow`: it is marked every session and
holds nothing, whatever its record (`share_cap`), and counts in N when it is judged. The universe is the USD coins Coinbase lists as trading today with a full 300-bar history, the most traded
first: a universe stated as such, not the cell's, so the forward record is of the trial as a live feed can compute it (marks only: no volume, no funding).

    python scripts/v664_register_observers.py            # prints what it would register
    python scripts/v664_register_observers.py --apply    # writes ml/generations/registry.json and lifecycle.jsonl
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation.forward_ledger import definition_sha256  # noqa: E402
from evaluation.generation_registry import Generation, append_lifecycle, load_registry, save_registry  # noqa: E402

SCORES = ROOT / "ml" / "evaluation" / "v664" / "selection_scores_round4c.json"
OBSERVERS_RULE = ROOT / "ml" / "evaluation" / "v664" / "observers.json"
PRODUCTS_URL = "https://api.exchange.coinbase.com/products"
CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
UNIVERSE_SIZE = 25
MIN_BARS = 295
STABLE_BASES = frozenset({"USDT", "USDC", "DAI", "PYUSD", "EURC", "GUSD", "PAX", "USDP", "TUSD", "USDS", "FDUSD", "BUSD", "UST", "LUSD", "FRAX", "RLUSD", "USD1", "USDG"})
CRYPTO_SETTINGS = {"target_vol": 0.07, "gross_cap": 1.4, "name_cap": 0.03, "class_caps": {"crypto": 0.15}, "name_cap_by_class": {"crypto": 0.05}}
# round 4C's trials as the forward feed can compute them: from marks alone
SIGNALS = {
    "x10": ("time_series", 5, {"builder": "breadth_timing", "params": {"window": 50, "floor": 0.5}}, None),
    "x12": ("cross_sectional", 20, {"builder": "low_vol", "params": {"window": 60}, "gate": "regime"}, 10),
    "x14": ("cross_sectional", 20, {"rank_mean": [{"builder": "low_vol", "params": {"window": 60}}, {"builder": "lottery_max", "params": {"window": 30}},
                                                    {"builder": "high_proximity", "params": {"window": 365, "min_periods": 180}}], "minimum": 3, "gate": "regime"}, 10),
    "x01": ("cross_sectional", 20, {"builder": "low_vol", "params": {"window": 60}}, 10),
    "x02": ("cross_sectional", 20, {"builder": "lottery_max", "params": {"window": 30}}, 10),
    "x05": ("cross_sectional", 20, {"builder": "high_proximity", "params": {"window": 365, "min_periods": 180}}, 10),
    "x06": ("cross_sectional", 5, {"builder": "short_reversal", "params": {"window": 7}}, 10),
    "x07": ("cross_sectional", 20, {"builder": "low_beta", "params": {"window": 60}}, 10),
    "x08": ("cross_sectional", 20, {"builder": "idio_vol", "params": {"window": 60}}, 10),
    "x11": ("time_series", 5, {"builder": "core_constant", "params": {}}, None),
}
# a trial the forward feed cannot compute from marks: volume, funding or a fitted model
NOT_FROM_MARKS = {"x03": "needs volume", "x04": "needs volume", "x09": "needs funding", "x13": "a fitted model needs its own host"}


def select_observers(scores: Mapping[str, Mapping], count: int = 3) -> list[str]:
    """The `count` x-trials with the highest pooled Sharpe, a tie to the lower trial number, skipping any the feed cannot compute (the next-highest takes its place)."""
    ranked = sorted((trial for trial, score in scores.items() if trial.startswith("x") and score.get("sharpe") is not None), key=lambda trial: (-float(scores[trial]["sharpe"]), trial))
    return [trial for trial in ranked if trial in SIGNALS][:count]


def looks_like_a_stablecoin(product_id: str, closes: list[float]) -> bool:
    """A stablecoin has no trend to rank: by name, or by a price that stayed within 2% of one dollar for the whole window."""
    if product_id.split("-")[0] in STABLE_BASES:
        return True
    values = sorted(float(close) for close in closes if close)
    return bool(values) and 0.97 <= values[len(values) // 2] <= 1.03 and (values[-1] - values[0]) < 0.02 * values[len(values) // 2]


def rank_coins(
    products: list[dict], volume_by_product: Mapping[str, float], bars_by_product: Mapping[str, int], size: int = UNIVERSE_SIZE, *, stable: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """USD products that are online and tradeable, with a full history and not a stablecoin, the most traded (30-day quote volume) first. Tickers in the project's own form (`BTCUSD`)."""
    eligible = [
        product["id"] for product in products
        if product.get("quote_currency") == "USD" and product.get("status") == "online" and not product.get("trading_disabled") and bars_by_product.get(product["id"], 0) >= MIN_BARS
        and product["id"] not in stable
    ]
    eligible.sort(key=lambda name: (-float(volume_by_product.get(name, 0.0)), name))
    return [name.replace("-", "") for name in eligible[:size]]


def build_definition(trial: str, tickers: list[str], anchor: str) -> dict:
    kind, every, signal, top_k = SIGNALS[trial]
    params: dict = {"signal": signal}
    if top_k:
        params["top_k"] = top_k
    return {
        "id": f"obs_{trial}", "kind": kind, "family": "crypto_signal", "universe": ["crypto"], "rebalance_every": every, "params": params, "tickers": list(tickers),
        "asset_class": {ticker: "crypto" for ticker in tickers}, "anchor_date": anchor, "cost_class": "crypto", "initial_weights": {}, "settings": dict(CRYPTO_SETTINGS),
        "data_sources": ["Coinbase public candles", "Yahoo chart API"],
    }


def k09_definition(anchor: str) -> dict:
    """k09 (quarterly accruals, IC t 2.60 in round 3) needs fundamentals, so a host dates its decisions (`aq cycle decide`); the runner only marks it."""
    from evaluation.wide_context import SECTORS

    return {
        "id": "obs_k09", "kind": "pooled", "family": "external_score", "universe": list(SECTORS), "rebalance_every": 20, "params": {"table": "k09", "top_k": None}, "tickers": [], "asset_class": {},
        "anchor_date": anchor, "cost_class": "equity", "initial_weights": {}, "settings": {"target_vol": 0.07, "gross_cap": 1.4, "name_cap": 0.03, "class_caps": {"crypto": 0.15}, "name_cap_by_class": {"crypto": 0.05}},
        "data_sources": ["SEC EDGAR (host-computed decisions)", "Yahoo chart API"],
    }


def fetch_universe(get_json: Callable[[str], object], pause: float = 0.35) -> tuple[list[str], dict]:
    products = [item for item in get_json(PRODUCTS_URL) if item.get("quote_currency") == "USD" and item.get("status") == "online" and not item.get("trading_disabled")]
    volume, bars, stable = {}, {}, set()
    for product in products:
        rows = get_json(CANDLES_URL.format(product=product["id"]))
        time.sleep(pause)
        bars[product["id"]] = len(rows)
        recent = rows[:30]  # newest first: [time, low, high, open, close, volume]
        volume[product["id"]] = sum(float(row[4]) * float(row[5]) for row in recent)
        if looks_like_a_stablecoin(product["id"], [row[4] for row in recent]):
            stable.add(product["id"])
    return rank_coins(products, volume, bars, stable=stable), {
        "products_online_usd": len(products), "with_full_history": sum(1 for count in bars.values() if count >= MIN_BARS), "stablecoins_left_out": sorted(stable),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--anchor", default=None, help="the last session before the first decision (default: the newest weekday)")
    args = parser.parse_args(argv)
    import forward_ledger

    scores = json.loads(SCORES.read_text(encoding="utf-8"))
    chosen = select_observers(scores)
    rule_sha = OBSERVERS_RULE.with_suffix(".sha256").read_text(encoding="utf-8").strip()
    today = datetime.datetime.now(datetime.timezone.utc)
    anchor = args.anchor or forward_ledger.session_for_outage(today)
    tickers, universe_note = fetch_universe(forward_ledger._get_json)
    definitions = {f"obs_{trial}": build_definition(trial, tickers, anchor) for trial in chosen}
    definitions["obs_k09"] = k09_definition(anchor)
    summary = {"chosen_x_trials": chosen, "rule_sha256": rule_sha, "anchor": anchor, "universe": tickers, "universe_note": universe_note, "ids": list(definitions)}
    print(json.dumps(summary, indent=1))
    if not args.apply:
        return 0
    registry_path = ROOT / "ml" / "generations" / "registry.json"
    registry = load_registry(registry_path)
    number = max(int(name[1:]) for name in registry) + 1
    lifecycle = ROOT / "ml" / "generations" / "lifecycle.jsonl"
    created = today.replace(microsecond=0).isoformat()
    for observer_id, definition in definitions.items():
        generation_id = f"g{number:04d}"
        number += 1
        needs = "fundamentals" if observer_id == "obs_k09" else None
        note = f"{observer_id}: a forward observer under observers.json (sha256 {rule_sha[:12]}), tier none, shadow, holds nothing; not verified."
        registry[generation_id] = Generation(
            id=generation_id, kind="rule", tier="none", stage="shadow", born=created[:10], procedure_sha256=definition_sha256(definition), definition=definition, needs=needs,
            expected_sharpe=0.0, note=note, admission={},
        )
        append_lifecycle(lifecycle, event="observer_registered", created_at=created, payload={"generation": generation_id, "observer": observer_id, "definition_sha256": definition_sha256(definition), "rule_sha256": rule_sha})
    save_registry(registry_path, registry)
    print(f"registered {len(definitions)} observers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
