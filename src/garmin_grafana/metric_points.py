"""
Shared InfluxDB point-building helpers for garmin_fetch.py's per-metric
fetch functions.

Deliberately takes device_name/database_name as explicit parameters rather
than reading garmin_fetch.py's module globals -- keeps this module free of
any import coupling to garmin_fetch.py, so it's trivially unit-testable in
isolation (see tests/test_metric_points.py).

Phase 1 covers the "single daily-summary point" shape
(build_daily_summary_point -- get_hillscore, get_race_predictions,
get_fitness_age, get_vo2_max, get_endurance_score, get_hydration). Phase 2
adds the "multi-point-per-day, real API timestamp" shape
(build_timestamped_point -- get_training_readiness, get_blood_pressure,
get_training_status, get_solar_intensity, get_lactate_threshold). Both
verified precisely by reading each function's body, not assumed. Other
shapes (intraday arrays, activity/GPS, sleep, strength training, etc.) are
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


def build_timestamped_point(
    measurement: str,
    timestamp: Any,
    fields: dict[str, Any],
    *,
    device_name: str,
    database_name: str,
    extra_tags: Optional[dict[str, Any]] = None,
) -> list:
    """
    Single point at a caller-computed, arbitrary timestamp -- unlike
    build_daily_summary_point, not tied to date_str's midnight. Shared by
    get_training_readiness, get_blood_pressure, get_training_status,
    get_solar_intensity, and get_lactate_threshold, each of which computes
    its own timestamp differently (real API epoch-ms, real API ISO string,
    or a date-derived value) -- deliberately not unified here, since that
    computation is exactly what those functions already get right today and
    isn't part of what's duplicated across them.

    `timestamp` may be a pre-formatted string (used as-is) or any object
    with `.isoformat()` (e.g. a datetime). Same "[] if all fields are None,
    else one point in a list" contract as build_daily_summary_point.
    """
    if not fields or all(value is None for value in fields.values()):
        return []

    tags = {"Device": device_name, "Database_Name": database_name}
    if extra_tags:
        tags.update(extra_tags)

    time_value = timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp

    return [
        {
            "measurement": measurement,
            "time": time_value,
            "tags": tags,
            "fields": fields,
        }
    ]
