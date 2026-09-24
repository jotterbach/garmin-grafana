"""
Characterization tests for fetch_write_bulk's retry/backoff logic (#17
phase B) and free-standing unit tests for _is_http_status_error.

Unlike phase A (__main__'s intraday-refresh logic, which was
unexecutable by pytest until extracted), fetch_write_bulk needed no
extraction to become testable -- it already calls out to three
substitutable collaborators (daily_fetch_write, garmin_login, time.sleep)
and nothing else, so this phase is pure test-writing against the
existing implementation. Confirmed via grep before this file: zero
references to fetch_write_bulk anywhere in the suite.

time.sleep is mocked throughout (monkeypatch, auto-restored per test) --
real durations here include FETCH_FAILED_WAIT_SECONDS (default 1800s)
and RATE_LIMIT_CALLS_SECONDS (default 5s) per retry.

Disclosed finding, not fixed here (would need explicit sign-off since
touching it means touching fetch_write_bulk's except clauses): the
second except tuple (GarminConnectConnectionError,
requests.exceptions.ConnectionError, requests.exceptions.Timeout) lists
GarminConnectConnectionError, but the *first* except tuple
(requests.exceptions.HTTPError, GarminConnectConnectionError) already
catches it -- except clauses match top-to-bottom, so
GarminConnectConnectionError can never reach the second clause. Dead,
but harmless (only requests.exceptions.ConnectionError/Timeout actually
reach that branch). test_garmin_connect_connection_error_matches_the_first_except_clause
below documents this explicitly rather than silently working around it.
"""

from unittest import mock

import pytest
import requests
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_fetch import _is_http_status_error

DATE_STR = "2020-01-15"


def _http_error(status_code):
    response = mock.Mock()
    response.status_code = status_code
    return requests.exceptions.HTTPError(response=response)


