"""
Confirms `garmin_fetch.py` can be imported at all in a fresh process against
a reachable (test) InfluxDB.

Runs in a real subprocess rather than reusing the already-imported module
other test files rely on (via the garmin_fetch_module fixture) -- otherwise
this test would just be re-checking an import Python has already cached and
would never actually catch the module-level connect-and-write-demo-point
code (garmin_fetch.py's import-time try/except block) breaking.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_module_imports_cleanly_against_reachable_influxdb():
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-c", "from garmin_grafana import garmin_fetch"],
        cwd=str(REPO_ROOT / "src"),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"importing garmin_fetch failed:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
