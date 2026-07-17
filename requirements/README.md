# requirements

`requirements*.txt` variants (moved out of the repo root in V2-17 for
tidiness).

| File | Used by | Contents |
|---|---|---|
| `requirements.txt` | local dev, `train.py`, `main.py`/Lean, **and** the single consolidated `Dockerfile` (`aether-quant-engine` image — app + every worker) | Full stack: `torch`, `numpy`, `pandas`, `scikit-learn`, `joblib`, `ibapi`, `flask`, `fastapi`, `uvicorn`, `aiofiles`, `redis`, `psycopg[binary]`, etc. |
| `requirements-dev.txt` | local dev only | `lean-cli`, `qcalgorithm`, `pytest`, `black`, `fakeredis`, plus `psycopg[binary]` for test imports (connections are mocked in tests), plus `yfinance` (V2-19.5, `data_pipeline/yfinance_backfill.py` — an offline script, never bundled into any container), plus `matplotlib` (`generate_backtest_report.py`, called by `aq backtest` to regenerate README.md's Backtest Results chart) |

**Docker image consolidation**: this project previously shipped three
separate Dockerfiles (`Dockerfile` for the FastAPI+webui app,
`Dockerfile.workers` for `experience-worker`/`performance-trigger-worker`/
`telegram-worker`, `Dockerfile.retraining_worker` for `retraining-worker`),
each with its own minimal `requirements-<variant>.txt` and a hand-
maintained `COPY <package>/` allow-list. That per-worker allow-list was
the direct cause of four separate incidents (`development/Problems.md`
#1, #2, #20, #30 — each a `ModuleNotFoundError` crash loop from a COPY
list drifting out of sync with the actual import graph). All three
Dockerfiles and their dedicated `requirements-runtime.txt`/
`requirements-workers.txt`/`requirements-retraining-worker.txt` files
were retired in favor of **one consolidated `Dockerfile`**, tagged
`aether-quant-engine`, that installs the single `requirements.txt` above
and `COPY . .`s the whole source tree — every service (app + every
worker) now runs from the same image, differentiated only by
`docker-compose.yml`'s per-service `command:`. This makes the whole
missing-COPY bug class structurally impossible: there is no longer a
per-image allow-list that can drift.

Install from the repo root:

```powershell
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-dev.txt   # local dev extras
```

`Dockerfile` does `COPY requirements/requirements.txt ./requirements/`
then `RUN pip install --no-cache-dir -r requirements/requirements.txt`.
