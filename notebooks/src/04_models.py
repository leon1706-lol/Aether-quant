# %% [markdown]
# # Models: load an exported model and score with numpy
#
# [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/04_models.ipynb)
#
# `aether_quant.models` loads any folder that holds an exported model and its feature schema, and scores a close table with the library's numpy forward pass: no torch. Each GitHub release publishes two small example models trained on the bundled sample (`aq models install example-crypto-mlp`); the project's own trading models are not published.
#
# This notebook stays offline. It writes a hand-made one-layer model in the export format, so the steps are the same as for a trained example or your own retrain's `ml/versions/<id>/`.

# %%
import sys
from pathlib import Path

if "google.colab" in sys.modules:  # Colab: install the library (numpy and pandas come with it)
    get_ipython().run_line_magic("pip", 'install -q "aether-quant[notebooks]"')  # noqa: F821
else:  # a clone: run against the checkout's code
    for parent in (Path.cwd(), *Path.cwd().parents):
        if (parent / "aether_quant" / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            break

# %% [markdown]
# ## The catalog
#
# The examples each release carries. `models.install(name)` downloads one, checks its sha256 against the release's manifest and unpacks it into `~/.cache/aether-quant/models`; `models.load(name)` then opens it.

# %%
import pandas as pd

from aether_quant import models, samples

pd.DataFrame(models.catalog())[["name", "kind", "summary"]]

# %% [markdown]
# ## The features
#
# Six features per coin and session, each from closes up to that session only, z-scored across the coins of the date: returns over 1, 5, 20 and 60 sessions and volatility over 20 and 60.

# %%
closes = samples.load_sample_prices()
features = models.example_features(closes)
names = [column for column in features.columns if column not in ("date", "ticker")]
features.dropna().tail()

# %% [markdown]
# ## A model folder
#
# The export format is a list of layers and a state dict. This one is linear: 20-session momentum minus half the 20-session volatility, read through one `rank_20d` head.

# %%
import json
import tempfile

folder = Path(tempfile.mkdtemp()) / "momentum-minus-volatility"
folder.mkdir(parents=True)
export = {"trunk": [{"type": "linear", "weight_key": "w", "bias_key": "b"}], "heads": {"rank_20d": [{"type": "linear", "weight_key": "h", "bias_key": "hb"}]},
          "state_dict": {"w": [[0.0, 0.0, 1.0, 0.0, -0.5, 0.0]], "b": [0.0], "h": [[1.0]], "hb": [0.0]}}
(folder / "multitask_model.json").write_text(json.dumps({"export": export}), encoding="utf-8")
(folder / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": names}), encoding="utf-8")
model = models.load(folder)
print(model["name"], model["kind"], model["schema"]["model_input_names"])

# %% [markdown]
# ## Score and look at the ranking
#
# `models.score` returns long rows (date, ticker, score) for every session the features exist. A trained example scores the same way.

# %%
import matplotlib.pyplot as plt

scores = models.score(model, closes)
last = scores[scores["date"] == scores["date"].max()].set_index("ticker")["score"].sort_values()
axes = last.plot.barh(figsize=(7, 3.2), title=f"Scores on {scores['date'].max()}")
plt.show()
print(f"{len(scores)} rows, {scores['ticker'].nunique()} coins, {scores['date'].min()} to {scores['date'].max()}")

# %% [markdown]
# *A score is not a result. Judge one with the IC report and the overfitting tests of the first notebooks before any book trades on it.*
