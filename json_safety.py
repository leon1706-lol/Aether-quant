"""Shared JSON-safety helpers (V5.4.7, development/Problems.md #120).

Three failure modes kept biting every JSON producer in this repo
independently:

1. **Non-finite floats** — `json.dumps` happily emits bare `NaN`/`Infinity`
   (Python-tolerant, but PostgreSQL JSONB rejects them and browser
   `JSON.parse` throws), so one poisoned event wedged the whole Redis →
   Postgres pipeline (Problems.md #120) and a NaN state value broke the
   webui's response parsing.
2. **numpy scalar types** — `np.float64`/`np.int64` raise `TypeError` under
   `json.dumps`, silently dropping events whose payloads came straight from
   pandas.
3. **Non-atomic writes** — truncate-then-`write_text` leaves a torn file
   whenever a reader races the writer or the writer dies mid-write; every
   reader of these files (`monitoring/api_server.py`, both workers) then
   either 500s or reads half a document.

One module, three pure functions, stdlib-only (plus numpy when present),
so any layer can import it without cycles: the producers sanitize before
dumps, the writers go through `atomic_write_json`, and the lenient reader
degrades to None instead of raising.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path


def _is_numpy_number(value) -> bool:
    """True for np.integer/np.floating without importing numpy at module
    load (kept optional on purpose - this module must import everywhere)."""
    type_name = type(value).__module__
    if type_name != "numpy":
        return False
    return hasattr(value, "item")


def sanitize_json_finite(value):
    """Recursively converts a structure into something `json.dumps(...,
    allow_nan=False)` can always serialize:

    - non-finite floats (NaN / +/-inf) -> None ("value unavailable",
      the repo-wide degrade convention)
    - numpy integer/float scalars -> plain int/float (via .item())
    - dict keys are passed through unchanged (they must already be strings)

    Tuples/lists/dicts are rebuilt; everything else returns unchanged."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bool) or isinstance(value, int) or value is None or isinstance(value, str):
        return value
    if _is_numpy_number(value):
        as_python = value.item()
        if isinstance(as_python, float) and not math.isfinite(as_python):
            return None
        return as_python
    if isinstance(value, dict):
        return {key: sanitize_json_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json_finite(item) for item in value]
    return value


def dumps_json_safe(payload) -> str:
    """sanitize + dumps with allow_nan=False - the single serialization
    path shared by the Redis producers and the status-file writers, so a
    non-finite value can never reach Postgres JSONB or the webui again."""
    return json.dumps(sanitize_json_finite(payload), allow_nan=False)


def atomic_write_json(path: Path, payload, *, indent: int | None = None) -> None:
    """Writes payload to path via a same-directory temp file + os.replace.

    os.replace is atomic within a filesystem, so a concurrent reader sees
    either the complete old file or the complete new file - never a torn
    one - and a writer crash mid-write leaves the previous generation
    intact. The temp file is cleaned up on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(sanitize_json_finite(payload), allow_nan=False, indent=indent)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """atomic_write_json's twin for plain-text content (CSV caches etc.) -
    same same-directory temp file + os.replace contract."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_json_lenient(path: Path):
    """Reads and parses path, returning None on ANY failure (missing,
    unreadable, mid-write torn, malformed). Every caller treats None as
    'not available right now' and degrades - the monitoring readers'
    documented contract, now actually true while a writer is mid-replace."""
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None
