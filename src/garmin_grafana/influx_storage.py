"""
InfluxDB v1/v3 client wrapper, extracted from garmin_fetch.py and
influxdb_exporter.py (which duplicated the same client-construction and
version-branching logic near-verbatim).

Construction does no I/O for either backend (confirmed against both
InfluxDBClient's and InfluxDBClient3's __init__ -- both just parse args and
build an internal API client object). That's what lets InfluxStorage(config)
be constructed at module import time safely: connectivity is only verified
when check_connection() is called explicitly, which garmin_fetch.py now does
once at actual startup (in __main__), not as an import-time side effect.
"""

from datetime import datetime, timedelta
from typing import Any, Mapping

import pytz
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError
from influxdb_client_3 import InfluxDBClient3, InfluxDBError

from config import Config


class InfluxStorage:
    def __init__(self, config: Config):
        self.version = config.influxdb_version
        scheme = "http" if config.influxdb_endpoint_is_http else "https"

        if self.version == "1":
            self._client = InfluxDBClient(
                host=config.influxdb_host,
                port=config.influxdb_port,
                username=config.influxdb_username,
                password=config.influxdb_password,
                ssl=not config.influxdb_endpoint_is_http,
                verify_ssl=not config.influxdb_endpoint_is_http,
            )
            self._client.switch_database(config.influxdb_database)
        else:
            self._client = InfluxDBClient3(
                host=f"{scheme}://{config.influxdb_host}:{config.influxdb_port}",
                token=config.influxdb_v3_access_token,
                org=config.influxdb_org,
                database=config.influxdb_database,
            )

    def check_connection(self) -> None:
        """
        Writes/overwrites a demo point to confirm the database is reachable.
        Raises InfluxDBClientError (wrapping the underlying error) on
        failure -- same behavior as garmin_fetch.py's former import-time
        check, just invoked explicitly instead of as an import side effect.
        """
        demo_point = {
            "measurement": "DemoPoint",
            "time": (datetime.now(pytz.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"),
            "tags": {"DemoTag": "DemoTagValue"},
            "fields": {"DemoField": 0},
        }
        try:
            self.write_points([demo_point])
        except (InfluxDBClientError, InfluxDBError) as err:
            raise InfluxDBClientError("InfluxDB connection failed:" + str(err)) from err

    def write_points(self, points: list, chunk_size: int = 20000) -> None:
        """
        Writes points in chunks (large activities can exceed 20000 points,
        which previously hit a 413 payload-too-large error -- see the
        original write_points_to_influxdb). Does not catch exceptions;
        callers decide how to handle write failures, matching the existing
        separation between this and garmin_fetch.py's write_points_to_influxdb.
        """
        for i in range(0, len(points), chunk_size):
            chunk = points[i : i + chunk_size]
            if self.version == "1":
                self._client.write_points(chunk)
            else:
                self._client.write(record=chunk)

    def query(self, query_str: str) -> list:
        """
        Normalizes v1's `.query(str).get_points()` and v3's
        `.query(query=str, language="influxql").to_pylist()` into one call
        shape: always a plain list of row mappings. Does NOT normalize the
        `time` field's type -- v1 returns it as a string, v3 as a native
        datetime -- that's a pre-existing difference left to callers that
        already know to handle it, not silently changed here.
        """
        if self.version == "1":
            return list(self._client.query(query_str).get_points())
        return self._client.query(query=query_str, language="influxql").to_pylist()

    def delete_series(self, measurement: str, tags: Mapping[str, Any]) -> None:
        """v1 only. Raises NotImplementedError on v3 -- callers decide what
        that means for them (see garmin_fetch.py's
        purge_existing_strength_exercise_sets, which already guards this
        with its own InfluxDB-version check before ever calling this)."""
        if self.version != "1":
            raise NotImplementedError(f"delete_series is not supported on InfluxDB v{self.version}")
        self._client.delete_series(measurement=measurement, tags=dict(tags))
