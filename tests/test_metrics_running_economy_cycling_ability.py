"""
Characterization tests for get_running_economy (#45) and get_cycling_ability
(#49), both new functions built on the existing build_daily_summary_point
shape from day one -- no "before" implementation to characterize against,
unlike the metric-registry migration phases.

Both call garmin_obj.connectapi() directly (there's no dedicated
FakeGarmin method for either, same pattern as get_lactate_threshold), so
each test overrides connectapi on the fixture's garmin_obj instance with
canned responses matching real, live-verified shapes (see issues #45/#49
for the research and exact confirmed field names).
"""

DATE_STR = "2026-01-15"


def test_running_economy_exact_point_shape(garmin_fetch_module):
    garmin_fetch_module.garmin_obj.connectapi = lambda endpoint, method="GET", params=None: [
        {"calendarDate": DATE_STR, "score": 202, "classification": "WELL_TRAINED"}
    ]

    points = garmin_fetch_module.get_running_economy(DATE_STR)

    assert points == [
        {
            "measurement": "RunningEconomy",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"score": 202, "classification": "WELL_TRAINED"},
        }
    ]


def test_running_economy_returns_no_points_on_a_non_qualifying_day(garmin_fetch_module):
    """
    Confirmed live (see #45): most days are null/null -- Running Economy is
    only computed on days with a qualifying run. build_daily_summary_point's
    existing all-fields-None guard handles this without any special-casing
    here.
    """
    garmin_fetch_module.garmin_obj.connectapi = lambda endpoint, method="GET", params=None: [
        {"calendarDate": DATE_STR, "score": None, "classification": None}
    ]

    points = garmin_fetch_module.get_running_economy(DATE_STR)

    assert points == []


def test_cycling_ability_exact_point_shape(garmin_fetch_module):
    garmin_fetch_module.garmin_obj.connectapi = lambda endpoint, method="GET", params=None: {
        "userProfilePK": 11886273,
        "startDate": DATE_STR,
        "endDate": DATE_STR,
        "cyclingAbilitiesMap": {
            DATE_STR: {
                "userProfilePk": 11886273,
                "deviceId": 3611912017,
                "calendarDate": DATE_STR,
                "timestamp": f"{DATE_STR}T07:52:45.0",
                "primaryTrainingDevice": False,
                "aerobicEndurance": 89,
                "aerobicCapacity": 82,
                "anaerobicCapacity": 57,
                "profileType": "ENDURANCE_SPECIALIST",
                "profileTypeFeedback": "ENDURANCE_SPECIALIST",
                "aerobicEnduranceFeedback": "HIGH_STRONGEST_120MIN_POWER_DEFICIT",
                "aerobicCapacityFeedback": "HIGH_20MIN_POWER_DEFICIT",
                "anaerobicCapacityFeedback": "HIGH_POWER_DEFICIT",
            }
        },
    }

    points = garmin_fetch_module.get_cycling_ability(DATE_STR)

    assert points == [
        {
            "measurement": "CyclingAbility",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "aerobicEndurance": 89,
                "aerobicCapacity": 82,
                "anaerobicCapacity": 57,
                "profileType": "ENDURANCE_SPECIALIST",
                "profileTypeFeedback": "ENDURANCE_SPECIALIST",
                "aerobicEnduranceFeedback": "HIGH_STRONGEST_120MIN_POWER_DEFICIT",
                "aerobicCapacityFeedback": "HIGH_20MIN_POWER_DEFICIT",
                "anaerobicCapacityFeedback": "HIGH_POWER_DEFICIT",
            },
        }
    ]


def test_cycling_ability_returns_no_points_when_date_missing_from_map(garmin_fetch_module):
    garmin_fetch_module.garmin_obj.connectapi = lambda endpoint, method="GET", params=None: {
        "userProfilePK": 11886273,
        "startDate": DATE_STR,
        "endDate": DATE_STR,
        "cyclingAbilitiesMap": {},
    }

    points = garmin_fetch_module.get_cycling_ability(DATE_STR)

    assert points == []


def test_cycling_ability_requests_uppercase_aggregation(garmin_fetch_module):
    """
    Regression guard: confirmed live (see #49) this endpoint returns a 400
    for lowercase aggregation, unlike every other metrics-service endpoint
    in this codebase which use lowercase. Easy to get wrong by
    pattern-matching get_lactate_threshold/get_running_economy.
    """
    calls = []

    def fake_connectapi(endpoint, method="GET", params=None):
        calls.append((endpoint, params))
        return {"cyclingAbilitiesMap": {}}

    garmin_fetch_module.garmin_obj.connectapi = fake_connectapi

    garmin_fetch_module.get_cycling_ability(DATE_STR)

    assert len(calls) == 1
    endpoint, params = calls[0]
    assert "?" not in endpoint
    assert params["aggregation"] == "DAILY"
