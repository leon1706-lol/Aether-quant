"""The never-read confirmation data of V6.5.0: a separate Lean data root with the universe's history before `data/` begins.

`data/` starts on 2013-01-02 and no phase has read anything older, so this root is the one window no rule was fitted on. It
is a separate folder, never a prepend: `data/` is one fixed Yahoo vintage (AGENTS.md rule 12), and adding older rows would
change what dataset builds read. Crypto did not trade then; tickers with no bars are left out and reported.

The script records only row counts and date spans. Nothing here looks at a price, and nothing may until verification.

    python scripts/build_pre2013_root.py --start 2002-01-01 --end 2013-01-02 --out data_pre2013
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_holdout_data import CLASS_KEY_BY_SECURITY_TYPE, yahoo_symbol  # noqa: E402

from data_pipeline.fetch import ASSET_CLASS_CONFIG  # noqa: E402
from data_pipeline.yfinance_backfill import (  # noqa: E402
    apply_price_overrides,
    fetch_yahoo_ohlcv,
    sanitize_ohlc,
    scale_for_lean,
    write_lean_zip,
)

SWEEP = {"ticker": "BIL", "security_type": "equity", "data_path": "data/equity/usa/daily/bil.zip"}
BENCHMARK_EXTRAS = (SWEEP,)
COPIED_DIRS = ("market-hours", "symbol-properties", "reference", Path("alternative") / "interest-rate")
EMPTY_DIRS = (Path("equity") / "usa" / "map_files", Path("equity") / "usa" / "factor_files")


def _asset_path(out: Path, asset: dict) -> Path:
    return out / Path(*Path(asset["data_path"]).parts[1:])


def build_root(
    config: dict, out: Path, *, start: str, end: str, source: Path = ROOT / "data",
    fetch_fn: Callable[[str, str, str], list[dict]] = fetch_yahoo_ohlcv, overrides: dict | None = None,
) -> dict:
    """Writes the root and returns its manifest: per ticker the row count, first and last date and the file's sha256; tickers
    left out with why. A failed fetch leaves a ticker out; the verification run simply has fewer names."""
    out = Path(out)
    for relative in COPIED_DIRS:
        target = out / relative
        if (source / relative).exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source / relative, target, dirs_exist_ok=True)
    for relative in EMPTY_DIRS:
        (out / relative).mkdir(parents=True, exist_ok=True)
    manifest: dict = {"start": start, "end": end, "tickers": {}, "left_out": {}}
    known = {str(asset["ticker"]) for asset in config["phase1"]["universe"]["assets"]}
    assets = list(config["phase1"]["universe"]["assets"]) + [asset for asset in BENCHMARK_EXTRAS if asset["ticker"] not in known]
    for asset in assets:
        ticker, security_type = str(asset["ticker"]), str(asset["security_type"])
        if security_type == "crypto":
            manifest["left_out"][ticker] = "crypto"
            continue
        if security_type not in CLASS_KEY_BY_SECURITY_TYPE:
            manifest["left_out"][ticker] = f"security type {security_type}"
            continue
        try:
            rows = fetch_fn(yahoo_symbol(asset), start, end)
        except Exception as error:  # one bad ticker must not lose the others
            manifest["left_out"][ticker] = f"fetch failed: {type(error).__name__}"
            continue
        rows, _ = apply_price_overrides(rows, (overrides or {}).get(ticker))
        rows, _ = sanitize_ohlc(rows)
        rows = [row for row in rows if row["date"].isoformat() < end]
        if not rows:
            manifest["left_out"][ticker] = "no bars in the window"
            continue
        path = _asset_path(out, asset)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fn = ASSET_CLASS_CONFIG[CLASS_KEY_BY_SECURITY_TYPE[security_type]].get("write_fn", write_lean_zip)
        write_fn(path, ticker, scale_for_lean(rows, security_type), merge_with_existing=False)
        manifest["tickers"][ticker] = {
            "rows": len(rows), "first": rows[0]["date"].isoformat(), "last": rows[-1]["date"].isoformat(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "security_type": security_type,
        }
    (out / "pre2013_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def universe_for_root(config: dict, manifest: dict) -> dict:
    """The config restricted to the tickers the root holds (no crypto, none listed later)."""
    import copy

    out = copy.deepcopy(config)
    keep = set(manifest["tickers"])
    out["phase1"]["universe"]["assets"] = [asset for asset in out["phase1"]["universe"]["assets"] if str(asset["ticker"]) in keep]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2002-01-01")
    parser.add_argument("--end", default="2013-01-02")
    parser.add_argument("--out", default="data_pre2013")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    overrides_path = ROOT / "data_pipeline" / "price_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    manifest = build_root(config, ROOT / args.out, start=args.start, end=args.end, overrides=overrides)
    print(f"{len(manifest['tickers'])} tickers written, {len(manifest['left_out'])} left out")
    for ticker, why in sorted(manifest["left_out"].items()):
        print(f"  {ticker}: {why}")
    spans = sorted((entry["first"], ticker) for ticker, entry in manifest["tickers"].items())
    print("latest starts:", spans[-10:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
