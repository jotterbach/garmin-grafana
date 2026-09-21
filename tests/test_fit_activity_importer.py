"""
Characterization tests for fit_activity_importer.get_fit_activity_summary
(the manual-import CLI's own independent FIT -> InfluxDB ontology mapping,
separate from fetch_activity_GPS -- see the garmin_grafana_phase7_fit_plan
memory / issue #26 for why this needed its own migration step). Previously
untested.

Uses a real FIT file from the same corpus fit_decoder's and
test_activity_gps.py's tests use (tests/conftest.py's real_fit_paths());
skips cleanly when the corpus is absent (real personal data, never
committed).

get_fit_activity_summary's *signature* legitimately changes as part of
this migration -- it used to take a parsed fitparse.FitFile, now takes
decode_fit()'s messages dict -- so _load_fit_input() is the one thing this
file expects to edit as part of the migration commit; every assertion
below is written to hold regardless of which library produced the input.

One exception: test_device_tag_uses_resolved_product_name characterizes a
genuine, disclosed behavior improvement from the migration (see its
docstring), following this project's established pattern for a disclosed
fix (e.g. test_metrics_activity.py's hrTimeInZone test) -- written to
expect the post-migration value, confirmed to fail against the
pre-migration code, and expected to pass once the migration lands.
"""

import pytest

from fit_activity_importer import get_fit_activity_summary
from fit_decoder import decode_fit
from conftest import real_fit_paths


def _find(name_substring):
    for path in real_fit_paths():
        if name_substring in path.name:
            return path
    return None


def _load_fit_input(path):
    return decode_fit(path.read_bytes())


@pytest.fixture
def running_file():
    path = _find("-running.fit")
    if path is None:
        pytest.skip("no real running FIT file found in the corpus yet")
    return path


def test_get_fit_activity_summary_produces_expected_point_shapes(running_file):
    activity_id, activity_type, start_point, end_point = get_fit_activity_summary(
        _load_fit_input(running_file)
    )

    assert isinstance(activity_id, int) and activity_id > 0
    assert isinstance(activity_type, str) and activity_type == "running"

    for point in (start_point, end_point):
        assert point["measurement"] == "ActivitySummary"
        assert isinstance(point["time"], str)
        tags = point["tags"]
        assert tags.keys() >= {"Device", "Database_Name", "ActivityID", "ActivitySelector"}
        assert tags["ActivityID"] == activity_id
        assert tags["Device"] is not None

    start_fields = start_point["fields"]
    assert start_fields["activityType"] == "running"
    assert "running" in start_fields["activityName"].lower()
    for key in ("distance", "elapsedDuration", "movingDuration", "averageHR", "maxHR", "lapCount"):
        assert key in start_fields

    end_fields = end_point["fields"]
    assert end_fields["activityName"] == "END"
    assert end_fields["activityType"] == "No Activity"
    assert end_fields["ActivityID"] == activity_id

    assert end_point["time"] > start_point["time"]


def test_device_tag_uses_resolved_product_name(running_file):
    """
    file_id_mesgs' "garmin_product" field is a raw numeric product code
    under fitparse's (stale) profile, e.g. 4565, but garmin-fit-sdk's
    current official profile resolves it to a real device name string,
    e.g. "fr970" -- confirmed by direct comparison against this exact
    real file. Post-migration, the Device tag on ActivitySummary points
    from this importer should carry the resolved name, not a bare numeric
    code masquerading as one.
    """
    _, _, start_point, _ = get_fit_activity_summary(_load_fit_input(running_file))

    device = start_point["tags"]["Device"]
    assert isinstance(device, str)
    assert not device.isdigit(), (
        f"expected a resolved device name string, got a raw numeric code: {device!r}"
    )
