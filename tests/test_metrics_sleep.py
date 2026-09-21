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
