# %% [markdown]
# # Hello world: the shipped book in one call
#
# [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/00_hello_world.ipynb)
#
# This is `aq hello` as a library call. It runs the project's shipped book on daily bars for 11 coins, through a cost-aware backtest, and prints the report: benchmarks, overfitting checks, and an honest note. No key, no Docker, no Lean.
#
# The rule is long a coin while its trailing return over 20, 60 and 120 sessions is positive, with one vote per lookback. Weights are vol-scaled and capped, rebalanced every 5 sessions, and charged Coinbase's taker fee plus slippage.

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
# ## Run it
#
# `offline=True` uses the sample that ships in the wheel (2021-06 to 2026-10), so this notebook gives the same numbers everywhere. Use `offline=False` to download fresh bars from Coinbase's public candles. A failed download falls back to the sample.

# %%
from aether_quant import hello

report = hello.run(offline=True)
print(hello.render_text(report))

# %% [markdown]
# ## The equity curve against BTC
#
# The shipped sleeve holds about 11% gross on average, so it is a small, low-volatility slice next to buying BTC outright. Compare Sharpe and drawdown, not total return.

# %%
import matplotlib.pyplot as plt
import pandas as pd

curves = pd.DataFrame({"shipped rule": report.equity, "BTC buy & hold": report.benchmark_equity})
curves.index = pd.to_datetime(curves.index)
axes = curves.plot(logy=True, figsize=(9, 4), color=["#d97706", "#64748b"], title="Growth of $1 (log scale)")
axes.set_xlabel("")
plt.show()

# %% [markdown]
# ## The robustness grid
#
# The same rule on 8 lookback variants. CSCV's PBO asks how often the variant that looked best in one half of the history did worse than the median variant in the other half. Above 0.5 means picking the best-looking variant is worse than picking one at random.

# %%
grid = pd.Series(report.grid_sharpes, name="Sharpe (no T-bill)")
grid.index = [f"a={a}, c={c}" for a in (10, 20, 30, 40) for c in (120, 180)]
print(f"PBO: {report.pbo:.2f}")
grid.to_frame()

# %% [markdown]
# ## Save it
#
# `hello.save` writes a self-contained HTML page (no scripts, no external files) and/or the JSON report.

# %%
import tempfile

out = Path(tempfile.mkdtemp())
hello.save(report, html_path=out / "hello.html", json_path=out / "hello.json")
sorted(path.name for path in out.iterdir())

# %% [markdown]
# **Next:** [01 signal evaluation](01_signal_evaluation.ipynb) · [02 book construction](02_book_construction.ipynb) · [03 overfitting tests](03_overfitting_tests.ipynb)
#
# *No verified edge: this is the project's shipped book, labelled improved, not verified.*
