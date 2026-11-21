# %% [markdown]
# # The model lab: build, train, judge and export a model
#
# [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/05_model_lab.ipynb)
#
# `aether_quant.lab` is the library behind `aq lab`: a lab folder, a dataset in the production layout, model templates (linear, and with torch the project's own networks), training runs that each count as a trial, and the project's statistics to judge them. This notebook stays offline: the bundled sample and the `linear` template, which needs no torch. The [model lab guide](../guide/model-lab.md) shows the same steps as commands.

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
# ## A lab and its dataset
#
# `init_lab` makes the folder: `lab.toml`, `models/`, `runs/` and `data/`. `build_dataset` turns a close table into features, forward rank targets and split labels, in the columns of the project's own training dataset. Rows whose 20-session label reaches into the next split are labelled `purged`: never fitted or scored.

# %%
import tempfile

from aether_quant import lab, samples

folder = Path(tempfile.mkdtemp()) / "mylab"
print(lab.init_lab(folder))
closes = samples.load_sample_prices()
dataset = lab.build_dataset(closes, features="core", targets=(5, 20))
dataset.to_csv(folder / "data" / "dataset.csv", index=False)
print(dataset.groupby("split").size())

# %% [markdown]
# ## A model and a training run
#
# `new_model` copies a template into `models/<name>/`. Its `config.toml` names the features, the target and the training settings, and `overrides` change one run. Each seed of the run is a trial in the lab's `trials.jsonl`: the count N that every report judges against.

# %%
print(lab.new_model(folder, "ridge", "linear"))
record = lab.train_run(folder, "ridge", seeds=[1, 2], log=lambda line: None)
print(record["id"], "out-of-sample IC", round(record["metrics"]["oof_ic_mean"], 4), "N", record["trials_n"])

# %% [markdown]
# ## Judging it
#
# `evaluate_run` reads only the run's out-of-sample scores: the IC by split and year, its decay, the quintile spreads, the gap to the fitted IC, and with `book=True` a cost-aware quintile book with its deflated Sharpe at the lab's N.

# %%
run = lab.find_run(folder, "latest")
report = lab.evaluate_run(run, lab_dir=folder, book=True)
print(lab.render_eval(report))

# %% [markdown]
# ## Against a baseline, and what it learned
#
# `compare_runs` sets runs and a plain baseline signal on the rows they all scored, each tested against the best with a HAC t-statistic. `explain_run` is out-of-sample permutation importance: how much the IC drops when one feature is shuffled.

# %%
print(lab.render_compare(lab.compare_runs([run], baseline="momentum_20")))
print(lab.render_mapping("permutation importance", lab.explain_run(run)["importance"]))

# %% [markdown]
# ## Export
#
# `export_run` writes the run in the `aq models` format: the weights as JSON, the features it reads, a model card and a sha256 manifest. `aq models install NAME --from ZIP` installs it, and scoring needs no torch.

# %%
import zipfile

card = lab.model_card(run, report)
result = lab.export_run(run, folder / "ridge.zip", card=card)
print(result["zip"], sorted(zipfile.ZipFile(result["zip"]).namelist()))
