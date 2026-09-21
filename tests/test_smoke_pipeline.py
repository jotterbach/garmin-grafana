"""
The two highest-value smoke tests: does the actual orchestration function
that runs on every real fetch cycle complete without exploding, and does a
write actually round-trip through the InfluxDB client library.

This is the pair of tests most likely to catch the class of regression that
motivated this suite -- something that breaks the whole pipeline, not one
metric's field mapping.
"""

from datetime import datetime, timezone

DATE_STR = "2026-01-15"


def test_daily_fetch_write_end_to_end(garmin_fetch_module):
    # Should not raise for the default FETCH_SELECTION set with a
    # FakeGarmin backing every call.
    garmin_fetch_module.daily_fetch_write(DATE_STR)

    client = garmin_fetch_module.influxdbclient
    for measurement in (
        "DailyStats",
        "SleepSummary",
        "StepsIntraday",
        "HeartRateIntraday",
        "StressIntraday",
        "BreathingRateIntraday",
        "HRV_Intraday",
        "FitnessAge",
        "VO2_Max",
        "ActivitySummary",
        "RacePredictions",
        "BodyComposition",
        "LifestyleJournal",
    ):
        result = list(client.query(f'SELECT * FROM "{measurement}"').get_points())
        assert result, f"expected at least one point written to {measurement}"


def test_write_points_to_influxdb_round_trip(garmin_fetch_module):
    point = {
        "measurement": "SmokeTestRoundTrip",
        "time": datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat(),
        "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
        "fields": {"value": 42},
    }

    garmin_fetch_module.write_points_to_influxdb([point])

    result = list(
        garmin_fetch_module.influxdbclient.query(
            'SELECT * FROM "SmokeTestRoundTrip"'
        ).get_points()
    )
    assert len(result) == 1
    assert result[0]["value"] == 42
