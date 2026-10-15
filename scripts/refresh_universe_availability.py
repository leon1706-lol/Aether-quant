"""Set each universe asset's `available_from` / `available_to` in config.json to the first / last bar of its zip.

The fields are metadata (nothing in the trading or training path reads them); after the V5.8.0 data rewrite they still
said 2021-03-31. Dry run by default; `--apply` rewrites only those two values in place (the rest of the file's text is
left byte-identical).

    python scripts/refresh_universe_availability.py [--config config.json] [--apply]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def zip_date_range(zip_path: Path) -> tuple[str, str] | None:
    """First and last bar date (YYYY-MM-DD) of a daily Lean zip, or None when it is missing or empty."""
    if not zip_path.is_file():
        return None
    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist() if name.endswith(".csv")]
        if not members:
            return None
        lines = [line for line in archive.read(members[0]).decode("utf-8").splitlines() if line.strip()]
    if not lines:
        return None

    def _date(line: str) -> str:
        stamp = line.split(",", 1)[0].strip()[:8]
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"

    return _date(lines[0]), _date(lines[-1])


def planned_updates(config: dict, root: Path) -> list[dict]:
    updates = []
    for asset in config["phase1"]["universe"]["assets"]:
        found = zip_date_range(root / asset["data_path"])
        if found is None:
            continue
        first, last = found
        if asset.get("available_from") != first or asset.get("available_to") != last:
            updates.append({"ticker": asset["ticker"], "from": (asset.get("available_from"), first), "to": (asset.get("available_to"), last)})
    return updates


def _enclosing_object(text: str, position: int) -> tuple[int, int]:
    """Span of the JSON object that contains `position` (assets hold nested objects, so braces are counted)."""
    depth, start = 0, position
    while start > 0:
        start -= 1
        if text[start] == "}":
            depth += 1
        elif text[start] == "{":
            if depth == 0:
                break
            depth -= 1
    depth, end = 0, start
    for end in range(start, len(text)):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                break
    return start, end + 1


def apply_updates(text: str, updates: list[dict]) -> str:
    """Rewrite the two top-level date values of each updated asset's object, found by its unique `"ticker": "<T>"`."""
    for update in updates:
        anchor = re.search(r'"ticker":\s*"' + re.escape(update["ticker"]) + r'"', text)
        if anchor is None:
            raise ValueError(f"ticker {update['ticker']} not found")
        start, end = _enclosing_object(text, anchor.start())
        block = text[start:end]
        for key, (_, new) in (("available_from", update["from"]), ("available_to", update["to"])):
            block = re.sub(r'("' + key + r'":\s*")[^"]*(")', lambda m, new=new: m.group(1) + new + m.group(2), block, count=1)
        text = text[:start] + block + text[end:]
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT_DIR / "config.json"))
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.config)
    text = path.read_text(encoding="utf-8")
    updates = planned_updates(json.loads(text), Path(args.root))
    for update in updates:
        print(f"{update['ticker']:<8} from {update['from'][0]} -> {update['from'][1]}   to {update['to'][0]} -> {update['to'][1]}")
    print(f"{len(updates)} asset(s) to update")
    if args.apply and updates:
        new_text = apply_updates(text, updates)
        json.loads(new_text)
        path.write_text(new_text, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
