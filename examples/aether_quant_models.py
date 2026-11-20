"""Models from the library: the example catalog, then a model folder loaded and scored with the numpy forward pass on the bundled sample.
No torch, no network: the model here is a hand-made one-layer net in the library's export format (20-session momentum minus 60-session
volatility), written to a temporary folder. Any exported model folder loads the same way, an installed example or your own retrain's
`ml/versions/<id>/`; `aq models install example-crypto-mlp` fetches a trained example from a GitHub release.

    python examples/aether_quant_models.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aether_quant import models, samples

# a linear trunk over the example features (ret_1, ret_5, ret_20, ret_60, vol_20, vol_60) and one rank_20d head
WEIGHTS = [0.0, 0.0, 1.0, 0.0, -0.5, 0.0]


def write_model(folder: Path, names: list[str]) -> Path:
    export = {"trunk": [{"type": "linear", "weight_key": "w", "bias_key": "b"}], "heads": {"rank_20d": [{"type": "linear", "weight_key": "h", "bias_key": "hb"}]},
              "state_dict": {"w": [WEIGHTS], "b": [0.0], "h": [[1.0]], "hb": [0.0]}}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "multitask_model.json").write_text(json.dumps({"export": export}), encoding="utf-8")
    (folder / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": names}), encoding="utf-8")
    (folder / "card.md").write_text("# momentum-minus-volatility\nA hand-made example, not a trained model and not a trading model.\n", encoding="utf-8")
    return folder


def main() -> None:
    print("example models published with each release:")
    for entry in models.catalog():
        print(f"  {entry['name']} ({entry['kind']}): {entry['summary']}")
    closes = samples.load_sample_prices()
    names = [column for column in models.example_features(closes).columns if column not in ("date", "ticker")]
    with tempfile.TemporaryDirectory() as tmp:
        model = models.load(write_model(Path(tmp) / "momentum-minus-volatility", names))
        scores = models.score(model, closes)
    last = scores[scores["date"] == scores["date"].max()].sort_values("score", ascending=False)
    print(f"\nloaded {model['name']} ({model['kind']}): {model['card'].splitlines()[1]}")
    print(f"scored {len(scores)} rows, {scores['ticker'].nunique()} coins, {scores['date'].min()} to {scores['date'].max()}")
    print(f"ranking on {last['date'].iloc[0]}: " + ", ".join(f"{row.ticker} {row.score:+.3f}" for row in last.itertuples()))


if __name__ == "__main__":
    main()
