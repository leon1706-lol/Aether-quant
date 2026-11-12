# Install

`pip install aether-quant` is the research install: the library and the `aq` command on numpy and pandas only. It does not pull torch, Lean, Docker, Redis or Postgres. Add an extra for each thing you need.

| Command | Adds | For |
|---|---|---|
| `pip install aether-quant` | numpy, pandas | the library, `aq hello`, every facade (about 145 MB in a fresh venv) |
| `pip install "aether-quant[research]"` | scipy, scikit-learn, statsmodels, pyarrow, httpx | HRP, the gradient-boosted probes, parquet research files, FRED |
| `pip install "aether-quant[notebooks]"` | research + matplotlib, ipykernel, nbclient | the tutorials |
| `pip install "aether-quant[dashboard]"` | fastapi, uvicorn | serving the dashboard API |
| `pip install "aether-quant[live]"` | redis, psycopg, keyring, ibapi, the Lean CLI | paper and live deployments |
| `pip install "aether-quant[train]"` | torch, scikit-learn, pyarrow | retraining the models |
| `pip install "aether-quant[docs]"` | mkdocs-material, mkdocstrings, mkdocs-jupyter | building this site |
| `pip install "aether-quant[full]"` | everything above | the whole system |

**The Lean engine image (about 40 GB) is only for real Lean backtests and deployments of the trading system.** No research path needs it.

## From a clone

```bash
git clone https://github.com/leon1706-lol/Aether-quant
cd Aether-quant
pip install -e ".[research]"
aq hello --offline
```

## What a light install can do

Every facade imports with only numpy and pandas present (`tests/test_lite_install.py` blocks every optional package and checks). A function that needs an extra imports it when called. For example, `compute_hrp_weights` needs scipy, so it raises `ModuleNotFoundError` on a light install and works after `pip install "aether-quant[research]"`.
