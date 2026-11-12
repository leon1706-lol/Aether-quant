# Notebooks

Four tutorials for the `aether_quant` library. Each one opens in Colab, installs the library in its first cell, and runs on the sample that ships with the wheel, so the numbers are the same everywhere. No key, no Docker, no Lean.

| Notebook | What it shows | Open |
|---|---|---|
| [`00_hello_world`](00_hello_world.ipynb) | `aq hello` as a library call: the shipped book, its equity curve against BTC, the robustness grid | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/00_hello_world.ipynb) |
| [`01_signal_evaluation`](01_signal_evaluation.ipynb) | Forward targets, the IC report with HAC t and bootstrap CI, quantiles, IC decay, purged folds, a leakage audit that catches a leaked signal, factor spanning | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/01_signal_evaluation.ipynb) |
| [`02_book_construction`](02_book_construction.ipynb) | A rank book, dollar and beta neutrality, HRP, volatility targeting, fractional Kelly, cost models, `backtest()` with and without costs | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/02_book_construction.ipynb) |
| [`03_overfitting_tests`](03_overfitting_tests.ipynb) | PBO by CSCV, the deflated Sharpe as N grows, minimum track record, haircut Sharpe, a placebo test, a holdout read once, generations | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/03_overfitting_tests.ipynb) |

- **Locally:** `pip install "aether-quant[notebooks]"` and open them in Jupyter. From a clone, the first cell puts the checkout on `sys.path` instead.
- **Colab:** the install cell needs `aether-quant` 6.6.5 or later on PyPI.
- **Editing:** Each notebook's source is the percent-format `.py` file of the same name in [`src/`](src/). Rebuild and re-run with `python scripts/build_notebooks.py --execute` (about 4 minutes on a small PC). `tests/test_notebooks.py` fails if a notebook drifts from its source, lacks its Colab cell, or holds an error, and CI's `notebooks` job runs them all again.
