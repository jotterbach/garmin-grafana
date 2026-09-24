"""
Direct unit tests for config.py's env-var parsing. No subprocess, no
InfluxDB, no module import side effects -- Config.from_env() takes an
explicit mapping instead of always reading os.environ, which is what makes
this possible. Compare tests/test_config_helpers.py's one remaining
subprocess test, which only checks that garmin_fetch.py bridges a Config
field back to a module-level constant correctly, not the parsing itself.
"""

import pytest

from config import Config, _env_bool


def test_defaults_with_empty_env():
    config = Config.from_env({})
    assert config.influxdb_version == "1"
    assert config.influxdb_host == "localhost"
    assert config.influxdb_port == 8086
    assert config.influxdb_database == "GarminStats"
    assert config.garmin_devicename == "Unknown"
    assert config.garmin_devicename_automatic is True
    assert config.garminconnect_email is None
    assert config.garminconnect_password is None
    assert config.manual_start_date is None
    assert config.activity_type_filter == []
    assert config.lactate_threshold_sports == ["RUNNING"]
    assert config.ftp_sports == ["RUNNING", "CYCLING"]
    # Two different default *directions* pre-exist in garmin_fetch.py's
    # original parsing (see config.py's module docstring) -- confirm both
    # survive the extraction correctly.
    assert config.keep_fit_files is False  # defaults False unless truthy
    assert config.force_reprocess_activities is True  # defaults True unless falsy
    assert config.auto_date_range is True


@pytest.mark.parametrize("raw", ["True", "true", "1", "yes", "Yes", "YES", "t", "T"])
def test_env_bool_truthy_forms(raw):
    assert _env_bool(raw, default=False) is True
    assert _env_bool(raw, default=True) is True


@pytest.mark.parametrize("raw", ["False", "false", "0", "no", "No", "NO", "f", "F"])
def test_env_bool_falsy_forms(raw):
    assert _env_bool(raw, default=True) is False
    assert _env_bool(raw, default=False) is False


@pytest.mark.parametrize("raw", [None, "", "garbage", "maybe"])
def test_env_bool_unrecognized_falls_back_to_default(raw):
    assert _env_bool(raw, default=True) is True
    assert _env_bool(raw, default=False) is False


def test_keep_fit_files_overridden_truthy():
    assert Config.from_env({"KEEP_FIT_FILES": "yes"}).keep_fit_files is True


def test_force_reprocess_activities_overridden_falsy():
    assert (
        Config.from_env({"FORCE_REPROCESS_ACTIVITIES": "no"}).force_reprocess_activities
        is False
    )


def test_garminconnect_base64_password_is_decoded():
    # base64 for "hunter2"
    config = Config.from_env({"GARMINCONNECT_BASE64_PASSWORD": "aHVudGVyMg=="})
    assert config.garminconnect_password == "hunter2"


def test_garminconnect_password_absent_when_not_set():
    assert Config.from_env({}).garminconnect_password is None


def test_garmin_devicename_automatic_false_when_explicit():
    config = Config.from_env({"GARMIN_DEVICENAME": "Forerunner 965"})
    assert config.garmin_devicename == "Forerunner 965"
    assert config.garmin_devicename_automatic is False


def test_activity_type_filter_splits_lowercases_and_strips():
    config = Config.from_env({"ACTIVITY_TYPE_FILTER": " Running, Cycling ,,Hiking"})
    assert config.activity_type_filter == ["running", "cycling", "hiking"]


def test_lactate_threshold_sports_splits_and_uppercases():
    config = Config.from_env({"LACTATE_THRESHOLD_SPORTS": "running,cycling"})
    assert config.lactate_threshold_sports == ["RUNNING", "CYCLING"]


def test_ftp_sports_defaults_to_running_and_cycling():
    config = Config.from_env({})
    assert config.ftp_sports == ["RUNNING", "CYCLING"]


def test_ftp_sports_splits_and_uppercases():
    config = Config.from_env({"FTP_SPORTS": "running"})
    assert config.ftp_sports == ["RUNNING"]


def test_numeric_fields_parse_as_int():
    config = Config.from_env(
        {
            "INFLUXDB_PORT": "9999",
            "RATE_LIMIT_CALLS_SECONDS": "10",
            "MAX_CONSECUTIVE_500_ERRORS": "3",
        }
    )
    assert config.influxdb_port == 9999
    assert config.rate_limit_calls_seconds == 10
    assert config.max_consecutive_500_errors == 3


def test_invalid_influxdb_version_raises():
    with pytest.raises(AssertionError):
        Config.from_env({"INFLUXDB_VERSION": "2"})
