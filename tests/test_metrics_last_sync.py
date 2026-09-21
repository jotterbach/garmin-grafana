"""
Characterization tests for phase 5 of the metric registry refactor:
get_last_sync -- the last function deferred out of phase 3, for a real
reason: it takes no date_str and mutates module globals (GARMIN_DEVICENAME,
GARMIN_DEVICEID) as a side effect, architecturally different from every
other get_X function. Migrating it onto the existing
metric_points.build_timestamped_point() (no new helper needed).

Both tests mutate GARMIN_DEVICENAME/GARMIN_DEVICEID/GARMIN_DEVICENAME_AUTOMATIC,
which are shared module-level globals read by every other point-building
function in garmin_fetch.py -- each test captures the original values and
restores them in a finally block, so a failure here can't leak state into
other tests in the same session.
"""

DATE_STR = "2026-01-15"


def test_last_sync_no_mutation_when_not_automatic(garmin_fetch_module):
    """The default test environment has GARMIN_DEVICENAME_AUTOMATIC=False
    (GARMIN_DEVICENAME is explicitly set to "TestDevice", not left as the
    "Unknown" sentinel that would enable automatic mode) -- confirms the
    globals are NOT overwritten in this mode, and the point uses the
    existing (unmutated) values."""
    assert garmin_fetch_module.GARMIN_DEVICENAME_AUTOMATIC is False
    original_name = garmin_fetch_module.GARMIN_DEVICENAME
    original_id = garmin_fetch_module.GARMIN_DEVICEID

    points = garmin_fetch_module.get_last_sync()

    assert garmin_fetch_module.GARMIN_DEVICENAME == original_name
    assert garmin_fetch_module.GARMIN_DEVICEID == original_id
    assert points == [
        {
            "measurement": "DeviceSync",
            "time": "2026-01-15T07:00:00+00:00",
            "tags": {"Device": original_name, "Database_Name": "SmokeTestDB"},
            "fields": {
                "imageUrl": "https://example.com/device-image.png",
                "Device_Name": original_name,
            },
        }
    ]


def test_last_sync_mutates_globals_when_automatic(garmin_fetch_module):
    """When GARMIN_DEVICENAME_AUTOMATIC is True, get_last_sync updates
    GARMIN_DEVICENAME/GARMIN_DEVICEID from the sync data before building
    the point, so the point's Device tag and Device_Name field reflect
    the newly-updated name, not the old one."""
    original_automatic = garmin_fetch_module.GARMIN_DEVICENAME_AUTOMATIC
    original_name = garmin_fetch_module.GARMIN_DEVICENAME
    original_id = garmin_fetch_module.GARMIN_DEVICEID
    try:
        garmin_fetch_module.GARMIN_DEVICENAME_AUTOMATIC = True

        points = garmin_fetch_module.get_last_sync()

        assert garmin_fetch_module.GARMIN_DEVICENAME == "Forerunner 970"
        assert garmin_fetch_module.GARMIN_DEVICEID == 3456789012
        assert points == [
            {
                "measurement": "DeviceSync",
                "time": "2026-01-15T07:00:00+00:00",
                "tags": {"Device": "Forerunner 970", "Database_Name": "SmokeTestDB"},
                "fields": {
                    "imageUrl": "https://example.com/device-image.png",
                    "Device_Name": "Forerunner 970",
                },
            }
        ]
    finally:
        garmin_fetch_module.GARMIN_DEVICENAME_AUTOMATIC = original_automatic
        garmin_fetch_module.GARMIN_DEVICENAME = original_name
        garmin_fetch_module.GARMIN_DEVICEID = original_id
