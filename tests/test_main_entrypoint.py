"""
Tests for #17 phase C: garmin_fetch.py's __main__ block, extracted into
main() plus three testable helpers (_determine_initial_sync_time,
_determine_local_timediff, _maybe_sync_once). Before this phase, none of
this was callable by pytest at all -- gated behind
`if __name__ == "__main__":` -- so unlike phases A/B there's no "confirm
against the current implementation first" step possible; the extraction
itself (a careful, faithful transcription -- see the PR/commit for the
diff) is what phase C's plan anticipated as the only viable order here.

main()'s own `while True:` polling loop is inherently untestable to
completion by design -- tests confirm one iteration's wiring is correct
by monkeypatching _maybe_sync_once to raise a sentinel exception after
being called once, matching the "the loop itself doesn't need testing
once everything it calls is tested" framing from the issue.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytz
from influxdb.exceptions import InfluxDBClientError

from garmin_fetch import (
    _determine_initial_sync_time,
    _determine_local_timediff,
    _maybe_sync_once,
    main,
)


# --- _determine_initial_sync_time ---


def test_determine_initial_sync_time_returns_last_written_point(garmin_fetch_module):
    storage = garmin_fetch_module.INFLUXDB_STORAGE
    point_time = datetime(2026, 3, 1, 12, 30, 0, tzinfo=timezone.utc)
    storage.write_points(
        [
            {
                "measurement": "HeartRateIntraday",
                "time": point_time.isoformat(),
                "tags": {"Device": "TestDevice"},
                "fields": {"value": 60},
            }
        ]
    )

    result = _determine_initial_sync_time(storage)

    assert result == pytz.utc.localize(point_time.replace(tzinfo=None))


def test_determine_initial_sync_time_falls_back_to_seven_days_ago_when_empty(
    garmin_fetch_module,
):
    storage = garmin_fetch_module.INFLUXDB_STORAGE  # clean_influxdb wiped it

    result = _determine_initial_sync_time(storage)

    expected = (datetime.today() - timedelta(days=7)).astimezone(pytz.timezone("UTC"))
    assert abs((result - expected).total_seconds()) < 5


# --- _determine_local_timediff ---


def test_determine_local_timediff_uses_user_timezone_override(
    garmin_fetch_module, monkeypatch
):
    monkeypatch.setattr(garmin_fetch_module, "USER_TIMEZONE", "Europe/Berlin")

    result = _determine_local_timediff()

    expected = datetime.now(tz=pytz.timezone("Europe/Berlin")).utcoffset()
    assert result == expected


def test_determine_local_timediff_auto_detects_from_last_activity(
    garmin_fetch_module, monkeypatch
):
    monkeypatch.setattr(garmin_fetch_module, "USER_TIMEZONE", "")
    garmin_fetch_module.garmin_obj.get_last_activity = lambda: {
        "startTimeLocal": "2026-03-01 14:30:00",
        "startTimeGMT": "2026-03-01 12:30:00",
    }

    result = _determine_local_timediff()

    assert result == timedelta(hours=2)


def test_determine_local_timediff_falls_back_to_utc_on_missing_data(
    garmin_fetch_module, monkeypatch
):
    monkeypatch.setattr(garmin_fetch_module, "USER_TIMEZONE", "")
    garmin_fetch_module.garmin_obj.get_last_activity = lambda: {}  # KeyError

    result = _determine_local_timediff()

    assert result == timedelta(0)


# --- _maybe_sync_once ---


def test_maybe_sync_once_fetches_when_watch_is_newer(garmin_fetch_module, monkeypatch):
    calls = []
    monkeypatch.setattr(
        garmin_fetch_module,
        "fetch_write_bulk",
        lambda start, end: calls.append((start, end)),
    )
    # fixtures/device_sync.json: lastUsedDeviceUploadTime = 1768460400000 (ms)
    watch_time_utc = datetime.fromtimestamp(1768460400000 / 1000, tz=timezone.utc)
    older = watch_time_utc - timedelta(days=1)

    result = _maybe_sync_once(older, timedelta(0))

    assert result == watch_time_utc
    assert len(calls) == 1
    assert calls[0] == (older.strftime("%Y-%m-%d"), watch_time_utc.strftime("%Y-%m-%d"))


def test_maybe_sync_once_does_nothing_when_influxdb_already_current(
    garmin_fetch_module, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        garmin_fetch_module,
        "fetch_write_bulk",
        lambda start, end: calls.append((start, end)),
    )
    watch_time_utc = datetime.fromtimestamp(1768460400000 / 1000, tz=timezone.utc)
    newer = watch_time_utc + timedelta(days=1)

    result = _maybe_sync_once(newer, timedelta(0))

    assert result == newer
    assert calls == []


# --- main() ---


def test_main_raises_and_never_logs_in_when_influxdb_unreachable(
    garmin_fetch_module, monkeypatch
):
    def _fail():
        raise InfluxDBClientError("down")

    monkeypatch.setattr(
        garmin_fetch_module.INFLUXDB_STORAGE, "check_connection", _fail
    )
    login_calls = []
    monkeypatch.setattr(
        garmin_fetch_module,
        "garmin_login",
        lambda config: login_calls.append(config),
    )

    with pytest.raises(InfluxDBClientError):
        main()

    assert login_calls == []


def test_main_manual_start_date_runs_once_and_returns(garmin_fetch_module, monkeypatch):
    monkeypatch.setattr(garmin_fetch_module.INFLUXDB_STORAGE, "check_connection", lambda: None)
    monkeypatch.setattr(garmin_fetch_module, "garmin_login", lambda config: garmin_fetch_module.garmin_obj)
    monkeypatch.setattr(garmin_fetch_module, "MANUAL_START_DATE", "2026-01-01")
    monkeypatch.setattr(garmin_fetch_module, "MANUAL_END_DATE", "2026-01-02")
    calls = []
    monkeypatch.setattr(
        garmin_fetch_module,
        "fetch_write_bulk",
        lambda start, end: calls.append((start, end)),
    )

    result = main()  # must not loop forever

    assert result is None
    assert calls == [("2026-01-01", "2026-01-02")]


def test_main_automatic_mode_wires_helpers_into_the_polling_loop(
    garmin_fetch_module, monkeypatch
):
    monkeypatch.setattr(garmin_fetch_module.INFLUXDB_STORAGE, "check_connection", lambda: None)
    monkeypatch.setattr(garmin_fetch_module, "garmin_login", lambda config: garmin_fetch_module.garmin_obj)
    monkeypatch.setattr(garmin_fetch_module, "MANUAL_START_DATE", None)
    monkeypatch.setattr(garmin_fetch_module, "UPDATE_INTERVAL_SECONDS", 0)

    sentinel_initial_sync = object()
    monkeypatch.setattr(
        garmin_fetch_module,
        "_determine_initial_sync_time",
        lambda storage: sentinel_initial_sync,
    )
    local_timediff_sentinel = timedelta(hours=3)
    monkeypatch.setattr(
        garmin_fetch_module, "_determine_local_timediff", lambda: local_timediff_sentinel
    )

    class _StopTheLoop(Exception):
        pass

    maybe_sync_calls = []

    def _fake_maybe_sync_once(last_sync, local_timediff):
        maybe_sync_calls.append((last_sync, local_timediff))
        raise _StopTheLoop()

    monkeypatch.setattr(garmin_fetch_module, "_maybe_sync_once", _fake_maybe_sync_once)
    monkeypatch.setattr(garmin_fetch_module.time, "sleep", lambda seconds: None)

    with pytest.raises(_StopTheLoop):
        main()

    assert maybe_sync_calls == [(sentinel_initial_sync, local_timediff_sentinel)]
