"""
Characterization tests for the "single daily-summary point" shape functions
being migrated to metric_points.build_daily_summary_point() on this branch:
get_hillscore, get_race_predictions, get_fitness_age, get_vo2_max,
get_endurance_score, get_hydration.

Each test is written and confirmed passing against the *current* (pre-
migration) implementation first, then must keep passing unchanged after that
function is refactored -- that's the actual verification that the refactor
didn't change behavior, not just "it still runs."

DATE_STR intentionally matches tests/test_smoke_metrics.py's convention.
"""

DATE_STR = "2026-01-15"


def test_hillscore_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_hillscore(DATE_STR)
    assert points == [
        {
            "measurement": "HillScore",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "strengthScore": 46,
                "enduranceScore": 47,
                "hillScoreClassificationId": 3,
                "overallScore": 68,
                "hillScoreFeedbackPhraseId": 12,
                "vo2MaxPreciseValue": 47.2,
            },
        }
    ]


def test_race_predictions_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_race_predictions(DATE_STR)
    assert points == [
        {
            "measurement": "RacePredictions",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "time5K": 1320,
                "time10K": 2760,
                "timeHalfMarathon": 6120,
                "timeMarathon": 12900,
            },
        }
    ]


def test_fitness_age_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_fitness_age(DATE_STR)
    assert points == [
        {
            "measurement": "FitnessAge",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "chronologicalAge": 32.0,
                "fitnessAge": 27,
                "achievableFitnessAge": 24,
            },
        }
    ]


def test_vo2_max_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_vo2_max(DATE_STR)
    assert points == [
        {
            "measurement": "VO2_Max",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"VO2_max_value": 47.2, "VO2_max_value_cycling": None},
        }
    ]


def test_vo2_max_zero_value_is_treated_as_no_data(garmin_fetch_module):
    """
    get_vo2_max's original guard is `if vo2_max_value or vo2_max_value_cycling:`
    (truthy), NOT "not all fields are None" like build_daily_summary_point's
    own guard -- a value of 0 (falsy, but not None) must still produce no
    point, matching the pre-refactor behavior exactly. This is exactly the
    kind of subtle divergence a naive helper-ification would silently
    introduce (0 is "real data" under an is-None check, but VO2_max=0 was
    never a real value the original code would have written).
    """
    garmin_fetch_module.garmin_obj._daily["max_metrics"] = [
        {"generic": {"vo2MaxPreciseValue": 0}, "cycling": {"vo2MaxPreciseValue": None}}
    ]
    points = garmin_fetch_module.get_vo2_max(DATE_STR)
    assert points == []


def test_endurance_score_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_endurance_score(DATE_STR)
    assert points == [
        {
            "measurement": "EnduranceScore",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {"EnduranceScore": 412},
        }
    ]


def test_endurance_score_zero_value_is_treated_as_no_data(garmin_fetch_module):
    """Original guard is `if endurance_dict.get("overallScore"):` (truthy),
    not an is-None check -- same subtlety as get_vo2_max."""
    garmin_fetch_module.garmin_obj._daily["endurance_score"] = {"overallScore": 0}
    points = garmin_fetch_module.get_endurance_score(DATE_STR)
    assert points == []


def test_hydration_exact_point_shape(garmin_fetch_module):
    points = garmin_fetch_module.get_hydration(DATE_STR)
    assert points == [
        {
            "measurement": "Hydration",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                "ValueInML": 1800.0,
                "SweatLossInML": 450.0,
                "GoalInML": 3000.0,
                "ActivityIntakeInML": 200.0,
            },
        }
    ]


def test_lactate_threshold_exact_point_shape(garmin_fetch_module):
    """
    #18: get_lactate_threshold used to compute its own timestamp via
    datetime.fromtimestamp(datetime.strptime(date_str, ...).timestamp(),
    tz=UTC) -- a round-trip through .timestamp() that interprets the naive
    datetime as being in the *system's local timezone* before relabeling
    it UTC, only actually correct because the container happens to run
    with tz=UTC set. Moved onto build_daily_summary_point (same
    timezone-safe midnight computation as get_hillscore/get_hydration/
    etc.) instead, which also merges what used to be up to 4 separate
    single-field points (one per endpoint, all sharing the same day) into
    the single multi-field point this measurement actually represents --
    LactateThreshold is a daily-summary shape, not an arbitrary-timestamp
    one.

    Default LACTATE_THRESHOLD_SPORTS is a single sport ("RUNNING"), used
    for speed/heart-rate threshold; default FTP_SPORTS is
    ("RUNNING", "CYCLING") -- a deliberately separate, broader sport list,
    since FTP applies to cycling too but lactateThresholdSpeed/HeartRate
    don't (see #22). FakeGarmin.connectapi returns the same canned value
    for all four endpoint calls.
    """
    points = garmin_fetch_module.get_lactate_threshold(DATE_STR)
    assert points == [
        {
            "measurement": "LactateThreshold",
            "time": "2026-01-15T00:00:00+00:00",
            "tags": {"Device": "TestDevice", "Database_Name": "SmokeTestDB"},
            "fields": {
                # x10: lactateThresholdSpeed's raw "value" is not true
                # m/s, confirmed live against the athlete's real Garmin
                # Connect display (0.3888878 raw vs. a real ~4:1x/km
                # pace) -- see garmin_fetch.py's get_lactate_threshold.
                "SpeedThreshold_RUNNING": 1650,
                "HeartRateThreshold_RUNNING": 165,
                "PowerThreshold_RUNNING": 165,
                "PowerThreshold_CYCLING": 165,
            },
        }
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


def test_daily_fetch_write_respects_custom_fetch_selection_subset(garmin_fetch_module, monkeypatch):
    """
    Narrower than test_smoke_pipeline.py's test_daily_fetch_write_end_to_end
    (which always uses the full default FETCH_SELECTION) -- proves the
    dispatch is genuinely data-driven by selecting only two metrics and
    confirming *only* those measurements get written, not the full set.
    This is the baseline the upcoming dispatch-table refactor of
    daily_fetch_write's if-chain must keep passing unchanged.
    """
    monkeypatch.setattr(garmin_fetch_module, "FETCH_SELECTION", "hydration,hill_score")
    garmin_fetch_module.daily_fetch_write(DATE_STR)

    storage = garmin_fetch_module.INFLUXDB_STORAGE
    assert storage.query('SELECT * FROM "Hydration"')
    assert storage.query('SELECT * FROM "HillScore"')
    assert storage.query('SELECT * FROM "FitnessAge"') == []
    assert storage.query('SELECT * FROM "DailyStats"') == []
    assert storage.query('SELECT * FROM "RacePredictions"') == []
