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
