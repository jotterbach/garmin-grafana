"""
Shared InfluxDB point-building helpers for garmin_fetch.py's per-metric
fetch functions.

Deliberately takes device_name/database_name as explicit parameters rather
than reading garmin_fetch.py's module globals -- keeps this module free of
any import coupling to garmin_fetch.py, so it's trivially unit-testable in
isolation (see tests/test_metric_points.py).

Phase 1 of the metric registry: covers only the "single daily-summary
point" shape (get_hillscore, get_race_predictions, get_fitness_age,
get_vo2_max, get_endurance_score, get_hydration -- verified precisely by
reading each function's body, not assumed). Other shapes (multi-point-per-
day with real API timestamps, intraday arrays, activity/GPS, etc.) are
deliberately out of scope for this module for now.
"""

from datetime import datetime
from typing import Any, Optional

import pytz


def build_daily_summary_point(
    measurement: str,
    date_str: str,
    fields: dict[str, Any],
    *,
    device_name: str,
    database_name: str,
    extra_tags: Optional[dict[str, Any]] = None,
) -> list:
    """
    Builds the single-point-per-day shape shared by get_hillscore,
    get_race_predictions, get_fitness_age, get_vo2_max, get_endurance_score,
    and get_hydration: one point at date_str's midnight UTC, standard
    {Device, Database_Name} tags (plus any extra_tags), or no point at all
    if every field value is None -- matching each of those functions'
    existing `if not all(v is None for v in fields.values()):` guard.
    """
    if not fields or all(value is None for value in fields.values()):
        return []

    tags = {"Device": device_name, "Database_Name": database_name}
    if extra_tags:
        tags.update(extra_tags)

    return [
        {
            "measurement": measurement,
            "time": datetime.strptime(date_str, "%Y-%m-%d")
            .replace(hour=0, tzinfo=pytz.UTC)
            .isoformat(),
            "tags": tags,
            "fields": fields,
        }
    ]
