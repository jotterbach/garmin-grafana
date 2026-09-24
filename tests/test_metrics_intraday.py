"""
Characterization tests for phase 3 of the metric registry refactor:
get_intraday_hr, get_intraday_br, get_intraday_hrv, get_intraday_steps,
get_intraday_stress, get_daily_stats, get_body_composition,
get_lifestyle_data -- all migrating to the existing
metric_points.build_timestamped_point() / build_daily_summary_point()
helpers (no new helper needed this phase, see the approved plan).

Each test is written and confirmed passing against the *current*
(pre-migration) implementation first, then must keep passing unchanged
after that function is refactored.

The fixtures deliberately include a zero-value entry in heart_rates,
stress (both arrays), respiration, and hrv: get_intraday_hr/br/hrv use a
truthy-only guard (a 0 reading is dropped), while get_intraday_steps and
get_intraday_stress use a truthy-or-zero guard (a 0 reading is kept) --
this is a real, pre-existing inconsistency across these functions, not
something to unify, and the tests below pin down both behaviors exactly.
"""

DATE_STR = "2026-01-15"


def test_intraday_hr_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_hr(DATE_STR)
    assert points == [
        {
            "measurement": "HeartRateIntraday",
            "time": "2026-01-15T07:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"HeartRate": 58},
        },
        {
            "measurement": "HeartRateIntraday",
            "time": "2026-01-15T07:05:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"HeartRate": 61},
        },
    ]


def test_intraday_br_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_br(DATE_STR)
    assert points == [
        {
            "measurement": "BreathingRateIntraday",
            "time": "2026-01-15T07:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"BreathingRate": 14.0},
        },
        {
            "measurement": "BreathingRateIntraday",
            "time": "2026-01-15T07:05:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"BreathingRate": 14.5},
        },
    ]


def test_intraday_hrv_exact_point_shape(garmin_fetch_module):
    """
    #48: get_hrv_data's response also carries an hrvSummary block (weekly
    avg, last night's avg, Garmin's own qualitative status, and the
    balanced-range baseline) that was previously fetched but discarded --
    zero extra API calls, just extract more of what's already there.
    """
    points = garmin_fetch_module.get_intraday_hrv(DATE_STR)
    assert points == [
        {
            "measurement": "HRV_Intraday",
            "time": "2026-01-15T06:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"hrvValue": 45},
        },
        {
            "measurement": "HRV_Status",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "weeklyAvg": 52,
                "lastNightAvg": 48,
                "lastNight5MinHigh": 61,
                "baselineLowUpper": 40,
                "baselineBalancedLow": 45,
                "baselineBalancedUpper": 60,
                "status": "BALANCED",
                "feedbackPhrase": "HRV_BALANCED_7",
            },
        },
    ]


def test_intraday_steps_exact_point_shape(garmin_fetch_module):
    """Unlike hr/br/hrv, this guard is truthy-or-zero -- a 0 steps
    reading is kept, not dropped."""
    points = garmin_fetch_module.get_intraday_steps(DATE_STR)
    assert points == [
        {
            "measurement": "StepsIntraday",
            "time": "2026-01-15T06:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"StepsCount": 320},
        },
        {
            "measurement": "StepsIntraday",
            "time": "2026-01-15T06:15:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"StepsCount": 0},
        },
    ]


def test_intraday_stress_exact_point_shape(garmin_fetch_module):
    """Two measurements from two separate arrays in one function, both
    with a truthy-or-zero guard (0 kept, matching get_intraday_steps,
    not the truthy-only hr/br/hrv pattern)."""
    points = garmin_fetch_module.get_intraday_stress(DATE_STR)
    assert points == [
        {
            "measurement": "StressIntraday",
            "time": "2026-01-15T07:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"stressLevel": 22},
        },
        {
            "measurement": "StressIntraday",
            "time": "2026-01-15T07:05:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"stressLevel": 28},
        },
        {
            "measurement": "StressIntraday",
            "time": "2026-01-15T07:10:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"stressLevel": 0},
        },
        {
            "measurement": "BodyBatteryIntraday",
            "time": "2026-01-15T07:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"BodyBatteryLevel": 74},
        },
        {
            "measurement": "BodyBatteryIntraday",
            "time": "2026-01-15T07:05:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"BodyBatteryLevel": 72},
        },
        {
            "measurement": "BodyBatteryIntraday",
            "time": "2026-01-15T07:10:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"BodyBatteryLevel": 0},
        },
    ]


