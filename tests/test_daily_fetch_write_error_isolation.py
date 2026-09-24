"""
Characterization tests for per-metric-handler error isolation in
daily_fetch_write's dispatch loop.

Real production crash (2026-09-24): a 3-year backfill died with an
uncaught AttributeError inside get_solar_intensity. fetch_write_bulk's
per-day retry/backoff loop only catches specific connection/auth/
rate-limit errors -- anything else propagates all the way up and kills
the whole process (IGNORE_ERRORS=True, not the default, is the existing
day-level escape hatch, but even that only skips the *entire remaining
day*, not just the one broken handler). Worse: before this change,
daily_fetch_write's for-loop had no per-handler guard at all, so one
broken metric handler aborted every *other*, unrelated, working handler
for that same day too -- not just the broken one.

Each handler call is now individually guarded: a genuine bug (anything
not already one of fetch_write_bulk's retryable API/network error types)
is logged and skipped, and the loop continues with the next metric.
Connection/auth/rate-limit errors are deliberately NOT caught here --
they still propagate up to fetch_write_bulk, which needs to see them to
retry/backoff/skip a whole day correctly; swallowing them per-metric
here would silently break that existing behavior.
"""

DATE_STR = "2026-01-15"


def test_one_broken_metric_handler_does_not_prevent_others_from_running(garmin_fetch_module, monkeypatch):
    monkeypatch.setattr(garmin_fetch_module, "FETCH_SELECTION", "hydration,hill_score")
    monkeypatch.setattr(garmin_fetch_module, "REQUEST_INTRADAY_DATA_REFRESH", False)

    def broken_hydration(date_str):
        raise AttributeError("'list' object has no attribute 'get'")

    monkeypatch.setattr(garmin_fetch_module, "get_hydration", broken_hydration)

    garmin_fetch_module.daily_fetch_write(DATE_STR)

    storage = garmin_fetch_module.INFLUXDB_STORAGE
    assert storage.query('SELECT * FROM "Hydration"') == []
    # hill_score's handler ran fine and wasn't skipped just because
    # hydration's, earlier in dict-iteration order, blew up.
    assert storage.query('SELECT * FROM "HillScore"')


def test_connection_errors_from_a_handler_still_propagate_up(garmin_fetch_module, monkeypatch):
    """
    fetch_write_bulk's retry/backoff/500-counter logic depends on seeing
    these exception types -- swallowing them at the per-metric level
    here would silently disable that existing, working behavior.
    """
    monkeypatch.setattr(garmin_fetch_module, "FETCH_SELECTION", "hydration")
    monkeypatch.setattr(garmin_fetch_module, "REQUEST_INTRADAY_DATA_REFRESH", False)

    def flaky_hydration(date_str):
        raise garmin_fetch_module.GarminConnectConnectionError("connection reset")

    monkeypatch.setattr(garmin_fetch_module, "get_hydration", flaky_hydration)

    import pytest

    with pytest.raises(garmin_fetch_module.GarminConnectConnectionError):
        garmin_fetch_module.daily_fetch_write(DATE_STR)
