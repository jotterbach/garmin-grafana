"""
Shared pytest fixtures for the garmin-grafana smoke-test suite.

Critical ordering note: even though garmin_fetch.py no longer connects to
InfluxDB as an import-time side effect (see influx_storage.py --
connectivity is now verified explicitly, either by __main__ in production or
by the garmin_fetch_module fixture below in tests), the right env vars still
need to be set *before* anything imports garmin_fetch or config -- including
test collection itself, since Config.from_env() runs at garmin_fetch's
import time regardless. This file runs before any test module in this
directory is collected, so all of that setup happens here at module level,
not inside a fixture function. The test database is also created here
upfront, before collection, so it's ready the moment any test's explicit
check_connection() call needs it.

Import mode: garmin_fetch.py is run in production as a raw script
(Dockerfile: `python garmin_grafana/garmin_fetch.py`), which puts its own
directory on sys.path[0] -- garmin_fetch.py's sibling imports (e.g. `from
config import Config`) rely on that, matching the same bare-import
convention the other sibling scripts already use (fit_activity_importer.py:
`import garmin_fetch`). So tests add src/garmin_grafana itself to sys.path
and use bare `import garmin_fetch` / `import config` too, rather than
package-qualified imports -- exercising the same import mode production
actually uses, not a more lenient one that would hide an import bug like
this until it broke in the real container.

Deliberately isolated from the real deployment: distinct host/port/database
name from the project's own compose.yml defaults, so this can never be
accidentally pointed at real ingested health data.
"""

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent
SRC_PACKAGE_DIR = REPO_ROOT / "src" / "garmin_grafana"

sys.path.insert(0, str(SRC_PACKAGE_DIR))

# Real FIT files pulled from production via KEEP_FIT_FILES (see issue #26 /
# the garmin_grafana_phase7_fit_plan memory) -- never committed (real
# personal health data), so this directory won't exist in CI. Shared by
# every test module that characterizes real-FIT-file parsing; each such
# test skips cleanly when the corpus is absent.
FIT_CORPUS_DIR = Path(
    os.environ.get("FIT_TEST_CORPUS_DIR", "/ext/garmin-grafana/fit_filestore")
)


def real_fit_paths():
    if not FIT_CORPUS_DIR.is_dir():
        return []
    return sorted(FIT_CORPUS_DIR.glob("*.fit"))


