"""
Characterization tests for phase 4 of the metric registry refactor:
get_sleep_data -- the highest-complexity remaining function, migrating
piece by piece onto metric_points.build_timestamped_point(). One test per
sub-shape, each written and confirmed passing against the *current*
(pre-migration) implementation before that specific piece is refactored.

See tests/fixtures/sleep.json for the fixture data and why each entry is
shaped the way it is (real-schema types, issue #43's 0-for-deep-sleep,
issue #127's duplicate terminal point, and the entry.get("activityLevel",
-1.0) default bug found and fixed alongside the fixture).
"""

DATE_STR = "2026-01-15"


def test_sleep_summary_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    summary_points = [p for p in points if p["measurement"] == "SleepSummary"]
    assert summary_points == [
        {
            "measurement": "SleepSummary",
            "time": "2026-01-15T09:20:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "sleepTimeSeconds": 25200,
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 4800,
                "awakeSleepSeconds": 600,
                "averageSpO2Value": 96.5,
                "lowestSpO2Value": 91,
                "highestSpO2Value": 99,
                "averageRespirationValue": 14.2,
                "lowestRespirationValue": 11.0,
                "highestRespirationValue": 18.0,
                "awakeCount": 3,
                "avgSleepStress": 18.0,
                "sleepScore": 82,
                "restlessMomentsCount": 12,
                "avgOvernightHrv": 45.0,
                "bodyBatteryChange": 55,
                "restingHeartRate": 52,
                "avgSkinTempDeviationC": -0.2,
                "avgSkinTempDeviationF": -0.36,
            },
        }
    ]


def test_sleep_movement_exact_point_shape(garmin_fetch_module):
    """No per-entry guard at all -- every entry unconditionally produces
    a point. The second entry has no "activityLevel" key, exercising the
    entry.get("activityLevel", -1.0) default (fixed from an int default
    to a float one -- see the fixture-prep commit for why)."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    movement_points = [
        p for p in points
        if p["measurement"] == "SleepIntraday" and "SleepMovementActivityLevel" in p["fields"]
    ]
    assert movement_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T02:30:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"SleepMovementActivityLevel": 2.5, "SleepMovementActivitySeconds": 300},
        },
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T02:35:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"SleepMovementActivityLevel": -1.0, "SleepMovementActivitySeconds": 300},
        },
    ]


def test_sleep_restlessness_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0 value is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    restless_points = [p for p in points if "sleepRestlessValue" in p["fields"]]
    assert restless_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T02:45:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"sleepRestlessValue": 3},
        },
    ]


def test_sleep_spo2_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0 reading is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    spo2_points = [p for p in points if "spo2Reading" in p["fields"]]
    assert spo2_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T02:55:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"spo2Reading": 95},
        },
    ]


def test_sleep_respiration_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0.0 reading is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    respiration_points = [p for p in points if "respirationValue" in p["fields"]]
    assert respiration_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T03:10:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"respirationValue": 13.5},
        },
    ]


def test_sleep_heart_rate_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0 value is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    hr_points = [p for p in points if "heartRate" in p["fields"]]
    assert hr_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T03:20:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"heartRate": 54},
        },
    ]


def test_sleep_stress_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0 value is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    stress_points = [p for p in points if "stressValue" in p["fields"]]
    assert stress_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T03:35:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"stressValue": 15},
        },
    ]


def test_sleep_body_battery_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0 value is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    bb_points = [p for p in points if "bodyBattery" in p["fields"]]
    assert bb_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T03:45:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"bodyBattery": 68},
        },
    ]


def test_sleep_hrv_exact_point_shape(garmin_fetch_module):
    """Truthy-only guard: a 0.0 value is dropped."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    hrv_points = [p for p in points if "hrvData" in p["fields"]]
    assert hrv_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T03:55:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"hrvData": 42.5},
        },
    ]


def test_sleep_levels_exact_point_shape(garmin_fetch_module):
    """The highest-risk sub-shape: truthy-or-zero guard (issue #43: 0.0
    is deep sleep, kept) PLUS a duplicate terminal point (issue #127)
    appended after the loop, using Python's leaked loop variable (the
    *last* entry), guarded only by endGMT truthiness -- NOT by the
    per-entry activityLevel guard. The fixture's last entry has
    activityLevel: null (dropped by the per-entry guard, so no regular
    point for it) but a valid endGMT, so the duplicate point still fires
    with a None field -- this exact quirk is preserved, not "fixed"."""
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    level_points = [p for p in points if "SleepStageLevel" in p["fields"]]
    assert level_points == [
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T02:30:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"SleepStageLevel": 1.0, "SleepStageSeconds": 1800},
        },
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T03:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"SleepStageLevel": 0.0, "SleepStageSeconds": 1800},
        },
        {
            "measurement": "SleepIntraday",
            "time": "2026-01-15T04:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"SleepStageLevel": None},
        },
    ]
