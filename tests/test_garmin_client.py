"""
Tests for garmin_client.py -- garmin_login() and the headless-MFA fix.

None of these need the disposable test InfluxDB or the garmin_fetch_module
fixture: that's the actual point of extracting this into its own module with
an explicit Config parameter, rather than reading garmin_fetch.py's bare
globals. Compare the previous version of this coverage
(tests/test_login_headless.py, now folded in here), which had to reach into
garmin_fetch_module just to get at garmin_login/Garmin.
"""

import base64
import logging
import sys

import pytest

import garmin_client
from config import Config


# -- _prompt_mfa() -----------------------------------------------------------


def test_prompt_mfa_raises_clearly_when_not_interactive(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(RuntimeError, match="MFA code required.*interactive terminal"):
        garmin_client._prompt_mfa()


def test_prompt_mfa_calls_input_when_interactive(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "  123456  ")
    assert garmin_client._prompt_mfa() == "123456"


# -- garmin_login() -----------------------------------------------------------


class _FakeGarminMFA:
    """
    Mimics garminconnect.Garmin closely enough to exercise garmin_login()'s
    two-stage login flow: a token-based attempt that fails, followed by a
    credential+MFA attempt whose prompt_mfa callback is invoked for real.

    Wraps *any* exception from prompt_mfa() into GarminConnectConnectionError,
    matching the real library's broad `except Exception` handler in its outer
    Garmin.login() (verified against garminconnect/__init__.py) -- not just
    the specific EOFError case the old input()-based implementation hit.
    """

    def __init__(self, email=None, password=None, is_cn=False, prompt_mfa=None):
        self._prompt_mfa = prompt_mfa

    def login(self, token_store):
        if self._prompt_mfa is None:
            # First attempt in garmin_login(): Garmin() with no stored token.
            raise FileNotFoundError("no stored token for test")

        try:
            self._prompt_mfa()
        except Exception as err:
            from garminconnect import GarminConnectConnectionError

            raise GarminConnectConnectionError(f"Login failed: {err}") from err


def _config_with_credentials():
    return Config.from_env(
        {
            "GARMINCONNECT_EMAIL": "test@example.com",
            "GARMINCONNECT_BASE64_PASSWORD": base64.b64encode(b"dummy-password").decode(),
        }
    )


def test_headless_mfa_fails_with_documented_exception_and_clear_log(monkeypatch, caplog):
    """
    Pins the same overall outcome as before this fix (garmin_login() still
    raises Exception("Garmin login failed after credential/MFA attempt") --
    the crash-and-let-`restart: unless-stopped`-retry behavior itself is
    unchanged, fixing that is a separate concern) -- but now the actual
    logged error is diagnosable instead of a bare "EOF when reading a line".
    """
    monkeypatch.setattr(garmin_client, "Garmin", _FakeGarminMFA)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception, match="Garmin login failed after credential/MFA attempt"):
            garmin_client.garmin_login(_config_with_credentials())

    assert "MFA code required" in caplog.text
    assert "interactive terminal" in caplog.text


def test_interactive_mfa_still_works(monkeypatch):
    """The actual point of checking isatty() rather than always failing:
    a real interactive terminal still gets prompted normally."""
    monkeypatch.setattr(garmin_client, "Garmin", _FakeGarminMFA)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "123456")

    # _FakeGarminMFA.login() doesn't raise when prompt_mfa() succeeds, and
    # garmin_login() returns whatever the last-constructed Garmin() is.
    result = garmin_client.garmin_login(_config_with_credentials())
    assert isinstance(result, _FakeGarminMFA)
