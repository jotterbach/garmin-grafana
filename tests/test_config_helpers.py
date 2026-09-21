"""
Cheap, direct unit tests for small pure-logic pieces of garmin_fetch.py, plus
a couple of subprocess-based checks that the hand-rolled boolean env-var
parsing (repeated ~15 times across the module, e.g. garmin_fetch.py:65,67,68)
still accepts both truthy and falsy string forms correctly.

Subprocess-based because the parsing happens inline at module import time
into module-level constants, not through a shared helper function -- the
only way to test a specific env var's effect is to import the module fresh
in its own process with that var set, same pattern used by
claude-local-devbox-mcp's ServerStartupTests.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def test_iter_days_is_reverse_chronological_and_inclusive(garmin_fetch_module):
    days = list(garmin_fetch_module.iter_days("2026-01-13", "2026-01-15"))
    assert days == ["2026-01-15", "2026-01-14", "2026-01-13"]


def test_iter_days_single_day():
    from garmin_grafana import garmin_fetch

    assert list(garmin_fetch.iter_days("2026-01-15", "2026-01-15")) == ["2026-01-15"]


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


@pytest.mark.parametrize(
    "value,expected",
    [
        ("True", True),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("False", False),
        ("false", False),
        ("0", False),
        ("no", False),
    ],
)
def test_keep_fit_files_env_var_parsing(value, expected):
    env = os.environ.copy()
    env["KEEP_FIT_FILES"] = value
    result = subprocess.run(
        [sys.executable, "-c", "from garmin_grafana import garmin_fetch; print(garmin_fetch.KEEP_FIT_FILES)"],
        cwd=str(REPO_ROOT / "src"),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # garmin_fetch.py prints a banner at import time (garmin_fetch.py:29), so
    # only the last line of stdout is the value we actually printed.
    last_line = result.stdout.strip().splitlines()[-1]
    assert last_line == str(expected)
