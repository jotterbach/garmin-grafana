"""
Characterization test for GarminBulkExport.load_fit_file_index -- the
last of issue #26's three fitparse call sites (see the
garmin_grafana_phase7_fit_plan memory). Lower-stakes than the other two:
this only extracts session.start_time/session.sport for cataloging a
local bulk-export archive (confirmed via grep -- no "measurement" key
anywhere in this file, so a mismatch here affects file ordering, not
stored InfluxDB data).

GarminBulkExport's normal constructor needs a full bulk-export directory
layout (activities, sleep stats, agg stats, ...) -- building that just to
exercise this one FIT-indexing method would be disproportionate, so this
test bypasses __init__ and sets only the two attributes
load_fit_file_index actually reads (all_files, cached_fit_file_index).

Uses a real FIT file from the shared corpus (tests/conftest.py's
real_fit_paths()); skips cleanly when the corpus is absent.
"""

import zipfile
from datetime import datetime, timezone

import pytest

from conftest import real_fit_paths
from garmin_bulk_importer import GarminBulkExport


@pytest.fixture
def running_file():
    for path in real_fit_paths():
        if "-running.fit" in path.name:
            return path
    pytest.skip("no real running FIT file found in the corpus yet")


def _bulk_export_zip(tmp_path, fit_path):
    zip_path = tmp_path / "DI-Connect-Uploaded-Files-1.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(fit_path, arcname=fit_path.name)
    return zip_path


def test_load_fit_file_index_catalogs_a_real_fit_file(tmp_path, running_file):
    zip_path = _bulk_export_zip(tmp_path, running_file)

    export = object.__new__(GarminBulkExport)
    export.all_files = [zip_path]
    export.cached_fit_file_index = tmp_path / "fit_file_index_cache.json"

    index = export.load_fit_file_index()

    assert len(index) == 1
    entry = index[0]
    assert entry.activity == "running"
    assert isinstance(entry.date, datetime)
    assert entry.date.tzinfo == timezone.utc
    assert entry.zip_file_name == zip_path
    assert entry.fit_file_name == running_file.name

    assert export.cached_fit_file_index.exists()
