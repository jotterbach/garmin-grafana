"""
Characterization tests for the "multi-point-per-day, real API timestamp"
shape functions being migrated to metric_points.build_timestamped_point()
on this branch: get_training_readiness, get_blood_pressure,
get_training_status, get_solar_intensity, get_lactate_threshold.

Each test is written and confirmed passing against the *current*
(pre-migration) implementation first, then must keep passing unchanged
after that function is refactored -- except where a function's migration
involves a disclosed behavioral change (see test_blood_pressure_exact_point_shape's
and test_solar_intensity_exact_point_shape's docstrings), in which case the
test is updated to match the new, understood behavior rather than kept red.
"""

from datetime import datetime

import pytz

DATE_STR = "2026-01-15"

# Mirrors get_lactate_threshold's own (implicit-local-timezone) timestamp
# computation exactly, rather than hardcoding a value that would silently
# depend on this test machine's system timezone -- see that function's
# refactor commit for why this computation itself is being preserved
# as-is, not "fixed".
LACTATE_THRESHOLD_EXPECTED_TIME = datetime.fromtimestamp(
    datetime.strptime(DATE_STR, "%Y-%m-%d").timestamp(), tz=pytz.timezone("UTC")
).isoformat()


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


def test_lactate_threshold_exact_point_shape(garmin_fetch_module):
    """
    Default LACTATE_THRESHOLD_SPORTS is a single sport ("RUNNING"), used for
    speed/heart-rate threshold; default FTP_SPORTS is ("RUNNING", "CYCLING")
    -- a deliberately separate, broader sport list, since FTP applies to
    cycling too but lactateThresholdSpeed/HeartRate don't (see #22). So
    get_lactate_threshold builds four endpoints (speed + HR for running,
    power/FTP for running + cycling) and FakeGarmin.connectapi returns the
    same canned value for all four -- four single-field points, in
    endpoint-iteration order (LACTATE_THRESHOLD_SPORTS's endpoints first,
    then FTP_SPORTS's). Written to expect the post-cycling-FTP four-endpoint
    shape already (confirmed failing against the running-only
    three-endpoint implementation before that change landed).

    Real, live-verified bug (found via a Grafana panel showing an
    implausible ~43 min/km pace, confirmed against the athlete's actual
    Garmin Connect display): the lactateThresholdSpeed endpoint's raw
    "value" is *not* true m/s -- it's off by a factor of 10 from real m/s
    (0.3888878 raw vs. a real, Garmin-Connect-confirmed ~4:1x/km pace,
    i.e. ~3.89 m/s). HeartRateThreshold/PowerThreshold need no such
    correction -- both matched real expectations at face value. So only
    the SpeedThreshold_* field gets the x10 correction, applied once here
    at ingestion so every downstream consumer (Grafana, InfluxQL) sees
    real m/s, not the raw API's mis-scaled value.
    """
    points = garmin_fetch_module.get_lactate_threshold(DATE_STR)
    assert points == [
        {
            "measurement": "LactateThreshold",
            "time": LACTATE_THRESHOLD_EXPECTED_TIME,
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"SpeedThreshold_RUNNING": 1650},
        },
        {
            "measurement": "LactateThreshold",
            "time": LACTATE_THRESHOLD_EXPECTED_TIME,
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"HeartRateThreshold_RUNNING": 165},
        },
        {
            "measurement": "LactateThreshold",
            "time": LACTATE_THRESHOLD_EXPECTED_TIME,
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"PowerThreshold_RUNNING": 165},
        },
        {
            "measurement": "LactateThreshold",
            "time": LACTATE_THRESHOLD_EXPECTED_TIME,
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"PowerThreshold_CYCLING": 165},
        },
    ]


def test_lactate_threshold_passes_query_params_separately_not_embedded_in_path(
    garmin_fetch_module,
):
    """
    Regression guard: garminconnect 0.3.16 added strict path validation to
    connectapi() that rejects a literal '?' in the path -- callers must pass
    query params via the params= kwarg instead. get_lactate_threshold used
    to build f"{path}?aggregation=daily&sport={sport}" directly, which broke
    under 0.3.16 (confirmed live against the real API before this fix).
    Asserts the actual call shape, not just that it doesn't crash against
    FakeGarmin (which never validated this either way).
    """
    calls = []

    def fake_connectapi(endpoint, method="GET", params=None):
        calls.append((endpoint, params))
        return []

    garmin_fetch_module.garmin_obj.connectapi = fake_connectapi

    garmin_fetch_module.get_lactate_threshold(DATE_STR)

    assert calls, "expected at least one connectapi call"
    for endpoint, params in calls:
        assert "?" not in endpoint, f"query string embedded in path: {endpoint!r}"
        assert params["aggregation"] == "daily"
        assert params["sport"] in ("RUNNING", "CYCLING")


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


def test_solar_intensity_exact_point_shape(garmin_fetch_module):
    """
    Post-migration point shape for get_solar_intensity, now routed through
    build_timestamped_point. Same disclosed raw-datetime -> isoformat-string
    normalization as get_blood_pressure's migration -- see that function's
    test docstring for the full rationale.
    """
    points = garmin_fetch_module.get_solar_intensity(DATE_STR)
    assert points == [
        {
            "measurement": "SolarIntensity",
            "time": "2026-01-15T06:30:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"solarUtilization": 45, "activityTimeGainMs": 1200},
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
