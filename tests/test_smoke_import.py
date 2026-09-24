"""
Confirms `garmin_fetch.py` can be imported at all in a fresh process.

Runs in a real subprocess rather than reusing the already-imported module
other test files rely on (via the garmin_fetch_module fixture) -- otherwise
this test would just be re-checking an import Python has already cached and
would never actually catch a real import-time break.

cwd/import style deliberately matches production (Dockerfile: `python
garmin_grafana/garmin_fetch.py`, run from the directory containing it, bare
sibling imports) rather than a package-qualified import -- see
tests/conftest.py's module docstring.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SRC_PACKAGE_DIR = REPO_ROOT / "src" / "garmin_grafana"


def _import_garmin_fetch(env):
    return subprocess.run(
        [sys.executable, "-c", "import garmin_fetch"],
        cwd=str(SRC_PACKAGE_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_module_imports_cleanly_against_reachable_influxdb():
    result = _import_garmin_fetch(os.environ.copy())
    assert result.returncode == 0, f"importing garmin_fetch failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_module_imports_cleanly_even_with_unreachable_influxdb():
    """
    The actual point of the InfluxDB wrapper extraction (influx_storage.py):
    import no longer does any network I/O at all, so it succeeds regardless
    of whether InfluxDB is reachable -- connectivity is only verified by an
    explicit check_connection() call at real startup (__main__). Before this
    refactor, this exact env would have made the import itself fail.
    """
    env = os.environ.copy()
    env["INFLUXDB_HOST"] = "192.0.2.1"  # TEST-NET-1 (RFC 5737), guaranteed unreachable
    env["INFLUXDB_PORT"] = "1"

    result = _import_garmin_fetch(env)
    assert result.returncode == 0, (
        f"importing garmin_fetch should succeed even with InfluxDB unreachable:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
