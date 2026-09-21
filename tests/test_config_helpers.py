"""
Cheap, direct unit tests for small pure-logic pieces of garmin_fetch.py.

Env-var parsing itself now lives in config.py and has its own fast, direct
unit tests in tests/test_config.py (Config.from_env(dict), no subprocess or
InfluxDB needed). What's left here is a single subprocess-based check that
garmin_fetch.py's *bridging* from Config to its bare module-level constants
(garmin_fetch.py's CONFIG.xxx -> XXX assignments) still works end-to-end in
a real process -- not a re-test of the parsing logic itself.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SRC_PACKAGE_DIR = REPO_ROOT / "src" / "garmin_grafana"


def test_iter_days_is_reverse_chronological_and_inclusive(garmin_fetch_module):
    days = list(garmin_fetch_module.iter_days("2026-01-13", "2026-01-15"))
    assert days == ["2026-01-15", "2026-01-14", "2026-01-13"]


def test_iter_days_single_day(garmin_fetch_module):
    assert list(garmin_fetch_module.iter_days("2026-01-15", "2026-01-15")) == ["2026-01-15"]


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHTTPError(Exception):
    def __init__(self, status_code):
        self.response = _FakeResponse(status_code)


def test_is_http_status_error_matches_response_status_code(garmin_fetch_module):
    err = _FakeHTTPError(500)
    assert garmin_fetch_module._is_http_status_error(err, 500) is True
    assert garmin_fetch_module._is_http_status_error(err, 429) is False


def test_is_http_status_error_falls_back_to_string_match(garmin_fetch_module):
    err = Exception("Garmin API returned 429 Too Many Requests")
    assert garmin_fetch_module._is_http_status_error(err, 429) is True


def test_keep_fit_files_bridges_from_config_end_to_end():
    env = os.environ.copy()
    env["KEEP_FIT_FILES"] = "yes"
    result = subprocess.run(
        [sys.executable, "-c", "import garmin_fetch; print(garmin_fetch.KEEP_FIT_FILES)"],
        cwd=str(SRC_PACKAGE_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # garmin_fetch.py prints a banner at import time (garmin_fetch.py:29), so
    # only the last line of stdout is the value we actually printed.
    last_line = result.stdout.strip().splitlines()[-1]
    assert last_line == "True"
