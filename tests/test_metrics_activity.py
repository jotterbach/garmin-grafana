"""
Characterization tests for phase 6 of the metric registry / activity
pipeline refactor: get_activity_summary and get_strength_training_data,
migrating piece by piece onto the existing
metric_points.build_timestamped_point(). fetch_activity_GPS and
_build_cycling_dynamics_point (real FIT-file binary parsing) are
deliberately out of scope -- see the approved plan.

Each test is written and confirmed passing against the *current*
(pre-migration) implementation first, then must keep passing unchanged
after that piece is refactored -- except get_activity_summary's
hrTimeInZone_* fields, which are a disclosed fix (see that test's
docstring), not a preserved quirk.
"""

DATE_STR = "2026-01-15"


def test_activity_summary_exact_point_shape(garmin_fetch_module):
    """Two ActivitySummary points per activity (a rich "start" point and
    a minimal "END" marker at start + elapsedDuration), for both fixture
    activities (running, strength_training -- neither has GPS, so no FIT
    parsing is triggered here).

    hrTimeInZone_1..5 are asserted as float, not the int() the current
    code casts to -- a disclosed fix, not preserved behavior: real
    production ActivitySummary data has always stored these as float
    (confirmed via SHOW FIELD KEYS), and the int() cast (added 2026-02-19,
    over a year after that real float data was written) was proven in
    this phase's planning to cause a real InfluxDB "field type conflict"
    write failure whenever an activity already stored as float gets
    reprocessed. This test is written to already expect the fix.
    """
    points = garmin_fetch_module.get_activity_summary(DATE_STR)[0]

    # Python's == treats 120 == 120.0 as True, so the dict-equality
    # assertion below wouldn't actually catch an int/float mismatch --
    # assert the type explicitly for the fields this fix is about.
    for point in (points[0], points[2]):
        for field in ["hrTimeInZone_1", "hrTimeInZone_2", "hrTimeInZone_3", "hrTimeInZone_4", "hrTimeInZone_5"]:
            assert isinstance(point["fields"][field], float), f"{field} should be float, got {type(point['fields'][field])}"

    assert points == [
        {
            "measurement": "ActivitySummary",
            "time": "2026-01-15T06:30:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "ActivityID": 9876543210,
                "ActivitySelector": "20260115T063000UTC-running",
            },
            "fields": {
                "Activity_ID": 9876543210,
                "Device_ID": 3456789012,
                "activityName": "Morning Run",
                "description": None,
                "activityType": "running",
                "distance": 8046.7,
                "elevationGain": 45.2,
                "elevationLoss": 44.8,
                "elapsedDuration": 2415,
                "movingDuration": 2390,
                "averageSpeed": 3.33,
                "maxSpeed": 4.5,
                "calories": 520,
                "bmrCalories": 45,
                "averageHR": 148,
                "maxHR": 172,
                "vO2MaxValue": 47.0,
                "locationName": "Riverside Park",
                "lapCount": 8,
                "hrTimeInZone_1": 120.0,
                "hrTimeInZone_2": 900.0,
                "hrTimeInZone_3": 1100.0,
                "hrTimeInZone_4": 280.0,
                "hrTimeInZone_5": 15.0,
                "hrZoneLowBoundary_1": 95,
                "hrZoneLowBoundary_2": 130,
                "hrZoneLowBoundary_3": 150,
                "hrZoneLowBoundary_4": 165,
                "hrZoneLowBoundary_5": 178,
                "aerobicTrainingEffect": 3.2,
                "anaerobicTrainingEffect": 0.8,
                "activityTrainingLoad": 145.0,
                "moderateIntensityMinutes": 30,
                "vigorousIntensityMinutes": 5,
            },
        },
        {
            "measurement": "ActivitySummary",
            "time": "2026-01-15T07:10:15+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "ActivityID": 9876543210,
                "ActivitySelector": "20260115T063000UTC-running",
            },
            "fields": {
                "Activity_ID": 9876543210,
                "Device_ID": 3456789012,
                "activityName": "END",
                "activityType": "No Activity",
            },
        },
        {
            "measurement": "ActivitySummary",
            "time": "2026-01-15T18:00:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "ActivityID": 9876543211,
                "ActivitySelector": "20260115T180000UTC-strength_training",
            },
            "fields": {
                "Activity_ID": 9876543211,
                "Device_ID": 3456789012,
                "activityName": "Evening Strength Session",
                "description": None,
                "activityType": "strength_training",
                "distance": 0.0,
                "elevationGain": 0.0,
                "elevationLoss": 0.0,
                "elapsedDuration": 3000,
                "movingDuration": 2200,
                "averageSpeed": 0.0,
                "maxSpeed": 0.0,
                "calories": 310,
                "bmrCalories": 60,
                "averageHR": 118,
                "maxHR": 156,
                "vO2MaxValue": None,
                "locationName": None,
                "lapCount": 1,
                "hrTimeInZone_1": 900.0,
                "hrTimeInZone_2": 1400.0,
                "hrTimeInZone_3": 600.0,
                "hrTimeInZone_4": 90.0,
                "hrTimeInZone_5": 0.0,
                "hrZoneLowBoundary_1": 95,
                "hrZoneLowBoundary_2": 130,
                "hrZoneLowBoundary_3": 150,
                "hrZoneLowBoundary_4": 165,
                "hrZoneLowBoundary_5": 178,
                "aerobicTrainingEffect": 1.8,
                "anaerobicTrainingEffect": 2.1,
                "activityTrainingLoad": 62.0,
                "moderateIntensityMinutes": 40,
                "vigorousIntensityMinutes": 8,
            },
        },
        {
            "measurement": "ActivitySummary",
            "time": "2026-01-15T18:50:00+00:00",
            "tags": {
                "Device": "TestDevice",
                "Database_Name": "SmokeTestDB",
                "ActivityID": 9876543211,
                "ActivitySelector": "20260115T180000UTC-strength_training",
            },
            "fields": {
                "Activity_ID": 9876543211,
                "Device_ID": 3456789012,
                "activityName": "END",
                "activityType": "No Activity",
            },
        },
    ]
