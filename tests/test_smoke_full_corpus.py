"""
Full-corpus integration smoke test for the fitparse -> garmin-fit-sdk
migration (issue #26 / PR #28): feeds every real FIT file conftest's
real_fit_paths() returns through the actual fetch_activity_GPS pipeline,
simulating a real activity-sync data flow end to end -- without ever
calling write_points_to_influxdb, so nothing is persisted anywhere. This
started as a one-off dry-run script; promoted to a real (opt-in) test so
it keeps getting run instead of bit-rotting.

Same real-data-availability caveat as the rest of the real-FIT test
modules (test_fit_decoder.py, test_activity_gps.py, ...): this corpus is
real personal health data, never committed, so it won't exist in CI --
this test skips cleanly when it's absent.

By default real_fit_paths() returns a random sample (see conftest.py's
FIT_CORPUS_SAMPLE_SIZE), not the whole corpus -- it grew well past its
original ~143 files and iterating all of it on every local run got slow
enough to discourage running this test while debugging. Set
FIT_TEST_CORPUS_SAMPLE_SIZE=all to actually exercise every file in one
pass -- do that before merging a change to the FIT-parsing path, not on
every iteration.

Assertions are aggregate/structural, matching the rest of this test
family's "patterns and structure, not exact values" rule: total points
scale with corpus size (which grows over time), so nothing here hardcodes
a specific count.
"""

import logging

import pytest

from conftest import RealFitGarmin, real_fit_paths


def _activity_type_from_filename(path):
    # KEEP_FIT_FILES naming convention: <timestamp>UTC-<activity_type>.fit
    return path.stem.split("UTC-", 1)[-1]


def test_full_corpus_dry_run_no_errors_and_nothing_persisted(garmin_fetch_module, caplog):
    paths = real_fit_paths()
    if not paths:
        pytest.skip("no real FIT corpus found locally -- integration smoke test, not a CI gate")

    original_fetch_selection = garmin_fetch_module.FETCH_SELECTION
    original_garmin_obj = garmin_fetch_module.garmin_obj

    measurement_counts = {}
    session_counts_by_file = {}  # path.name -> ActivitySession points from that file alone
    errors = []

    # Random sampling (conftest.py's FIT_CORPUS_SAMPLE_SIZE) means the set
    # under test drifts between runs -- log it up front so a failure (or a
    # later report of one) can be tied back to exactly which files were
    # exercised, not just an aggregate count. pytest shows captured INFO
    # logs in the failure report by default, no extra flags needed.
    with caplog.at_level(logging.INFO):
        logging.info("Testing %d real FIT file(s): %s", len(paths), [p.name for p in paths])

        try:
            garmin_fetch_module.FETCH_SELECTION = "activity,cycling_dynamics"

            for i, path in enumerate(paths, start=1):
                activity_type = _activity_type_from_filename(path)
                activity_id = 9_000_000 + i  # unique per file, never a real ID

                garmin_fetch_module.garmin_obj = RealFitGarmin(path)
                try:
                    points = garmin_fetch_module.fetch_activity_GPS({activity_id: activity_type})
                except Exception as e:  # noqa: BLE001 -- collecting, not swallowing
                    logging.info("[%d/%d] %s -> raised %r", i, len(paths), path.name, e)
                    errors.append((path.name, repr(e)))
                    continue

                file_session_count = 0
                for p in points:
                    measurement_counts[p["measurement"]] = measurement_counts.get(p["measurement"], 0) + 1
                    if p["measurement"] == "ActivitySession":
                        file_session_count += 1
                session_counts_by_file[path.name] = file_session_count
                logging.info(
                    "[%d/%d] %s -> %d point(s), %d ActivitySession",
                    i,
                    len(paths),
                    path.name,
                    len(points),
                    file_session_count,
                )
                # Never call write_points_to_influxdb -- this is the whole
                # point of a dry run: exercise real parsing/point-building,
                # persist nothing.
        finally:
            # garmin_fetch is imported once and reused across the whole test
            # session -- leaving FETCH_SELECTION/garmin_obj mutated here
            # would silently break later tests that assume the defaults
            # (confirmed: this broke test_smoke_pipeline.py's
            # test_daily_fetch_write_end_to_end before this restore was
            # added).
            garmin_fetch_module.FETCH_SELECTION = original_fetch_selection
            garmin_fetch_module.garmin_obj = original_garmin_obj

    assert not errors, f"fetch_activity_GPS raised on {len(errors)} real file(s): {errors}"

    # ActivitySession is exactly one point per file in every real file seen
    # so far (confirmed via test_fit_decoder's corpus-wide characterization
    # too) -- the one count this test treats as a hard invariant rather
    # than just "greater than zero". Named per file, not just totalled, so
    # a failure points straight at the offending file(s) instead of just a
    # mismatched aggregate.
    offenders = {name: count for name, count in session_counts_by_file.items() if count != 1}
    assert not offenders, f"expected exactly 1 ActivitySession point per file, got: {offenders}"
    assert measurement_counts.get("ActivityGPS", 0) > 0

    # Nothing should have reached the (test) database -- confirm the dry
    # run didn't accidentally write anything, not just that we didn't
    # intend to.
    storage = garmin_fetch_module.INFLUXDB_STORAGE
    for measurement in measurement_counts:
        result = storage.query(f'SELECT * FROM "{measurement}"')
        assert not result, f"expected zero persisted {measurement} points from a dry run, found some"
