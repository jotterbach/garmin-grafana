"""
Regression guard for a real bug found during #22/#45/#49's work: 6 metrics
(fitness_age, lifestyle, solar_intensity, training_status, plus the newly
added running_economy, cycling_ability) were fully implemented in
DAILY_METRIC_HANDLERS -- coded, tested, and shipped -- but silently never
added to this deployment's FETCH_SELECTION in compose.yml. They collected
nothing in production, with no test or CI check flagging the gap; it took
a manual audit to find it.

This parses compose.yml's actual FETCH_SELECTION value (the real,
canonical deployment config this project tracks -- not a template) and
asserts every DAILY_METRIC_HANDLERS key is present, or explicitly listed
in INTENTIONALLY_NOT_DEFAULT below with a reason. Forces a conscious
choice (enable it, or document why not) instead of silent omission --
does not force every metric to be enabled, since FETCH_SELECTION is a
deliberate opt-in surface (see README) and some metrics may reasonably
stay off for a given deployment.
"""

import re
from pathlib import Path

import garmin_fetch

REPO_ROOT = Path(__file__).parent.parent

# Metrics implemented in DAILY_METRIC_HANDLERS but deliberately not enabled
# in this deployment's FETCH_SELECTION. Document *why*, don't just silence
# the test -- an empty dict here means every implemented metric is
# currently enabled, which is this deployment's actual, intentional state
# as of the last audit, not an oversight.
INTENTIONALLY_NOT_DEFAULT: dict[str, str] = {}


def _compose_fetch_selection():
    compose_text = (REPO_ROOT / "compose.yml").read_text()
    match = re.search(r"FETCH_SELECTION=([a-zA-Z_0-9,]+)", compose_text)
    assert match, "FETCH_SELECTION not found in compose.yml"
    return set(match.group(1).split(","))


def test_every_daily_metric_handler_is_in_fetch_selection_or_explicitly_excluded():
    handler_keys = set(garmin_fetch.DAILY_METRIC_HANDLERS.keys())
    enabled = _compose_fetch_selection()
    excluded = set(INTENTIONALLY_NOT_DEFAULT.keys())

    unaccounted = handler_keys - enabled - excluded
    assert not unaccounted, (
        f"{sorted(unaccounted)} implemented in DAILY_METRIC_HANDLERS but "
        f"missing from compose.yml's FETCH_SELECTION, and not listed in "
        f"INTENTIONALLY_NOT_DEFAULT with a reason. Either add to "
        f"FETCH_SELECTION or document why it's deliberately opt-in."
    )


def test_fetch_selection_has_no_unknown_metrics():
    """Catches the inverse case: a stale or misspelled FETCH_SELECTION entry
    that doesn't correspond to any real handler."""
    handler_keys = set(garmin_fetch.DAILY_METRIC_HANDLERS.keys())
    enabled = _compose_fetch_selection()

    unknown = enabled - handler_keys
    assert not unknown, f"FETCH_SELECTION references unknown metric(s): {sorted(unknown)}"
