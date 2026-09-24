"""
Per-metric smoke tests for the functions covered by the default
FETCH_SELECTION (see garmin_fetch.py:62), plus body_composition (weigh-ins).

Not exhaustive correctness tests -- just confirms each function still
returns points shaped the way daily_fetch_write and Grafana expect
(measurement name present, no exception) when fed a realistic canned API
response. Fine-grained coverage of every field/edge case is deferred to the
individual refactors that touch these functions.
"""

DATE_STR = "2026-01-15"


def _measurements(points):
    return {p["measurement"] for p in points}


def test_daily_stats(garmin_fetch_module):
    points = garmin_fetch_module.get_daily_stats(DATE_STR)
    assert _measurements(points) == {"DailyStats"}
    assert points[0]["fields"]["totalSteps"] == 9800


def test_sleep_data(garmin_fetch_module):
    points = garmin_fetch_module.get_sleep_data(DATE_STR)
    assert "SleepSummary" in _measurements(points)
    summary = next(p for p in points if p["measurement"] == "SleepSummary")
    assert summary["fields"]["sleepScore"] == 82


def test_intraday_steps(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_steps(DATE_STR)
    assert len(points) == 2
    assert _measurements(points) == {"StepsIntraday"}


def test_intraday_heart_rate(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_hr(DATE_STR)
    assert len(points) == 2
    assert _measurements(points) == {"HeartRateIntraday"}


def test_intraday_stress_and_body_battery(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_stress(DATE_STR)
    assert _measurements(points) == {"StressIntraday", "BodyBatteryIntraday"}


def test_intraday_breathing_rate(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_br(DATE_STR)
    assert len(points) == 2
    assert _measurements(points) == {"BreathingRateIntraday"}


def test_intraday_hrv(garmin_fetch_module):
    points = garmin_fetch_module.get_intraday_hrv(DATE_STR)
    assert len(points) == 2
    assert points[0]["measurement"] == "HRV_Intraday"
    assert points[1]["measurement"] == "HRV_Status"


def test_fitness_age(garmin_fetch_module):
    points = garmin_fetch_module.get_fitness_age(DATE_STR)
    assert points[0]["measurement"] == "FitnessAge"
    assert points[0]["fields"]["fitnessAge"] == 27


def test_vo2_max(garmin_fetch_module):
    points = garmin_fetch_module.get_vo2_max(DATE_STR)
    assert points[0]["measurement"] == "VO2_Max"


def test_activity_summary(garmin_fetch_module):
    points, gps_ids, strength_ids = garmin_fetch_module.get_activity_summary(DATE_STR)
    assert _measurements(points) == {"ActivitySummary"}
    # Both fixture activities (a running activity and a strength activity)
    # are GPS-less: no FIT download/parsing should be triggered by this
    # smoke test. The strength activity is collected into strength_ids for
    # get_strength_training_data to pick up separately.
    assert gps_ids == {}
    assert strength_ids.keys() == {9876543211}
    tagged_ids = {p["tags"]["ActivityID"] for p in points}
    assert tagged_ids == {9876543210, 9876543211}


def test_race_predictions(garmin_fetch_module):
    points = garmin_fetch_module.get_race_predictions(DATE_STR)
    assert points[0]["measurement"] == "RacePredictions"


def test_body_composition(garmin_fetch_module):
    points = garmin_fetch_module.get_body_composition(DATE_STR)
    assert points[0]["measurement"] == "BodyComposition"
    assert points[0]["fields"]["weight"] == 72500.0


def test_lifestyle_data(garmin_fetch_module):
    points = garmin_fetch_module.get_lifestyle_data(DATE_STR)
    assert len(points) == 2
    assert _measurements(points) == {"LifestyleJournal"}
