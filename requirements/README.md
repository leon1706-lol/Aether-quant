# requirements

All `requirements*.txt` variants in one place (moved out of the repo root
in V2-17 for tidiness — six files was enough to justify a folder).

| File | Used by | Contents |
|---|---|---|
| `requirements.txt` | local dev, `train.py`, `main.py`/Lean | Full stack: `torch`, `numpy`, `pandas`, `scikit-learn`, `joblib`, `ibapi`, `flask`, `fastapi`, `uvicorn`, `redis`, `psycopg[binary]`, etc. |
| `requirements-dev.txt` | local dev only | `lean-cli`, `qcalgorithm`, `pytest`, `black`, `fakeredis`, plus `psycopg[binary]` for test imports (connections are mocked in tests), plus `yfinance` (V2-19.5, `data_pipeline/yfinance_backfill.py` — an offline script, never bundled into any container) |
| `requirements-runtime.txt` | `Dockerfile` (the `aether-quant` FastAPI+webui container) | Minimal: `fastapi`, `uvicorn`, `aiofiles` — no ML deps, since that container only serves the JSON API and the built webui |
| `requirements-worker.txt` | `Dockerfile.worker` (`experience-worker`, V2-14) | `redis`, `psycopg[binary]`, `numpy` (the last one transitively required — see `development/Problems.md` #1) |
| `requirements-trigger-worker.txt` | `Dockerfile.trigger_worker` (`performance-trigger-worker`, V2-16) | `psycopg[binary]`, `numpy` — no `redis`, this worker never touches the stream |
| `requirements-retraining-worker.txt` | `Dockerfile.retraining_worker` (`retraining-worker`, V2-17) | The full training stack (`torch`, `numpy`, `pandas`, `scikit-learn`, `joblib`) plus `psycopg[binary]` — unlike the two workers above, this one subprocess-invokes `train.py --candidate` directly, so it can't use a minimal image |
| `requirements-telegram-worker.txt` | `Dockerfile.telegram_worker` (`telegram-worker`, V2-19) | `psycopg[binary]`, `requests`, `numpy` — no `redis`, this worker never touches the experience stream directly. `numpy` is transitively required the same way as `requirements-trigger-worker.txt` (importing `performance.postgres_triggers` initializes `performance/__init__.py` -> `.triggers` -> `experience.observation_metrics`) |

Install from the repo root:

```powershell
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-dev.txt   # local dev extras
```

Each Dockerfile does `COPY requirements/requirements-<variant>.txt .` then
`RUN pip install --no-cache-dir -r requirements-<variant>.txt` — the file
lands at the image's working directory root, so the install step itself
doesn't need the `requirements/` prefix.
