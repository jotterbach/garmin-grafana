"""
Typed, unit-testable env-var configuration for garmin_fetch.py.

Extracted from garmin_fetch.py's module-level parsing block (previously
lines 36-74) as the first step of decomposing that file. garmin_fetch.py
still bridges every field back to the same bare module-level constant names
the rest of that file reads -- this module owns *parsing*, not yet how the
rest of the pipeline consumes it (that's a later step).

Field-for-field equivalent to the original inline os.getenv() calls,
including the pre-existing asymmetry in default direction: some booleans
default to False unless explicitly set truthy (e.g. KEEP_FIT_FILES), others
default to True unless explicitly set falsy (e.g. FORCE_REPROCESS_ACTIVITIES).
_env_bool() takes that default explicitly per field rather than assuming one
direction for all of them.
"""

import base64
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Optional

_TRUTHY = {"True", "true", "TRUE", "t", "T", "yes", "Yes", "YES", "1"}
_FALSY = {"False", "false", "FALSE", "f", "F", "no", "No", "NO", "0"}


def _env_bool(raw: Optional[str], default: bool) -> bool:
    """Matches the original inline truthy/falsy string-list checks exactly."""
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


@dataclass(frozen=True)
class Config:
    influxdb_version: str
    influxdb_host: str
    influxdb_port: int
    influxdb_username: str
    influxdb_password: str
    influxdb_database: str
    influxdb_v3_access_token: str
    influxdb_org: str
    influxdb_endpoint_is_http: bool
    token_dir: str
    garminconnect_email: Optional[str]
    garminconnect_password: Optional[str]
    garminconnect_is_cn: bool
    garmin_devicename: str
    garmin_devicename_automatic: bool
    garmin_deviceid: Optional[str]
    auto_date_range: bool
    manual_start_date: Optional[str]
    manual_end_date: str
    log_level: str
    fetch_failed_wait_seconds: int
    rate_limit_calls_seconds: int
    max_consecutive_500_errors: int
    update_interval_seconds: int
    fetch_selection: str
    activity_type_filter: list = field(default_factory=list)
    lactate_threshold_sports: list = field(default_factory=list)
    ftp_sports: list = field(default_factory=list)
    keep_fit_files: bool = False
    fit_file_storage_location: str = ""
    always_process_fit_files: bool = False
    request_intraday_data_refresh: bool = False
    ignore_intraday_data_refresh_days: int = 30
    tag_measurements_with_user_email: bool = False
    force_reprocess_activities: bool = True
    user_timezone: str = ""
    ignore_errors: bool = False

    def __post_init__(self):
        assert self.influxdb_version in ("1", "3"), (
            "Only InfluxDB version 1 or 3 is allowed - please ensure to set "
            "this value to either 1 or 3"
        )

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = env if env is not None else os.environ

        garminconnect_email = (env.get("GARMINCONNECT_EMAIL") or "").strip() or None
        garmin_pw_b64 = env.get("GARMINCONNECT_BASE64_PASSWORD")
        garminconnect_password = (
            base64.b64decode(garmin_pw_b64).decode("utf-8").strip()
            if garmin_pw_b64
            else None
        )
        garmin_devicename = env.get("GARMIN_DEVICENAME", "Unknown")

        return cls(
            influxdb_version=env.get("INFLUXDB_VERSION", "1"),
            influxdb_host=env.get("INFLUXDB_HOST", "localhost"),
            influxdb_port=int(env.get("INFLUXDB_PORT", 8086)),
            influxdb_username=env.get("INFLUXDB_USERNAME", "influxdb_username"),
            influxdb_password=env.get("INFLUXDB_PASSWORD", "influxdb_access_password"),
            influxdb_database=env.get("INFLUXDB_DATABASE", "GarminStats"),
            influxdb_v3_access_token=env.get("INFLUXDB_V3_ACCESS_TOKEN", ""),
            influxdb_org=env.get("INFLUXDB_ORG", "default"),
            influxdb_endpoint_is_http=_env_bool(
                env.get("INFLUXDB_ENDPOINT_IS_HTTP"), default=True
            ),
            token_dir=env.get("TOKEN_DIR", "~/.garminconnect"),
            garminconnect_email=garminconnect_email,
            garminconnect_password=garminconnect_password,
            garminconnect_is_cn=_env_bool(env.get("GARMINCONNECT_IS_CN"), default=False),
            garmin_devicename=garmin_devicename,
            garmin_devicename_automatic=garmin_devicename == "Unknown",
            garmin_deviceid=env.get("GARMIN_DEVICEID", None),
            auto_date_range=_env_bool(env.get("AUTO_DATE_RANGE"), default=True),
            manual_start_date=env.get("MANUAL_START_DATE", None),
            manual_end_date=env.get(
                "MANUAL_END_DATE", datetime.today().strftime("%Y-%m-%d")
            ),
            log_level=env.get("LOG_LEVEL", "INFO"),
            fetch_failed_wait_seconds=int(env.get("FETCH_FAILED_WAIT_SECONDS", 1800)),
            rate_limit_calls_seconds=int(env.get("RATE_LIMIT_CALLS_SECONDS", 5)),
            max_consecutive_500_errors=int(env.get("MAX_CONSECUTIVE_500_ERRORS", 10)),
            update_interval_seconds=int(env.get("UPDATE_INTERVAL_SECONDS", 300)),
            fetch_selection=env.get(
                "FETCH_SELECTION",
                "daily_avg,sleep,steps,heartrate,stress,breathing,hrv,"
                "fitness_age,vo2,activity,race_prediction,body_composition,lifestyle",
            ),
            activity_type_filter=[
                t.strip().lower()
                for t in env.get("ACTIVITY_TYPE_FILTER", "").split(",")
                if t.strip()
            ],
            lactate_threshold_sports=env.get("LACTATE_THRESHOLD_SPORTS", "RUNNING")
            .upper()
            .split(","),
            # Separate from lactate_threshold_sports: FTP applies broadly
            # (confirmed live for both running and cycling), unlike
            # lactateThresholdSpeed/HeartRate, which aren't meaningful for
            # cycling -- see #22. A shared sport list would mean either
            # missing cycling FTP or wasting two empty calls/day fetching
            # cycling lactate threshold speed/HR that Garmin doesn't track.
            ftp_sports=env.get("FTP_SPORTS", "RUNNING,CYCLING")
            .upper()
            .split(","),
            keep_fit_files=_env_bool(env.get("KEEP_FIT_FILES"), default=False),
            fit_file_storage_location=env.get(
                "FIT_FILE_STORAGE_LOCATION",
                os.path.join(os.path.expanduser("~"), "fit_filestore"),
            ),
            always_process_fit_files=_env_bool(
                env.get("ALWAYS_PROCESS_FIT_FILES"), default=False
            ),
            request_intraday_data_refresh=_env_bool(
                env.get("REQUEST_INTRADAY_DATA_REFRESH"), default=False
            ),
            ignore_intraday_data_refresh_days=int(
                env.get("IGNORE_INTRADAY_DATA_REFRESH_DAYS", 30)
            ),
            tag_measurements_with_user_email=_env_bool(
                env.get("TAG_MEASUREMENTS_WITH_USER_EMAIL"), default=False
            ),
            force_reprocess_activities=_env_bool(
                env.get("FORCE_REPROCESS_ACTIVITIES"), default=True
            ),
            user_timezone=env.get("USER_TIMEZONE", ""),
            ignore_errors=_env_bool(env.get("IGNORE_ERRORS"), default=False),
        )
