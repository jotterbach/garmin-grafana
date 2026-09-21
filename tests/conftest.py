"""
Shared pytest fixtures for the garmin-grafana smoke-test suite.

Critical ordering note: garmin_fetch.py opens a real InfluxDB connection and
writes a demo point as a *side effect of being imported* (see
src/garmin_grafana/garmin_fetch.py, the module-level try/except right after
the ENV var parsing block). That means the test database must exist, and the
right env vars must be set, *before* anything imports garmin_fetch --
including test collection itself. This file runs before any test module in
this directory is collected, so all of that setup happens here at module
level, not inside a fixture function.

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

import json
import os
import sys
import time
from pathlib import Path

import pytest
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent
SRC_PACKAGE_DIR = REPO_ROOT / "src" / "garmin_grafana"

sys.path.insert(0, str(SRC_PACKAGE_DIR))

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


@pytest.fixture
def fake_garmin():
    return FakeGarmin()


@pytest.fixture
def garmin_fetch_module():
    """
    Imports garmin_fetch (triggering its import-time InfluxDB connection
    against the isolated test database set up above) and injects fake_garmin
    as garmin_fetch.garmin_obj, matching the existing project convention in
    fit_activity_importer.py of assigning garmin_fetch.garmin_obj directly.

    Bare import (not `from garmin_grafana import garmin_fetch`) -- see this
    file's module docstring for why that matters here.
    """
    import garmin_fetch

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
