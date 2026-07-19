# requirements

`requirements*.txt` variants (moved out of the repo root in V2-17 for
tidiness) — **except the repo-root `requirements.txt`, which is back by
necessity, not tidiness** (see "Lean CLI's own requirements.txt" below).

| File | Used by | Contents |
|---|---|---|
| `requirements/requirements.txt` | local dev, `train.py`, **and** the single consolidated `Dockerfile` (`aether-quant-engine` image — app + every worker) | Full stack: `torch`, `numpy`, `pandas`, `scikit-learn`, `joblib`, `ibapi`, `flask`, `fastapi`, `uvicorn`, `aiofiles`, `redis`, `psycopg[binary]`, etc. |
| `requirements/requirements-dev.txt` | local dev only | `lean-cli`, `qcalgorithm`, `pytest`, `black`, `fakeredis`, plus `psycopg[binary]` for test imports (connections are mocked in tests), plus `yfinance` (V2-19.5, `data_pipeline/yfinance_backfill.py` — an offline script, never bundled into any container), plus `matplotlib` (`generate_backtest_report.py`, called by `aq backtest` to regenerate README.md's Backtest Results chart) |
| repo-root `requirements.txt` (**not** in this folder) | `lean backtest .` only | Just `redis` — see below |

## Lean CLI's own `requirements.txt` (repo root, not this folder)

`main.py`/Lean does **not** read `requirements/requirements.txt` — this
table's earlier claim to the contrary was wrong, and was a real, previously-
undiscovered bug (development/Problems.md). Lean CLI auto-detects a
`requirements.txt` sitting at the **project root**, next to `main.py`
(the installed `lean` package's `components/docker/lean_runner.py::
set_up_python_options()`, `requirements_files = [... project_dir /
"requirements.txt"]`) and pip-installs it into its own per-backtest
site-packages volume — a completely separate mechanism from everything
else in this table. Since Lean's own image already bundles the heavy
scientific stack (torch/pandas/numpy/scikit-learn all already work inside
a real `lean backtest .` run), the repo-root `requirements.txt` only needs
to list what Lean's image is actually missing: `redis`, needed by
`main.py`'s `ExperienceQueue` (`experience/redis_queue.py`) to push
experience events to Postgres during a real backtest. Without it, that
push silently no-ops (`"ExperienceQueue: Redis unavailable ... No module
named 'redis'"`) and the retraining loop's real data source never gets fed
by an actual backtest run at all. Keep this file minimal and deliberately
separate from `requirements/` — anything added here gets reinstalled into
every fresh Lean site-packages volume, so only add what Lean's own image
doesn't already provide.

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
