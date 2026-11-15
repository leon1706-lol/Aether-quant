"""retraining/planning.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from retraining.planning import count_events_in_last_day, min_observations_satisfied


def test_observation_floor_and_the_last_day_count():
    assert min_observations_satisfied(10, 10) is True and min_observations_satisfied(9, 10) is False
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    events = [{"created_at": now - timedelta(hours=2)}, {"created_at": now - timedelta(days=2)}]
    assert count_events_in_last_day(events, now) == 1
