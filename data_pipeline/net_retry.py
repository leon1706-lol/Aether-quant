"""A download that outlives a dropped connection (V6.6.0). The owner's WLAN can drop mid-run, and a fetch that fails must never read as "no data".

Only a status the server chose (404, or 403 where a dated file doesn't exist) means absent. Anything else is retried, waiting out an outage; when the
wait runs out it raises `NetworkOutage`, so the run stops with what it saved and resumes later instead of recording a hole.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable


class NetworkOutage(RuntimeError):
    """The network stayed down, or the server kept failing, for longer than the caller will wait."""


def fetch(
    url: str, *, get: Callable, absent_codes: tuple[int, ...] = (404,), max_wait_seconds: float = 3600.0, sleep: Callable[[float], None] = _time.sleep,
    timeout: float = 120.0, **request_kwargs,
):
    """The response, or None when the server says the file doesn't exist. `get` is `requests.get` or a session's."""
    waited = 0.0
    delay = 5.0
    last_problem = ""
    while True:
        try:
            response = get(url, timeout=timeout, **request_kwargs)
        except Exception as error:  # requests raises several types for a dropped connection, and so do its dependencies
            last_problem = f"{type(error).__name__}"
        else:
            if response.status_code in absent_codes:
                return None
            if response.ok:
                return response
            last_problem = f"HTTP {response.status_code}"
        if waited >= max_wait_seconds:
            raise NetworkOutage(f"{url}: {last_problem} after {waited:.0f} s")
        sleep(delay)
        waited += delay
        delay = min(delay * 2.0, 120.0)
