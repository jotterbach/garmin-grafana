"""
Characterization tests for daily_fetch_write's intraday-data-refresh
polling logic (#17 phase A). Written and confirmed passing against the
current implementation before it gets extracted into its own helper
function -- must keep passing unchanged after that extraction.

REQUEST_INTRADAY_DATA_REFRESH defaults False (config.py), so none of this
runs in the existing smoke tests -- confirmed via grep across tests/
before this file was added: zero references to it, fetch_write_bulk, or
__main__'s logic anywhere.

time.sleep is mocked throughout (monkeypatch, auto-restored per test) --
the DENIED branch sleeps ~24 hours (time.sleep(86500)) for real in
production; nothing here should ever actually wait.
"""

from datetime import datetime

DATE_STR = "2020-01-15"  # always "old enough" relative to whenever tests run


def _recent_date_str():
    return datetime.today().strftime("%Y-%m-%d")


class FakeConnectapi:
    """Records calls, returns a fixed status dict for the wellness refresh endpoint."""

    def __init__(self, status):
        self.status = status
        self.calls = []

    def __call__(self, endpoint, method="GET"):
        self.calls.append((endpoint, method))
        return {"status": self.status}


def _sleep_recorder(monkeypatch, garmin_fetch_module):
    calls = []
    monkeypatch.setattr(
        garmin_fetch_module.time, "sleep", lambda seconds: calls.append(seconds)
    )
    return calls


def _set_up(garmin_fetch_module, monkeypatch, status, request_refresh=True):
    monkeypatch.setattr(
        garmin_fetch_module, "REQUEST_INTRADAY_DATA_REFRESH", request_refresh
    )
    monkeypatch.setattr(garmin_fetch_module, "FETCH_SELECTION", "hydration")
    fake_connectapi = FakeConnectapi(status)
    garmin_fetch_module.garmin_obj.connectapi = fake_connectapi
    return fake_connectapi


def test_refresh_logic_skipped_when_feature_flag_off(garmin_fetch_module, monkeypatch):
    fake_connectapi = _set_up(
        garmin_fetch_module, monkeypatch, "SUBMITTED", request_refresh=False
    )

    garmin_fetch_module.daily_fetch_write(DATE_STR)

    assert fake_connectapi.calls == []
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"')


def test_refresh_logic_skipped_when_date_too_recent(garmin_fetch_module, monkeypatch):
    fake_connectapi = _set_up(garmin_fetch_module, monkeypatch, "SUBMITTED")

    garmin_fetch_module.daily_fetch_write(_recent_date_str())

    assert fake_connectapi.calls == []
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"')


def test_submitted_status_sleeps_then_proceeds(garmin_fetch_module, monkeypatch):
    fake_connectapi = _set_up(garmin_fetch_module, monkeypatch, "SUBMITTED")
    sleeps = _sleep_recorder(monkeypatch, garmin_fetch_module)

    garmin_fetch_module.daily_fetch_write(DATE_STR)

    assert len(fake_connectapi.calls) == 1
    assert sleeps == [10]
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"')


def test_complete_status_proceeds_without_sleeping(garmin_fetch_module, monkeypatch):
    _set_up(garmin_fetch_module, monkeypatch, "COMPLETE")
    sleeps = _sleep_recorder(monkeypatch, garmin_fetch_module)

    garmin_fetch_module.daily_fetch_write(DATE_STR)

    assert sleeps == []
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"')


def test_no_files_found_status_skips_metric_handlers_entirely(
    garmin_fetch_module, monkeypatch
):
    _set_up(garmin_fetch_module, monkeypatch, "NO_FILES_FOUND")

    result = garmin_fetch_module.daily_fetch_write(DATE_STR)

    assert result is None
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"') == []


def test_denied_status_sleeps_24h_then_retries_then_proceeds(
    garmin_fetch_module, monkeypatch
):
    fake_connectapi = _set_up(garmin_fetch_module, monkeypatch, "DENIED")
    sleeps = _sleep_recorder(monkeypatch, garmin_fetch_module)

    garmin_fetch_module.daily_fetch_write(DATE_STR)

    # requested twice: the initial request, then the retry after the 24h wait
    assert len(fake_connectapi.calls) == 2
    assert sleeps == [86500, 10]
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"')


def test_unknown_status_sleeps_briefly_then_proceeds(garmin_fetch_module, monkeypatch):
    _set_up(garmin_fetch_module, monkeypatch, "SOME_OTHER_STATUS")
    sleeps = _sleep_recorder(monkeypatch, garmin_fetch_module)

    garmin_fetch_module.daily_fetch_write(DATE_STR)

    assert sleeps == [5]
    assert garmin_fetch_module.INFLUXDB_STORAGE.query('SELECT * FROM "Hydration"')
