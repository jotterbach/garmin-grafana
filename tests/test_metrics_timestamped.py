"""
Characterization tests for the "multi-point-per-day, real API timestamp"
shape functions being migrated to metric_points.build_timestamped_point()
on this branch: get_training_readiness, get_blood_pressure,
get_training_status, get_solar_intensity, get_lactate_threshold.

Each test is written and confirmed passing against the *current*
(pre-migration) implementation first, then must keep passing unchanged
after that function is refactored -- except where a function's migration
involves a disclosed behavioral change (see test_blood_pressure_exact_point_shape's
docstring), in which case the test is updated to match the new, understood
behavior rather than kept red.
"""

from datetime import datetime

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


def test_training_status_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_training_status(DATE_STR)
    assert points == [
        {
            "measurement": "TrainingStatus",
            "time": "2026-01-15T07:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "trainingStatus": 4,
                "trainingStatusFeedbackPhrase": "PRODUCTIVE",
                "weeklyTrainingLoad": 850,
                "fitnessTrend": "MAINTAINING",
                "acwrPercent": 105,
                "dailyTrainingLoadAcute": 320,
                "dailyTrainingLoadChronic": 280,
                "maxTrainingLoadChronic": 400,
                "minTrainingLoadChronic": 150,
                "dailyAcuteChronicWorkloadRatio": 1.14,
            },
        }
    ]


def test_solar_intensity_exact_point_shape_before_refactor(garmin_fetch_module):
    """
    Captures get_solar_intensity's CURRENT exact behavior. Same
    raw-datetime-object "time" inconsistency as get_blood_pressure's
    pre-refactor code (no .isoformat() call) -- see that function's
    now-updated test for the full rationale. This test documents that
    baseline; it is deliberately superseded once the refactor lands (see
    test_solar_intensity_exact_point_shape below), the same way
    get_blood_pressure's before/after pair was handled.
    """
    points = garmin_fetch_module.get_solar_intensity(DATE_STR)
    assert len(points) == 1
    point = points[0]
    assert point["measurement"] == "SolarIntensity"
    assert isinstance(point["time"], datetime)  # not a string, today
    assert point["tags"] == {"Device": "TestDevice", "Database_Name": "SmokeTestDB"}
    assert point["fields"] == {"solarUtilization": 45, "activityTimeGainMs": 1200}


def test_blood_pressure_exact_point_shape(garmin_fetch_module):
    """
    Post-migration point shape for get_blood_pressure, now routed through
    build_timestamped_point. Pre-refactor, this function built its "time"
    field from a raw datetime object (no .isoformat() call) -- unlike
    get_training_readiness, which already called .isoformat(). Migrating
    through the shared helper normalizes "time" to the isoformat string
    seen below; this is a disclosed, understood change to this function's
    Python-level return value, not to what ultimately gets written to
    InfluxDB (the influxdb client accepts both raw datetime objects and ISO
    strings identically, and this exact raw-datetime code ran successfully
    in production for a long time). Everything else (measurement, tags
    including the extra "Source" tag, fields) is unchanged from before.
    """
    points = garmin_fetch_module.get_blood_pressure(DATE_STR)
    assert points == [
        {
            "measurement": "BloodPressure",
            "time": "2026-01-15T06:30:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "Source": "MANUAL",
            },
            "fields": {"Systolic": 120, "Diastolic": 80, "Pulse": 65},
        }
    ]
