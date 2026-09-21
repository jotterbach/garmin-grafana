"""
Tests for metric_points.py's build_daily_summary_point() -- written before
the implementation exists (TDD), per this branch's explicit process.

Pure unit tests: no InfluxDB, no Garmin mocking, no garmin_fetch_module
fixture. device_name/database_name are passed explicitly rather than read
from garmin_fetch.py's globals, specifically so this helper has zero import
coupling to garmin_fetch.py and stays trivially testable in isolation.
"""

from metric_points import build_daily_summary_point


def test_returns_one_point_with_standard_tags_and_midnight_time():
    points = build_daily_summary_point(
        "HillScore",
        "2026-01-15",
        {"strengthScore": 5, "overallScore": None},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert len(points) == 1
    point = points[0]
    assert point["measurement"] == "HillScore"
    assert point["tags"] == {"Device": "Forerunner 970", "Database_Name": "GarminStats"}
    assert point["fields"] == {"strengthScore": 5, "overallScore": None}
    assert point["time"] == "2026-01-15T00:00:00+00:00"


def test_returns_empty_list_when_all_fields_none():
    points = build_daily_summary_point(
        "HillScore",
        "2026-01-15",
        {"strengthScore": None, "overallScore": None},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert points == []


def test_returns_one_point_when_at_least_one_field_is_not_none():
    points = build_daily_summary_point(
        "Hydration",
        "2026-01-15",
        {"ValueInML": None, "GoalInML": 3000},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert len(points) == 1


def test_extra_tags_are_merged_with_standard_tags():
    points = build_daily_summary_point(
        "BloodPressure",
        "2026-01-15",
        {"Systolic": 120},
        device_name="Forerunner 970",
        database_name="GarminStats",
        extra_tags={"Source": "MANUAL"},
    )
    assert points[0]["tags"] == {
        "Device": "Forerunner 970",
        "Database_Name": "GarminStats",
        "Source": "MANUAL",
    }


def test_empty_fields_dict_returns_empty_list():
    points = build_daily_summary_point(
        "HillScore",
        "2026-01-15",
        {},
        device_name="Forerunner 970",
        database_name="GarminStats",
    )
    assert points == []
