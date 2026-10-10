# storage

Currently empty — reserved placeholder for future persistent artifact
storage outside `ml/`, `data/` and `backtests/` (e.g. later paper/live
trading state or archived model versions that shouldn't live under `ml/`).

No code in the repository reads or writes here yet. It is already excluded
from the Docker build context via `.dockerignore` (grouped with `data/` and
`ml/` — large/local-only directories the FastAPI server doesn't need), so
introducing real content here later won't require any Docker wiring change.