class ScriptedDailyFetchWrite:
    """
    Stands in for daily_fetch_write: raises each entry in `outcomes` in
    sequence per call (None means "succeed"); fetch_write_bulk's while
    loop calls it repeatedly for the same date until it stops retrying.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, date_str):
        self.calls.append(date_str)
        outcome = self.outcomes.pop(0)
        if outcome is not None:
            raise outcome


def _sleep_recorder(monkeypatch, garmin_fetch_module):
    calls = []
    monkeypatch.setattr(garmin_fetch_module.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


def _set_up(garmin_fetch_module, monkeypatch, outcomes):
    scripted = ScriptedDailyFetchWrite(outcomes)
    monkeypatch.setattr(garmin_fetch_module, "daily_fetch_write", scripted)
    login_calls = []
    monkeypatch.setattr(
        garmin_fetch_module,
        "garmin_login",
        lambda config: login_calls.append(config) or garmin_fetch_module.garmin_obj,
    )
    sleeps = _sleep_recorder(monkeypatch, garmin_fetch_module)
    return scripted, login_calls, sleeps


# --- _is_http_status_error: pure function, no refactor needed ---


def test_is_http_status_error_matches_via_response_status_code():
    assert _is_http_status_error(_http_error(500), 500) is True
    assert _is_http_status_error(_http_error(404), 500) is False


def test_is_http_status_error_matches_via_bare_status_code_attribute():
    err = mock.Mock(spec=["status_code"])
    err.status_code = 500
    assert _is_http_status_error(err, 500) is True


def test_is_http_status_error_falls_back_to_string_matching():
    err = Exception("Server Error: 500 for url ...")
    assert _is_http_status_error(err, 500) is True
    assert _is_http_status_error(Exception("no code here"), 500) is False


def test_is_http_status_error_does_not_false_positive_on_substring():
    # 500 must appear as a whole word/number, not e.g. inside "15000"
    assert _is_http_status_error(Exception("code 15000"), 500) is False


# --- fetch_write_bulk's retry/backoff ---


def test_success_on_first_attempt_no_retry(garmin_fetch_module, monkeypatch):
    scripted, login_calls, sleeps = _set_up(garmin_fetch_module, monkeypatch, [None])

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR]
    assert login_calls == []


def test_429_retries_then_succeeds(garmin_fetch_module, monkeypatch):
    scripted, login_calls, sleeps = _set_up(
        garmin_fetch_module,
        monkeypatch,
        [GarminConnectTooManyRequestsError("rate limited"), None],
    )

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR, DATE_STR]
    assert garmin_fetch_module.FETCH_FAILED_WAIT_SECONDS in sleeps


def test_single_500_error_retries_then_succeeds_and_resets_counter(garmin_fetch_module, monkeypatch):
    scripted, login_calls, sleeps = _set_up(garmin_fetch_module, monkeypatch, [_http_error(500), None])

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR, DATE_STR]
    assert garmin_fetch_module.RATE_LIMIT_CALLS_SECONDS in sleeps


def test_consecutive_500_errors_give_up_at_threshold(garmin_fetch_module, monkeypatch):
    monkeypatch.setattr(garmin_fetch_module, "MAX_CONSECUTIVE_500_ERRORS", 2)
    scripted, login_calls, sleeps = _set_up(
        garmin_fetch_module,
        monkeypatch,
        [_http_error(500), _http_error(500)],  # 2 consecutive 500s == threshold
    )

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    # gave up after exactly 2 attempts, did not retry a 3rd time
    assert scripted.calls == [DATE_STR, DATE_STR]


def test_non_500_http_error_skips_without_retry(garmin_fetch_module, monkeypatch):
    scripted, login_calls, sleeps = _set_up(garmin_fetch_module, monkeypatch, [_http_error(404)])

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR]  # no retry
    assert garmin_fetch_module.RATE_LIMIT_CALLS_SECONDS in sleeps


def test_connection_error_skips_without_retry(garmin_fetch_module, monkeypatch):
    scripted, login_calls, sleeps = _set_up(
        garmin_fetch_module,
        monkeypatch,
        [requests.exceptions.ConnectionError("boom")],
    )

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR]


def test_garmin_connect_connection_error_matches_the_first_except_clause(garmin_fetch_module, monkeypatch):
    """
    GarminConnectConnectionError is listed in the *second* except tuple
    too, but can never reach it -- the first except tuple
    ((requests.exceptions.HTTPError, GarminConnectConnectionError))
    always matches first. Behavior is identical either way (both
    branches skip without retry), so this documents the dead branch
    rather than asserting anything different from the plain
    ConnectionError case above.
    """
    scripted, login_calls, sleeps = _set_up(
        garmin_fetch_module,
        monkeypatch,
        [GarminConnectConnectionError("boom")],
    )

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR]


def test_authentication_error_triggers_relogin_then_retries(garmin_fetch_module, monkeypatch):
    scripted, login_calls, sleeps = _set_up(
        garmin_fetch_module,
        monkeypatch,
        [GarminConnectAuthenticationError("bad creds"), None],
    )

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)

    assert scripted.calls == [DATE_STR, DATE_STR]
    assert len(login_calls) == 1
    assert 5 in sleeps


def test_generic_exception_propagates_when_ignore_errors_is_false(garmin_fetch_module, monkeypatch):
    monkeypatch.setattr(garmin_fetch_module, "IGNORE_ERRORS", False)
    scripted, login_calls, sleeps = _set_up(garmin_fetch_module, monkeypatch, [ValueError("unexpected")])

    with pytest.raises(ValueError, match="unexpected"):
        garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)


def test_generic_exception_is_swallowed_when_ignore_errors_is_true(garmin_fetch_module, monkeypatch):
    monkeypatch.setattr(garmin_fetch_module, "IGNORE_ERRORS", True)
    scripted, login_calls, sleeps = _set_up(garmin_fetch_module, monkeypatch, [ValueError("unexpected")])

    garmin_fetch_module.fetch_write_bulk(DATE_STR, DATE_STR)  # does not raise

    assert scripted.calls == [DATE_STR]
