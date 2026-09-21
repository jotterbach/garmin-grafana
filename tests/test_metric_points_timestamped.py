"""
Tests for metric_points.py's build_timestamped_point() -- written before
the implementation exists (TDD), per this branch's explicit process.

Distinct from build_daily_summary_point (tests/test_metric_points.py):
this shape takes a caller-computed, arbitrary timestamp rather than always
being date_str's midnight, and supports extra_tags for the one caller
(get_blood_pressure) that needs a tag beyond the standard two.
"""

from datetime import datetime, timezone

from metric_points import build_timestamped_point


def test_returns_one_point_with_given_timestamp_string():
    points = build_timestamped_point(
        "TrainingReadiness",
        "2026-01-15T06:30:00+00:00",
        {"score": 72, "level": "HIGH"},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert points == [
        {
            "measurement": "TrainingReadiness",
            "time": "2026-01-15T06:30:00+00:00",
            "tags": {"Device": "Forerunner 970", "Database_Name": "GarminStats"},
            "fields": {"score": 72, "level": "HIGH"},
        }
    ]


def test_accepts_a_datetime_like_object_and_calls_isoformat():
    ts = datetime(2026, 1, 15, 6, 30, tzinfo=timezone.utc)
    points = build_timestamped_point(
        "TrainingStatus",
        ts,
        {"trainingStatus": 3},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert points[0]["time"] == ts.isoformat()


def test_returns_empty_list_when_all_fields_none():
    points = build_timestamped_point(
        "TrainingReadiness",
        "2026-01-15T06:30:00+00:00",
        {"score": None, "level": None},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert points == []


def test_empty_fields_dict_returns_empty_list():
    points = build_timestamped_point(
        "TrainingReadiness",
        "2026-01-15T06:30:00+00:00",
        {},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert points == []


def test_extra_tags_are_merged_with_standard_tags():
    points = build_timestamped_point(
        "BloodPressure",
        "2026-01-15T06:30:00+00:00",
        {"Systolic": 120, "Diastolic": 80, "Pulse": 60},
        device_name="Forerunner 970",
        database_name="GarminStats",
        extra_tags={"Source": "MANUAL"},
    )
    assert points[0]["tags"] == {
        "Device": "Forerunner 970",
        "Database_Name": "GarminStats",
        "Source": "MANUAL",
    }
