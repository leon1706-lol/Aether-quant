# requirements

All dependency manifests live under this directory so Lean CLI does not
auto-detect and bind-mount a dependency file from the project root.

| File | Used by | Contents |
|---|---|---|
| `requirements/requirements.txt` | local dev, `train.py`, and the consolidated `Dockerfile` | Full app/worker stack, including `redis`, `psycopg[binary]`, `torch`, `pandas`, and `lean` |
| `requirements/requirements-dev.txt` | local dev and tests | Lean CLI, pytest, formatting, test doubles, offline data helpers, and report-generation extras |
| `requirements/lean-runtime.txt` | `Dockerfile.lean` / the local image used by `aq backtest` | Only packages missing from the pinned QuantConnect image; currently `redis` |

## Local LEAN image

`aq backtest` uses `Dockerfile.lean` to build `aether-quant-lean:17900` on
the first run. The image is based on the pinned `quantconnect/lean:17900`
engine and installs `requirements/lean-runtime.txt` inside the image. This
avoids Lean CLI's Windows-host bind mount of a generated root
`requirements.txt` while preserving the Redis dependency for
`ExperienceQueue`.

The main `Dockerfile` continues to install `requirements/requirements.txt`
for the application and worker images. Install local dependencies from the
repo root with:

```powershell
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-dev.txt
```
