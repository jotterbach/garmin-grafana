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
