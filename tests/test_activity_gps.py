"""
Characterization tests for fetch_activity_GPS's FIT-parsing path, using
real FIT files from the same corpus fit_decoder's tests use (see
tests/conftest.py's FIT_CORPUS_DIR / real_fit_paths(), and issue #26 /
the garmin_grafana_phase7_fit_plan memory for why: real personal health
data, never committed, so every test here skips cleanly when the corpus
is absent -- local-only characterization, not a CI gate).

Written and confirmed passing against the *current* fitparse-based
implementation first, then must keep passing unchanged after the
fitparse -> garmin-fit-sdk migration -- including
test_grade_adjusted_speed_uses_the_post_migration_field_key, which is
true of *correct* behavior on both sides of the migration (fitparse's
"unknown_140" and garmin-fit-sdk's int key 140 both resolve to the same
real field), but exists specifically to catch the mistake of migrating
fetch_activity_GPS's decode call without also updating that one field
lookup -- see fit_decoder.py's module docstring for how the key
difference was confirmed against real data.

Assertions describe shape, type and count, not literal field values --
which real activity ends up in the corpus, and exactly what it contains,
isn't something this test should hardcode; the corpus also grows over
time as the backfill continues.

_build_cycling_dynamics_point itself (pure function, hand-built-dict edge
cases like the left_right_balance bitmask branches) is deliberately out
of scope here -- it doesn't touch FIT parsing directly and needs no real
fixture; see the plan for that as a separate, still-open piece of work.
"""

import pytest

from conftest import RealFitGarmin, real_fit_paths


def _find(name_substring):
    for path in real_fit_paths():
        if name_substring in path.name:
            return path
    return None


@pytest.fixture
def running_file():
    path = _find("-running.fit")
    if path is None:
        pytest.skip("no real running FIT file found in the corpus yet")
    return path


@pytest.fixture
def lap_swimming_file():
    path = _find("-lap_swimming.fit")
    if path is None:
        pytest.skip("no real lap-swimming FIT file found in the corpus yet")
    return path


def _fetch(garmin_fetch_module, fit_path, activity_id, activity_type):
    garmin_fetch_module.garmin_obj = RealFitGarmin(fit_path)
    return garmin_fetch_module.fetch_activity_GPS({activity_id: activity_type})


def _by_measurement(points, measurement):
    return [p for p in points if p["measurement"] == measurement]


def test_running_file_produces_expected_measurement_shapes(garmin_fetch_module, running_file):
    points = _fetch(garmin_fetch_module, running_file, 900001, "running")

    gps_points = _by_measurement(points, "ActivityGPS")
    session_points = _by_measurement(points, "ActivitySession")
    lap_points = _by_measurement(points, "ActivityLap")
    length_points = _by_measurement(points, "ActivityLength")

    assert gps_points, "expected at least one ActivityGPS point"
    assert len(session_points) == 1
    assert not length_points, "a running activity shouldn't produce ActivityLength points"

    for p in points:
        assert set(p.keys()) == {"measurement", "time", "tags", "fields"}
        assert isinstance(p["time"], str)
        assert p["tags"].keys() >= {
            "Device",
            "Database_Name",
            "ActivityID",
            "ActivitySelector",
        }
        assert p["tags"]["ActivityID"] == 900001

    for p in gps_points:
        f = p["fields"]
        assert f["ActivityName"] == "running"
        assert f["Activity_ID"] == 900001
        for key in ("Latitude", "Longitude"):
            assert f[key] is None or isinstance(f[key], float)
            if f[key] is not None:
                assert -180.0 <= f[key] <= 180.0
        assert isinstance(f["DurationSeconds"], float)
        assert f["DurationSeconds"] >= 0.0
        if f["HeartRate"] is not None:
            assert isinstance(f["HeartRate"], float)

    for p in lap_points:
        assert isinstance(p["fields"]["Index"], int)
        assert p["fields"]["Index"] >= 1


def test_grade_adjusted_speed_uses_the_post_migration_field_key(garmin_fetch_module, running_file):
    """
    Confirmed via fit_decoder's real-corpus tests that this specific
    running file's record_mesgs carry field def_num 140 on every record
    under fitparse's name "unknown_140". Post-migration, fetch_activity_GPS
    must look this field up the way garmin-fit-sdk exposes it -- if the
    lookup key isn't updated as part of the migration, GradeAdjustedSpeed
    silently goes from populated to always-None instead of raising, so
    this needs an explicit assertion, not just "no exception".
    """
    points = _fetch(garmin_fetch_module, running_file, 900002, "running")
    gps_points = _by_measurement(points, "ActivityGPS")

    non_none = [p["fields"]["GradeAdjustedSpeed"] for p in gps_points if p["fields"]["GradeAdjustedSpeed"] is not None]
    assert non_none, (
        "expected at least one GradeAdjustedSpeed value from this real "
        "running file (known to populate this field on every record) -- "
        "got none, field lookup key is likely still pointing at the old "
        "fitparse-style name"
    )
    for v in non_none:
        assert isinstance(v, float)


def test_lap_swimming_file_produces_length_points(garmin_fetch_module, lap_swimming_file):
    points = _fetch(garmin_fetch_module, lap_swimming_file, 900003, "lap_swimming")

    length_points = _by_measurement(points, "ActivityLength")
    assert length_points, "expected ActivityLength points from a lap-swimming file"

    for p in length_points:
        assert p["tags"]["ActivityID"] == 900003
        assert isinstance(p["fields"]["Index"], int)
        assert p["fields"]["Index"] >= 1


def test_activity_gps_timestamps_are_non_decreasing_within_an_activity(garmin_fetch_module, running_file):
    points = _fetch(garmin_fetch_module, running_file, 900004, "running")
    gps_points = _by_measurement(points, "ActivityGPS")

    times = [p["time"] for p in gps_points]
    assert times == sorted(times)
