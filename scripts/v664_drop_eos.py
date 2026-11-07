"""V6.6.4 Step 0.6: EOS leaves the forward definition (Problems #311), by the owner's decision of 2026-11-07.

Coinbase has delisted EOS-USD. The forward candidate gets a new id, so `judge_candidate` (which groups by name) never pools the old row with the new ones, and the registry's
g0001 takes the new definition with a lifecycle row. `forward/generations.jsonl` has no rows yet, so no earned record changes. Run once:

    python scripts/v664_drop_eos.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dataclasses import replace  # noqa: E402

from evaluation.forward_ledger import definition_sha256  # noqa: E402
from evaluation.generation_registry import append_lifecycle, load_registry, save_registry  # noqa: E402

OLD_ID, NEW_ID, COIN = "t3_crypto_trend_blend", "t3_crypto_trend_blend_x_eos", "EOSUSD"
REASON = "owner decision 2026-11-07: Coinbase delisted EOS-USD (Problems #311)"


def main() -> int:
    candidates_path = ROOT / "ml" / "forward" / "candidates.json"
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    entry = next((item for item in payload["candidates"] if item["id"] in (OLD_ID, NEW_ID)), None)
    if entry is None:
        print("no t3 candidate found", file=sys.stderr)
        return 1
    if entry["id"] == NEW_ID:
        print("already done")
        return 0
    previous_sha = definition_sha256(entry)
    entry["id"] = NEW_ID
    entry["tickers"] = [ticker for ticker in entry["tickers"] if ticker != COIN]
    entry["asset_class"] = {ticker: kind for ticker, kind in entry["asset_class"].items() if ticker != COIN}
    entry["initial_weights"] = {ticker: weight for ticker, weight in entry["initial_weights"].items() if ticker != COIN}
    candidates_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    new_sha = definition_sha256(entry)

    registry_path = ROOT / "ml" / "generations" / "registry.json"
    registry = load_registry(registry_path)
    generation = registry["g0001"]
    note = f"{NEW_ID}, the installed V6.5.0 sleeve without EOS (delisted by Coinbase, #311): not verified. {generation.note}"
    registry["g0001"] = replace(generation, definition=entry, procedure_sha256=new_sha, note=note)
    save_registry(registry_path, registry)
    append_lifecycle(
        ROOT / "ml" / "generations" / "lifecycle.jsonl", event="definition_changed", created_at="2026-11-07T00:00:00+00:00",
        payload={"generation": "g0001", "definition_sha256": new_sha, "previous_definition_sha256": previous_sha, "reason": REASON},
    )
    print(json.dumps({"id": NEW_ID, "tickers": len(entry["tickers"]), "definition_sha256": new_sha, "previous": previous_sha}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
