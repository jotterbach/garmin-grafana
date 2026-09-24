"""
Direct tests for influx_storage.py's InfluxStorage wrapper, against the same
disposable test InfluxDB instance conftest.py sets up (env vars are already
set globally there, so Config.from_env() here picks up the same test
target automatically).
"""

from datetime import datetime, timezone

import pytest
import requests

from config import Config
from influx_storage import InfluxStorage


@pytest.fixture
def storage():
    s = InfluxStorage(Config.from_env())
    s.check_connection()
    return s


def test_write_and_query_round_trip(storage):
    point = {
        "measurement": "InfluxStorageRoundTrip",
        "time": datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat(),
        "tags": {"Device": "TestDevice"},
        "fields": {"value": 7},
    }
    storage.write_points([point])

    rows = storage.query('SELECT * FROM "InfluxStorageRoundTrip"')
    assert len(rows) == 1
    assert rows[0]["value"] == 7


def test_query_returns_plain_list_not_a_client_specific_result_object(storage):
    point = {
        "measurement": "InfluxStorageShapeCheck",
        "time": datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat(),
        "tags": {"Device": "TestDevice"},
        "fields": {"value": 1},
    }
    storage.write_points([point])

    rows = storage.query('SELECT * FROM "InfluxStorageShapeCheck"')
    assert isinstance(rows, list)
    assert isinstance(rows[0], dict)


def test_delete_series_removes_matching_points(storage):
    point = {
        "measurement": "InfluxStorageDeleteMe",
        "time": datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat(),
        "tags": {"ActivityID": "12345"},
        "fields": {"value": 1},
    }
    storage.write_points([point])
    assert storage.query('SELECT * FROM "InfluxStorageDeleteMe"')

    storage.delete_series(measurement="InfluxStorageDeleteMe", tags={"ActivityID": "12345"})

    assert storage.query('SELECT * FROM "InfluxStorageDeleteMe"') == []


def test_delete_series_raises_not_implemented_on_v3():
    # No real v3 server needed -- delete_series short-circuits on the
    # version check before ever touching the underlying client.
    v3_storage = InfluxStorage(Config.from_env({"INFLUXDB_VERSION": "3"}))
    with pytest.raises(NotImplementedError):
        v3_storage.delete_series(measurement="Whatever", tags={"ActivityID": "1"})


def test_check_connection_succeeds_against_reachable_instance(storage):
    storage.check_connection()  # should not raise


def test_check_connection_propagates_when_unreachable():
    # check_connection() only catches/wraps (InfluxDBClientError,
    # InfluxDBError) -- same as the original import-time code did. A raw
    # TCP-level refusal surfaces unwrapped as requests.exceptions.
    # ConnectionError, not InfluxDBClientError; this test documents that
    # real (pre-existing) behavior rather than assuming a nicer exception
    # type that was never actually guaranteed.
    unreachable = InfluxStorage(Config.from_env({"INFLUXDB_HOST": "127.0.0.1", "INFLUXDB_PORT": "1"}))
    with pytest.raises(requests.exceptions.ConnectionError):
        unreachable.check_connection()
