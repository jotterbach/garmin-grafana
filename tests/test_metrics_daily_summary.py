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
                "strengthScore": 6.5,
                "enduranceScore": 7.2,
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
