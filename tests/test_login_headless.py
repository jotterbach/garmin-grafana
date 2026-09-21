"""
Pins the known non-interactive-MFA limitation in garmin_login()
(garmin_fetch.py:139-182): when the stored session token is invalid/expired
and the account requires MFA, garmin_login() prompts for the MFA code via a
blocking input() call. In a headless/detached container (this project's
primary deployment target -- restart: unless-stopped in its own
docker-compose.yml) there is no TTY to read from, so this currently raises
EOFError, which garmin_login() wraps into a generic
Exception("Garmin login failed after credential/MFA attempt").

This is the exact failure mode that shipped in commit 6720ed9 and crash-
looped a live deployment during this project's own MFA-token-renewal cycle,
repeatedly re-hitting Garmin's rate-limited login endpoint on every restart.

This test does NOT assert that behavior is good -- it pins it, so a future
fix to this code path (e.g. detecting non-interactive stdin and failing
fast with a clear message instead) is a deliberate, visible test change,
not another silent regression.
"""

import pytest


class _FakeGarminMFA:
    """
    Mimics garminconnect.Garmin closely enough to exercise garmin_login()'s
    two-stage login flow: a token-based attempt that fails, followed by a
    credential+MFA attempt whose prompt_mfa callback is invoked for real.
    """

    def __init__(self, email=None, password=None, is_cn=False, prompt_mfa=None):
        self._prompt_mfa = prompt_mfa

    def login(self, token_store):
        if self._prompt_mfa is None:
            # First attempt in garmin_login(): Garmin() with no stored token.
            raise FileNotFoundError("no stored token for test")

        try:
            self._prompt_mfa()
        except EOFError as err:
            # Mirrors garminconnect's own wrapping of the underlying error,
            # see garminconnect/__init__.py: GarminConnectConnectionError(
            #     f"Login failed: {e}") raised from the original exception.
            from garminconnect import GarminConnectConnectionError

            raise GarminConnectConnectionError(f"Login failed: {err}") from err


def test_headless_mfa_prompt_fails_with_documented_exception(
    garmin_fetch_module, monkeypatch
):
    monkeypatch.setattr(garmin_fetch_module, "Garmin", _FakeGarminMFA)
    monkeypatch.setattr(garmin_fetch_module, "GARMINCONNECT_EMAIL", "test@example.com")
    monkeypatch.setattr(garmin_fetch_module, "GARMINCONNECT_PASSWORD", "dummy-password")
    monkeypatch.setattr(
        "builtins.input", lambda *a, **k: (_ for _ in ()).throw(EOFError())
    )

    with pytest.raises(Exception, match="Garmin login failed after credential/MFA attempt"):
        garmin_fetch_module.garmin_login()
