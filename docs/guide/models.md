# Models

Every GitHub release carries two example models, trained on the library's bundled public sample (11 coins, Coinbase daily candles). Install one, load it and score a close table with the numpy forward pass; nothing here needs torch.

```bash
aq models list
aq models install example-crypto-mlp        # the latest release; --version 6.6.10 for a tag
aq models info example-crypto-mlp           # its model card
aq models score example-crypto-mlp          # the bundled sample, the last date's scores
aq models score example-crypto-seq --csv my_closes.csv --out scores.csv
```

```python
from aether_quant import models, samples

closes = samples.load_sample_prices()
print([entry["name"] for entry in models.catalog()])
features = models.example_features(closes)   # the six inputs every example reads, one row per date and coin
# once installed (models.install("example-crypto-seq"), or aq models install):
#     model = models.load("example-crypto-seq")
#     scores = models.score(model, closes, head="rank_20d")   # date, ticker, score
```

The [models tutorial](../tutorials/04_models.ipynb) does the whole path offline, with a hand-made model folder in the same format.

| Model | What it is |
|---|---|
| `example-crypto-mlp` | A multitask network (one hidden layer of 16) on six inputs: the 1-, 5-, 20- and 60-session returns and the 20- and 60-session volatility, each z-scored across the coins of its date |
| `example-crypto-seq` | A causal convolutional network (two layers of 8 channels) over the last 20 sessions of the same six inputs |

They are examples, not trading models: they show the format, the forward pass and the scoring path. Each zip carries a model card with its data, its windows and its backtest rank IC.

## What is checked

The release job builds the zips and a manifest of their sha256 in one run, and signs the files with Sigstore. `install` downloads the manifest over HTTPS, refuses a zip whose hash differs from it, and checks every file inside the zip against the zip's own manifest before anything is read. A refused install leaves the cache as it was.

## The project's own models

The models the trading book uses are not published. The example build reads only the bundled sample, and it refuses to publish any file whose hash matches an installed model (`ml/artifact_pins.json`). Your own models work with the same tools: `models.load("ml/versions/<id>")` opens any folder holding an exported model, such as a retrain of your own ([Train on a small machine](../getting-started/train-small-machine.md)).
