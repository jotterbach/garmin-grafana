"""
Characterization tests for the "multi-point-per-day, real API timestamp"
shape functions being migrated to metric_points.build_timestamped_point()
on this branch: get_training_readiness, get_blood_pressure,
get_training_status, get_solar_intensity, get_lactate_threshold.

Each test is written and confirmed passing against the *current*
(pre-migration) implementation first, then must keep passing unchanged
after that function is refactored.
"""

from datetime import datetime, timezone

DATE_STR = "2026-01-15"


def test_training_readiness_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_training_readiness(DATE_STR)
    assert points == [
        {
            "measurement": "TrainingReadiness",
            "time": "2026-01-15T06:30:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "level": "HIGH",
                "score": 72,
                "sleepScore": 85,
                "sleepScoreFactorPercent": 30,
                "recoveryTime": 12,
                "recoveryTimeFactorPercent": 20,
                "acwrFactorPercent": 15,
                "acuteLoad": 320,
                "stressHistoryFactorPercent": 10,
                "hrvFactorPercent": 25,
            },
        }
    ]


def test_blood_pressure_exact_point_shape_before_refactor(garmin_fetch_module):
    """
    Captures get_blood_pressure's CURRENT exact behavior, including a real
    pre-existing inconsistency: unlike get_training_readiness, this function
    never calls .isoformat() -- "time" is a raw datetime object, not a
    string. This test documents that baseline; it is deliberately NOT kept
    passing unchanged after the refactor (see
    test_blood_pressure_exact_point_shape_after_refactor below) because
    routing through build_timestamped_point's auto-isoformat-conversion
    normalizes this to a string -- a disclosed, understood change to this
    function's *return value*, not to what ultimately gets written to
    InfluxDB (the influxdb client accepts both types identically; this
    exact raw-datetime code has been running in production without issue).
    """
    points = garmin_fetch_module.get_blood_pressure(DATE_STR)
    assert len(points) == 1
    point = points[0]
    assert point["measurement"] == "BloodPressure"
    assert point["time"] == datetime(2026, 1, 15, 6, 30, tzinfo=timezone.utc)
    assert isinstance(point["time"], datetime)  # not a string, today
    assert point["tags"] == {
        "Device": "TestDevice",
        "Database_Name": "SmokeTestDB",
        "Source": "MANUAL",
    }
    assert point["fields"] == {"Systolic": 120, "Diastolic": 80, "Pulse": 65}
