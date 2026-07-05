# requirements

All `requirements*.txt` variants in one place (moved out of the repo root
in V2-17 for tidiness — six files was enough to justify a folder).

| File | Used by | Contents |
|---|---|---|
| `requirements.txt` | local dev, `train.py`, `main.py`/Lean | Full stack: `torch`, `numpy`, `pandas`, `scikit-learn`, `joblib`, `ibapi`, `flask`, `fastapi`, `uvicorn`, `redis`, `psycopg[binary]`, etc. |
| `requirements-dev.txt` | local dev only | `lean-cli`, `qcalgorithm`, `pytest`, `black`, `fakeredis`, plus `psycopg[binary]` for test imports (connections are mocked in tests), plus `yfinance` (V2-19.5, `data_pipeline/yfinance_backfill.py` — an offline script, never bundled into any container), plus `matplotlib` (`generate_backtest_report.py`, called by `aq backtest` to regenerate README.md's Backtest Results chart) |
| `requirements-runtime.txt` | `Dockerfile` (the `aether-quant` FastAPI+webui container) | Minimal: `fastapi`, `uvicorn`, `aiofiles` — no ML deps, since that container only serves the JSON API and the built webui |
| `requirements-workers.txt` | `Dockerfile.workers` (`experience-worker` V2-14, `performance-trigger-worker` V2-16, `telegram-worker` V2-19 — consolidated onto one shared image in the Docker image cleanup pass) | `redis`, `psycopg[binary]`, `numpy`, `requests` — the union of what the three lightweight internal workers need. `numpy` is transitively required by two of the three: importing `performance.postgres_triggers` initializes `performance/__init__.py` -> `.triggers` -> `experience.observation_metrics`, which imports `numpy` — see `development/Problems.md` #1 for the same lesson learned the hard way before this consolidation |
| `requirements-retraining-worker.txt` | `Dockerfile.retraining_worker` (`retraining-worker`, V2-17) | The full training stack (`torch`, `numpy`, `pandas`, `scikit-learn`, `joblib`) plus `psycopg[binary]` — unlike the shared workers image above, this one subprocess-invokes `train.py --candidate` directly, so it can't use a minimal image |

Install from the repo root:

```powershell
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-dev.txt   # local dev extras
```

Each Dockerfile does `COPY requirements/requirements-<variant>.txt .` then
`RUN pip install --no-cache-dir -r requirements-<variant>.txt` — the file
lands at the image's working directory root, so the install step itself
doesn't need the `requirements/` prefix.