def test_daily_stats_exact_point_shape(garmin_fetch_module):
    """Guard is a compound (timestamp truthy AND date < today) check, not
    a fields-None guard -- unaffected by which fields are populated."""
    points = garmin_fetch_module.get_daily_stats(DATE_STR)
    assert points == [
        {
            "measurement": "DailyStats",
            "time": "2026-01-15T06:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "activeKilocalories": 650.0,
                "bmrKilocalories": 1650.0,
                "totalSteps": 9800,
                "totalDistanceMeters": 7200,
                "highlyActiveSeconds": 1800,
                "activeSeconds": 5400,
                "sedentarySeconds": 43200,
                "sleepingSeconds": 25200,
                "moderateIntensityMinutes": 45,
                "vigorousIntensityMinutes": 20,
                "floorsAscendedInMeters": 24.4,
                "floorsDescendedInMeters": 24.4,
                "floorsAscended": 8.0,
                "floorsDescended": 8.0,
                "minHeartRate": 48,
                "maxHeartRate": 172,
                "restingHeartRate": 52,
                "minAvgHeartRate": 50,
                "maxAvgHeartRate": 148,
                "avgSkinTempDeviationC": -0.2,
                "avgSkinTempDeviationF": -0.36,
                "stressDuration": None,
                "restStressDuration": None,
                "activityStressDuration": None,
                "uncategorizedStressDuration": None,
                "totalStressDuration": None,
                "lowStressDuration": None,
                "mediumStressDuration": None,
                "highStressDuration": None,
                "stressPercentage": None,
                "restStressPercentage": None,
                "activityStressPercentage": None,
                "uncategorizedStressPercentage": None,
                "lowStressPercentage": None,
                "mediumStressPercentage": None,
                "highStressPercentage": None,
                "bodyBatteryChargedValue": None,
                "bodyBatteryDrainedValue": None,
                "bodyBatteryHighestValue": None,
                "bodyBatteryLowestValue": None,
                "bodyBatteryDuringSleep": None,
                "bodyBatteryAtWakeTime": None,
                "averageSpo2": None,
                "lowestSpo2": None,
            },
        }
    ]


def test_body_composition_exact_point_shape(garmin_fetch_module):
    """Two weigh-in entries: the first has a real timestampGMT (used
    as-is, even though it happens to be on a different calendar day than
    DATE_STR -- the API's own timestamp always wins); the second has a
    null timestampGMT and falls back to DATE_STR's midnight (issue #15).
    """
    points = garmin_fetch_module.get_body_composition(DATE_STR)
    assert points == [
        {
            "measurement": "BodyComposition",
            "time": "2026-01-16T00:00:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "Frequency": "Intraday",
                "SourceType": "MANUAL",
            },
            "fields": {
                "weight": 72500.0,
                "bmi": 22.4,
                "bodyFat": 15.2,
                "bodyWater": 58.1,
                "boneMass": 3200,
                "muscleMass": 34500,
                "physiqueRating": 5,
                "visceralFat": 4,
            },
        },
        {
            "measurement": "BodyComposition",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "Frequency": "Intraday",
                "SourceType": "INDEX_SCALE",
            },
            "fields": {
                "weight": 72400.0,
                "bmi": 22.3,
                "bodyFat": None,
                "bodyWater": None,
                "boneMass": None,
                "muscleMass": None,
                "physiqueRating": None,
                "visceralFat": None,
            },
        },
    ]


def test_lifestyle_data_exact_point_shape(garmin_fetch_module):
    """Midnight shape (build_daily_summary_point), looped per behavior
    log entry -- unlike every other function in this phase, which uses
    the arbitrary-timestamp shape."""
    points = garmin_fetch_module.get_lifestyle_data(DATE_STR)
    assert points == [
        {
            "measurement": "LifestyleJournal",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "behavior": "Alcohol",
                "category": "SUBSTANCE",
            },
            "fields": {"status": 0, "value": 0.0},
        },
        {
            "measurement": "LifestyleJournal",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "behavior": "Caffeine",
                "category": "SUBSTANCE",
            },
            "fields": {"status": 1, "value": 95.0},
        },
    ]
