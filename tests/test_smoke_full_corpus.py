"""
Full-corpus integration smoke test for the fitparse -> garmin-fit-sdk
migration (issue #26 / PR #28): feeds every real FIT file in the local
KEEP_FIT_FILES corpus through the actual fetch_activity_GPS pipeline,
simulating a real activity-sync data flow end to end -- without ever
calling write_points_to_influxdb, so nothing is persisted anywhere. This
started as a one-off dry-run script; promoted to a real (opt-in) test so
it keeps getting run instead of bit-rotting.

Same real-data-availability caveat as the rest of the real-FIT test
modules (test_fit_decoder.py, test_activity_gps.py, ...): this corpus is
real personal health data, never committed, so it won't exist in CI --
this test skips cleanly when it's absent. It's also the slowest test in
the suite when the corpus *is* present (the full 143-file corpus took
~2 minutes locally), so it earns its keep by being the one test that
exercises literally the whole corpus in one pass rather than a couple of
representative files -- worth the time only when actually validating a
change to the FIT-parsing path.

Assertions are aggregate/structural, matching the rest of this test
family's "patterns and structure, not exact values" rule: total points
scale with corpus size (which grows over time), so nothing here hardcodes
a specific count.
"""

import pytest

from conftest import RealFitGarmin, real_fit_paths


def _activity_type_from_filename(path):
    # KEEP_FIT_FILES naming convention: <timestamp>UTC-<activity_type>.fit
    return path.stem.split("UTC-", 1)[-1]


def test_full_corpus_dry_run_no_errors_and_nothing_persisted(garmin_fetch_module):
    paths = real_fit_paths()
    if not paths:
        pytest.skip(
            "no real FIT corpus found locally -- integration smoke test, not a CI gate"
        )

    original_fetch_selection = garmin_fetch_module.FETCH_SELECTION
    original_garmin_obj = garmin_fetch_module.garmin_obj

    measurement_counts = {}
    errors = []

    try:
        garmin_fetch_module.FETCH_SELECTION = "activity,cycling_dynamics"

        for i, path in enumerate(paths, start=1):
            activity_type = _activity_type_from_filename(path)
            activity_id = 9_000_000 + i  # unique per file, never a real ID

            garmin_fetch_module.garmin_obj = RealFitGarmin(path)
            try:
                points = garmin_fetch_module.fetch_activity_GPS({activity_id: activity_type})
            except Exception as e:  # noqa: BLE001 -- collecting, not swallowing
                errors.append((path.name, repr(e)))
                continue

            for p in points:
                measurement_counts[p["measurement"]] = (
                    measurement_counts.get(p["measurement"], 0) + 1
                )
            # Never call write_points_to_influxdb -- this is the whole point
            # of a dry run: exercise real parsing/point-building, persist
            # nothing.
    finally:
        # garmin_fetch is imported once and reused across the whole test
        # session -- leaving FETCH_SELECTION/garmin_obj mutated here would
        # silently break later tests that assume the defaults (confirmed:
        # this broke test_smoke_pipeline.py's
        # test_daily_fetch_write_end_to_end before this restore was added).
        garmin_fetch_module.FETCH_SELECTION = original_fetch_selection
        garmin_fetch_module.garmin_obj = original_garmin_obj

    assert not errors, f"fetch_activity_GPS raised on {len(errors)} real file(s): {errors}"

    # ActivitySession is exactly one point per file in every real file seen
    # so far (confirmed via test_fit_decoder's corpus-wide characterization
    # too) -- the one count this test treats as a hard invariant rather
    # than just "greater than zero".
    assert measurement_counts.get("ActivitySession", 0) == len(paths)
    assert measurement_counts.get("ActivityGPS", 0) > 0

    # Nothing should have reached the (test) database -- confirm the dry
    # run didn't accidentally write anything, not just that we didn't
    # intend to.
    storage = garmin_fetch_module.INFLUXDB_STORAGE
    for measurement in measurement_counts:
        result = storage.query(f'SELECT * FROM "{measurement}"')
        assert not result, (
            f"expected zero persisted {measurement} points from a dry run, found some"
        )