class RealFitGarmin:
    """
    Minimal stand-in for garminconnect.Garmin wrapping one real local FIT
    file, matching the existing MockGarminObject pattern in
    fit_activity_importer.py: download_activity() zips the file in-memory
    the same shape the real ORIGINAL-format download returns. Shared by
    every test module that drives fetch_activity_GPS against a real file.
    """

    class ActivityDownloadFormat:
        ORIGINAL = "original"
        TCX = "tcx"

    def __init__(self, fit_path: Path):
        self._fit_path = fit_path

    def download_activity(self, activity_id, dl_fmt=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w") as zf:
            zf.write(self._fit_path, arcname=self._fit_path.name)
        return buf.getvalue()

TEST_INFLUXDB_HOST = os.environ.get("TEST_INFLUXDB_HOST", "127.0.0.1")
TEST_INFLUXDB_PORT = int(os.environ.get("TEST_INFLUXDB_PORT", "18086"))
TEST_INFLUXDB_DATABASE = "SmokeTestDB"

os.environ["INFLUXDB_HOST"] = TEST_INFLUXDB_HOST
os.environ["INFLUXDB_PORT"] = str(TEST_INFLUXDB_PORT)
os.environ["INFLUXDB_DATABASE"] = TEST_INFLUXDB_DATABASE
os.environ["INFLUXDB_USERNAME"] = "root"
os.environ["INFLUXDB_PASSWORD"] = "root"
os.environ["INFLUXDB_ENDPOINT_IS_HTTP"] = "True"
os.environ.setdefault("GARMIN_DEVICENAME", "TestDevice")
os.environ.setdefault("GARMIN_DEVICEID", "1234567890")
os.environ.setdefault("TOKEN_DIR", "/tmp/garmin-grafana-test-tokens-unused")

# Make sure the test database exists before garmin_fetch's module-level
# import-time write can run. Retries because in CI the influxdb service
# container may not have finished starting the instant pytest does.
_admin_client = InfluxDBClient(
    host=TEST_INFLUXDB_HOST, port=TEST_INFLUXDB_PORT, username="root", password="root"
)
_deadline = time.time() + 30
while True:
    try:
        _admin_client.create_database(TEST_INFLUXDB_DATABASE)
        break
    except (InfluxDBClientError, ConnectionError, OSError):
        if time.time() > _deadline:
            raise
        time.sleep(1)


def _load_fixture(name: str):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class FakeGarmin:
    """
    Stands in for garminconnect.Garmin. Extends the same idea already used
    by src/garmin_grafana/fit_activity_importer.py's MockGarminObject, but
    covers the methods needed by garmin_fetch.py's default FETCH_SELECTION.

    Every canned response here is built from real Garmin API shapes verified
    live against an authenticated account during development of this suite
    (see the raw field lists checked for weigh-ins, activities, sleep, and
    stress) -- not guessed structures.
    """

    display_name = "test_user"

    def __init__(self):
        self._weigh_ins = _load_fixture("weigh_ins.json")
        self._activities = _load_fixture("activities.json")
        self._sleep = _load_fixture("sleep.json")
        self._daily = _load_fixture("daily_metrics.json")
        self._device_sync = _load_fixture("device_sync.json")
        self._exercise_sets = _load_fixture("exercise_sets.json")

    def get_stats(self, date_str):
        return self._daily["daily_stats"]

    def get_sleep_data(self, date_str):
        return self._sleep

    def get_steps_data(self, date_str):
        return self._daily["steps"]

    def get_heart_rates(self, date_str):
        return self._daily["heart_rates"]

    def get_stress_data(self, date_str):
        return self._daily["stress"]

    def get_respiration_data(self, date_str):
        return self._daily["respiration"]

    def get_hrv_data(self, date_str):
        return self._daily["hrv"]

    def get_fitnessage_data(self, date_str):
        return self._daily["fitness_age"]

    def get_max_metrics(self, date_str):
        return self._daily["max_metrics"]

    def get_activities_by_date(self, start_date, end_date):
        return self._activities

    def get_activity_hr_in_timezones(self, activity_id):
        return self._daily["hr_zones"]

    def get_race_predictions(self, startdate, enddate, _type):
        return self._daily["race_predictions"]

    def get_weigh_ins(self, start_date, end_date):
        return self._weigh_ins

    def get_lifestyle_logging_data(self, date_str):
        return self._daily["lifestyle"]

    def get_hill_score(self, date_str):
        return self._daily["hill_score"]

    def get_endurance_score(self, date_str):
        return self._daily["endurance_score"]

    def get_hydration_data(self, date_str):
        return self._daily["hydration"]

    def get_training_readiness(self, date_str):
        return self._daily["training_readiness"]

    def get_blood_pressure(self, start_date, end_date):
        return self._daily["blood_pressure"]

    def get_training_status(self, date_str):
        return self._daily["training_status"]

    def get_device_solar_data(self, device_id, date_str):
        return self._daily["solar_intensity"]

    def connectapi(self, endpoint, method="GET"):
        return [self._daily["lactate_threshold_value"]]

    def get_device_last_used(self):
        return self._device_sync

    def get_activity_exercise_sets(self, activity_id):
        return self._exercise_sets


@pytest.fixture
def fake_garmin():
    return FakeGarmin()


@pytest.fixture
def garmin_fetch_module():
    """
    Imports garmin_fetch and injects fake_garmin as garmin_fetch.garmin_obj,
    matching the existing project convention in fit_activity_importer.py of
    assigning garmin_fetch.garmin_obj directly.

    Bare import (not `from garmin_grafana import garmin_fetch`) -- see this
    file's module docstring for why that matters here.

    Since garmin_fetch.py no longer verifies InfluxDB connectivity at import
    time (that moved to an explicit INFLUXDB_STORAGE.check_connection() call
    in __main__ -- see influx_storage.py), this fixture calls it explicitly
    here instead, preserving the same guarantee tests relied on before: if
    this fixture succeeds, the test database is definitely reachable.
    """
    import garmin_fetch

    garmin_fetch.INFLUXDB_STORAGE.check_connection()
    garmin_fetch.garmin_obj = FakeGarmin()
    return garmin_fetch


@pytest.fixture(autouse=True)
def clean_influxdb():
    """Wipe all series before each test so tests can't see each other's data."""
    client = InfluxDBClient(
        host=TEST_INFLUXDB_HOST,
        port=TEST_INFLUXDB_PORT,
        username="root",
        password="root",
        database=TEST_INFLUXDB_DATABASE,
    )
    try:
        client.query("DROP SERIES FROM /.*/")
    except InfluxDBClientError:
        pass
    yield
    try:
        client.query("DROP SERIES FROM /.*/")
    except InfluxDBClientError:
        pass
