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
