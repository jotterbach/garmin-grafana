# %%
import traceback
import re
import requests, time, pytz, logging, os, sys, dotenv, io, zipfile
from fitparse import FitFile, FitParseError
from datetime import datetime, timedelta
from influxdb.exceptions import InfluxDBClientError
from influxdb_client_3 import InfluxDBError
import xml.etree.ElementTree as ET
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from config import Config
from influx_storage import InfluxStorage
from garmin_client import garmin_login
garmin_obj = None
banner_text = """

*****  █▀▀ ▄▀█ █▀█ █▀▄▀█ █ █▄ █    █▀▀ █▀█ ▄▀█ █▀▀ ▄▀█ █▄ █ ▄▀█  *****
*****  █▄█ █▀█ █▀▄ █ ▀ █ █ █ ▀█    █▄█ █▀▄ █▀█ █▀  █▀█ █ ▀█ █▀█  *****

______________________________________________________________________

By Arpan Ghosh | Please consider supporting the project if you love it
______________________________________________________________________

"""
print(banner_text)

env_override = dotenv.load_dotenv("override-default-vars.env", override=True)
if env_override:
    logging.warning("System ENV variables are overridden with override-default-vars.env")

# %%
# All env-var parsing lives in config.py now (extracted so it's unit-testable
# without a subprocess or a live InfluxDB). Bridged back to the same bare
# module-level names below since the rest of this file (and the sibling
# scripts that reach into it) still reads them that way -- see config.py's
# module docstring for why this is a deliberate, temporary bridge rather than
# threading Config through every function in this step.
CONFIG = Config.from_env()
INFLUXDB_VERSION = CONFIG.influxdb_version
INFLUXDB_HOST = CONFIG.influxdb_host
INFLUXDB_PORT = CONFIG.influxdb_port
INFLUXDB_USERNAME = CONFIG.influxdb_username
INFLUXDB_PASSWORD = CONFIG.influxdb_password
INFLUXDB_DATABASE = CONFIG.influxdb_database
INFLUXDB_V3_ACCESS_TOKEN = CONFIG.influxdb_v3_access_token
INFLUXDB_ORG = CONFIG.influxdb_org
INFLUXDB_ENDPOINT_IS_HTTP = CONFIG.influxdb_endpoint_is_http
# GARMIN_DEVICENAME / GARMIN_DEVICEID are reassigned at runtime by
# get_last_sync() (via `global`) once auto-detection resolves the real
# device -- these are just their initial values from config, not read back
# through CONFIG after that point.
GARMIN_DEVICENAME = CONFIG.garmin_devicename
GARMIN_DEVICEID = CONFIG.garmin_deviceid
GARMIN_DEVICENAME_AUTOMATIC = CONFIG.garmin_devicename_automatic
AUTO_DATE_RANGE = CONFIG.auto_date_range
MANUAL_START_DATE = CONFIG.manual_start_date
MANUAL_END_DATE = CONFIG.manual_end_date
LOG_LEVEL = CONFIG.log_level
FETCH_FAILED_WAIT_SECONDS = CONFIG.fetch_failed_wait_seconds
RATE_LIMIT_CALLS_SECONDS = CONFIG.rate_limit_calls_seconds
MAX_CONSECUTIVE_500_ERRORS = CONFIG.max_consecutive_500_errors
UPDATE_INTERVAL_SECONDS = CONFIG.update_interval_seconds
FETCH_SELECTION = CONFIG.fetch_selection
ACTIVITY_TYPE_FILTER = CONFIG.activity_type_filter
LACTATE_THRESHOLD_SPORTS = CONFIG.lactate_threshold_sports
KEEP_FIT_FILES = CONFIG.keep_fit_files
FIT_FILE_STORAGE_LOCATION = CONFIG.fit_file_storage_location
ALWAYS_PROCESS_FIT_FILES = CONFIG.always_process_fit_files
REQUEST_INTRADAY_DATA_REFRESH = CONFIG.request_intraday_data_refresh
IGNORE_INTRADAY_DATA_REFRESH_DAYS = CONFIG.ignore_intraday_data_refresh_days
TAG_MEASUREMENTS_WITH_USER_EMAIL = CONFIG.tag_measurements_with_user_email
FORCE_REPROCESS_ACTIVITIES = CONFIG.force_reprocess_activities
USER_TIMEZONE = CONFIG.user_timezone
IGNORE_ERRORS = CONFIG.ignore_errors

# Genuine mutable runtime state (an accumulator), not config -- stays here.
PARSED_ACTIVITY_ID_LIST = []

# %%
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# %%
# Client construction does no I/O (see influx_storage.py's module docstring),
# so this is safe at import time. Connectivity itself is only verified by an
# explicit INFLUXDB_STORAGE.check_connection() call in __main__ below -- not
# as an import-time side effect, which is what previously made this module
# impossible to import without a live, reachable InfluxDB.
INFLUXDB_STORAGE = InfluxStorage(CONFIG)

# %%
def iter_days(start_date: str, end_date: str):
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    current = end

    while current >= start:
        yield current.strftime('%Y-%m-%d')
        current -= timedelta(days=1)


# %%
def _is_http_status_error(err, status_code):
    """Best-effort status matching for wrapped Garmin errors in different module versions."""
    if hasattr(err, "response") and getattr(err.response, "status_code", None) == status_code:
        return True
    if hasattr(err, "status_code") and getattr(err, "status_code", None) == status_code:
        return True
    return re.search(rf"\b{status_code}\b", str(err)) is not None

# %%
def write_points_to_influxdb(points):
    try:
        if len(points) != 0:
            if TAG_MEASUREMENTS_WITH_USER_EMAIL:
                for item in points:
                    item['tags'].update({'User_ID': garmin_obj.display_name or 'Unknown'})
            INFLUXDB_STORAGE.write_points(points)
            logging.info("Success : updated influxDB database with new points")
    except (InfluxDBClientError, InfluxDBError) as err:
        logging.error("Write failed : Unable to connect with database! " + str(err))

# %%
def get_daily_stats(date_str):
    points_list = []
    stats_json = garmin_obj.get_stats(date_str)
    if stats_json['wellnessStartTimeGmt'] and datetime.strptime(date_str, "%Y-%m-%d") < datetime.today():
        points_list.append({
            "measurement":  "DailyStats",
            "time": pytz.timezone("UTC").localize(datetime.strptime(stats_json['wellnessStartTimeGmt'], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
            "tags": {
                "Device": GARMIN_DEVICENAME,
                "Database_Name": INFLUXDB_DATABASE
            },
            "fields": {
                "activeKilocalories": stats_json.get('activeKilocalories'),
                "bmrKilocalories": stats_json.get('bmrKilocalories'),

                'totalSteps': stats_json.get('totalSteps'),
                'totalDistanceMeters': stats_json.get('totalDistanceMeters'),

                "highlyActiveSeconds": stats_json.get("highlyActiveSeconds"),
                "activeSeconds": stats_json.get("activeSeconds"),
                "sedentarySeconds": stats_json.get("sedentarySeconds"),
                "sleepingSeconds": stats_json.get("sleepingSeconds"),
                "moderateIntensityMinutes": stats_json.get("moderateIntensityMinutes"),
                "vigorousIntensityMinutes": stats_json.get("vigorousIntensityMinutes"),

                "floorsAscendedInMeters": stats_json.get("floorsAscendedInMeters"),
                "floorsDescendedInMeters": stats_json.get("floorsDescendedInMeters"),
                "floorsAscended": stats_json.get("floorsAscended"),
                "floorsDescended": stats_json.get("floorsDescended"),

                "minHeartRate": stats_json.get("minHeartRate"),
                "maxHeartRate": stats_json.get("maxHeartRate"),
                "restingHeartRate": stats_json.get("restingHeartRate"),
                "minAvgHeartRate": stats_json.get("minAvgHeartRate"),
                "maxAvgHeartRate": stats_json.get("maxAvgHeartRate"),

                "avgSkinTempDeviationC": stats_json.get("avgSkinTempDeviationC"),
                "avgSkinTempDeviationF": stats_json.get("avgSkinTempDeviationF"),

                "stressDuration": stats_json.get("stressDuration"),
                "restStressDuration": stats_json.get("restStressDuration"),
                "activityStressDuration": stats_json.get("activityStressDuration"),
                "uncategorizedStressDuration": stats_json.get("uncategorizedStressDuration"),
                "totalStressDuration": stats_json.get("totalStressDuration"),
                "lowStressDuration": stats_json.get("lowStressDuration"),
                "mediumStressDuration": stats_json.get("mediumStressDuration"),
                "highStressDuration": stats_json.get("highStressDuration"),
                
                "stressPercentage": stats_json.get("stressPercentage"),
                "restStressPercentage": stats_json.get("restStressPercentage"),
                "activityStressPercentage": stats_json.get("activityStressPercentage"),
                "uncategorizedStressPercentage": stats_json.get("uncategorizedStressPercentage"),
                "lowStressPercentage": stats_json.get("lowStressPercentage"),
                "mediumStressPercentage": stats_json.get("mediumStressPercentage"),
                "highStressPercentage": stats_json.get("highStressPercentage"),
                
                "bodyBatteryChargedValue": stats_json.get("bodyBatteryChargedValue"),
                "bodyBatteryDrainedValue": stats_json.get("bodyBatteryDrainedValue"),
                "bodyBatteryHighestValue": stats_json.get("bodyBatteryHighestValue"),
                "bodyBatteryLowestValue": stats_json.get("bodyBatteryLowestValue"),
                "bodyBatteryDuringSleep": stats_json.get("bodyBatteryDuringSleep"),
                "bodyBatteryAtWakeTime": stats_json.get("bodyBatteryAtWakeTime"),
                
                "averageSpo2": stats_json.get("averageSpo2"),
                "lowestSpo2": stats_json.get("lowestSpo2"),
            }
        })
        if points_list:
            logging.info(f"Success : Fetching daily metrics for date {date_str}")
        return points_list
    else:
        logging.debug("No daily stat data available for the give date " + date_str)
        return []
    

# %%
def get_last_sync():
    global GARMIN_DEVICENAME
    global GARMIN_DEVICEID
    points_list = []
    sync_data = garmin_obj.get_device_last_used()
    if GARMIN_DEVICENAME_AUTOMATIC:
        GARMIN_DEVICENAME = sync_data.get('lastUsedDeviceName') or "Unknown"
        GARMIN_DEVICEID = sync_data.get('userDeviceId') or None
    points_list.append({
        "measurement":  "DeviceSync",
        "time": datetime.fromtimestamp(sync_data['lastUsedDeviceUploadTime']/1000, tz=pytz.timezone("UTC")).isoformat(),
        "tags": {
            "Device": GARMIN_DEVICENAME,
            "Database_Name": INFLUXDB_DATABASE
        },
        "fields": {
            "imageUrl": sync_data.get('imageUrl'),
            "Device_Name": GARMIN_DEVICENAME
        }
    })
    if points_list:
        logging.info(f"Success : Updated device last sync time")
    else:
        logging.warning("No associated/synced Garmin device found with your account")
    return points_list

# %%
def get_sleep_data(date_str):
    points_list = []
    all_sleep_data = garmin_obj.get_sleep_data(date_str)
    sleep_json = all_sleep_data.get("dailySleepDTO", None)
    if sleep_json["sleepEndTimestampGMT"]:
        points_list.append({
        "measurement":  "SleepSummary",
        "time": datetime.fromtimestamp(sleep_json["sleepEndTimestampGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
        "tags": {
            "Device": GARMIN_DEVICENAME,
            "Database_Name": INFLUXDB_DATABASE
            },
        "fields": {
            "sleepTimeSeconds": sleep_json.get("sleepTimeSeconds"),
            "deepSleepSeconds": sleep_json.get("deepSleepSeconds"),
            "lightSleepSeconds": sleep_json.get("lightSleepSeconds"),
            "remSleepSeconds": sleep_json.get("remSleepSeconds"),
            "awakeSleepSeconds": sleep_json.get("awakeSleepSeconds"),
            "averageSpO2Value": sleep_json.get("averageSpO2Value"),
            "lowestSpO2Value": sleep_json.get("lowestSpO2Value"),
            "highestSpO2Value": sleep_json.get("highestSpO2Value"),
            "averageRespirationValue": sleep_json.get("averageRespirationValue"),
            "lowestRespirationValue": sleep_json.get("lowestRespirationValue"),
            "highestRespirationValue": sleep_json.get("highestRespirationValue"),
            "awakeCount": sleep_json.get("awakeCount"),
            "avgSleepStress": sleep_json.get("avgSleepStress"),
            "sleepScore": ((sleep_json.get("sleepScores") or {}).get("overall") or {}).get("value"),
            "restlessMomentsCount": all_sleep_data.get("restlessMomentsCount"),
            "avgOvernightHrv": all_sleep_data.get("avgOvernightHrv"),
            "bodyBatteryChange": all_sleep_data.get("bodyBatteryChange"),
            "restingHeartRate": all_sleep_data.get("restingHeartRate"),
            "avgSkinTempDeviationC": all_sleep_data.get("avgSkinTempDeviationC"),
            "avgSkinTempDeviationF": all_sleep_data.get("avgSkinTempDeviationF")
            }
        })
    sleep_movement_intraday = all_sleep_data.get("sleepMovement")
    if sleep_movement_intraday:
        for entry in sleep_movement_intraday:
            points_list.append({
                "measurement":  "SleepIntraday",
                "time": pytz.timezone("UTC").localize(datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": {
                    "SleepMovementActivityLevel": entry.get("activityLevel",-1),
                    "SleepMovementActivitySeconds": int((datetime.strptime(entry["endGMT"], "%Y-%m-%dT%H:%M:%S.%f") - datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).total_seconds())
                }
            })
    sleep_levels_intraday = all_sleep_data.get("sleepLevels")
    if sleep_levels_intraday:
        for entry in sleep_levels_intraday:
            if entry.get("activityLevel") or entry.get("activityLevel") == 0: # Include 0 for Deepsleep but not None - Refer to issue #43
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "SleepStageLevel": entry.get("activityLevel"),
                        "SleepStageSeconds": int((datetime.strptime(entry["endGMT"], "%Y-%m-%dT%H:%M:%S.%f") - datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).total_seconds())
                    }
                })
        # Add additional duplicate terminal data point (see issue #127)
        if entry.get("endGMT"):
            points_list.append({
                "measurement":  "SleepIntraday",
                "time": pytz.timezone("UTC").localize(datetime.strptime(entry["endGMT"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": {"SleepStageLevel": entry.get("activityLevel")} # Duplicating last entry for visualization in Grafana
            })
    sleep_restlessness_intraday = all_sleep_data.get("sleepRestlessMoments")
    if sleep_restlessness_intraday:
        for entry in sleep_restlessness_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "sleepRestlessValue": entry.get("value")
                    }
                })
    sleep_spo2_intraday = all_sleep_data.get("wellnessEpochSPO2DataDTOList")
    if sleep_spo2_intraday:
        for entry in sleep_spo2_intraday:
            if entry.get("spo2Reading"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry["epochTimestamp"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "spo2Reading": entry.get("spo2Reading")
                    }
                })
    sleep_respiration_intraday = all_sleep_data.get("wellnessEpochRespirationDataDTOList")
    if sleep_respiration_intraday:
        for entry in sleep_respiration_intraday:
            if entry.get("respirationValue"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startTimeGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "respirationValue": entry.get("respirationValue")
                    }
                })
    sleep_heart_rate_intraday = all_sleep_data.get("sleepHeartRate")
    if sleep_heart_rate_intraday:
        for entry in sleep_heart_rate_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "heartRate": entry.get("value")
                    }
                })
    sleep_stress_intraday = all_sleep_data.get("sleepStress")
    if sleep_stress_intraday:
        for entry in sleep_stress_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "stressValue": entry.get("value")
                    }
                })
    sleep_bb_intraday = all_sleep_data.get("sleepBodyBattery")
    if sleep_bb_intraday:
        for entry in sleep_bb_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "bodyBattery": entry.get("value")
                    }
                })
    sleep_hrv_intraday = all_sleep_data.get("hrvData")
    if sleep_hrv_intraday:
        for entry in sleep_hrv_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "hrvData": entry.get("value")
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday sleep metrics for date {date_str}")
    return points_list

# %%
def get_intraday_hr(date_str):
    points_list = []
    hr_list = garmin_obj.get_heart_rates(date_str).get("heartRateValues") or []
    for entry in hr_list:
        if entry[1]:
            points_list.append({
                    "measurement":  "HeartRateIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "HeartRate": entry[1]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday Heart Rate for date {date_str}")
    return points_list

# %%
def get_intraday_steps(date_str):
    points_list = []
    steps_list = garmin_obj.get_steps_data(date_str)
    for entry in steps_list:
        if entry["steps"] or entry["steps"] == 0:
            points_list.append({
                    "measurement":  "StepsIntraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry['startGMT'], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "StepsCount": entry["steps"]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday steps for date {date_str}")
    return points_list

# %%
def get_intraday_stress(date_str):
    points_list = []
    stress_list = garmin_obj.get_stress_data(date_str).get('stressValuesArray') or []
    for entry in stress_list:
        if entry[1] or entry[1] == 0:
            points_list.append({
                    "measurement":  "StressIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "stressLevel": entry[1]
                    }
                })
    bb_list = garmin_obj.get_stress_data(date_str).get('bodyBatteryValuesArray') or []
    for entry in bb_list:
        if entry[2] or entry[2] == 0:
            points_list.append({
                    "measurement":  "BodyBatteryIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "BodyBatteryLevel": entry[2]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday stress and Body Battery values for date {date_str}")
    return points_list

# %%
def get_intraday_br(date_str):
    points_list = []
    br_list = garmin_obj.get_respiration_data(date_str).get('respirationValuesArray') or []
    for entry in br_list:
        if entry[1]:
            points_list.append({
                    "measurement":  "BreathingRateIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "BreathingRate": entry[1]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday Breathing Rate for date {date_str}")
    return points_list

# %%
def get_intraday_hrv(date_str):
    points_list = []
    hrv_list = (garmin_obj.get_hrv_data(date_str) or {}).get('hrvReadings') or []
    for entry in hrv_list:
        if entry.get('hrvValue'):
            points_list.append({
                    "measurement":  "HRV_Intraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry['readingTimeGMT'],"%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "hrvValue": entry.get('hrvValue')
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday HRV for date {date_str}")
    return points_list

# %%
def get_body_composition(date_str):
    points_list = []
    weight_list_all = garmin_obj.get_weigh_ins(date_str, date_str).get('dailyWeightSummaries', [])
    if weight_list_all:
        weight_list = weight_list_all[0].get('allWeightMetrics', [])
        for weight_dict in weight_list:
            data_fields = {
                    "weight": weight_dict.get("weight"),
                    "bmi": weight_dict.get("bmi"),
                    "bodyFat": weight_dict.get("bodyFat"),
                    "bodyWater": weight_dict.get("bodyWater"),
                    "boneMass": weight_dict.get("boneMass"),
                    "muscleMass": weight_dict.get("muscleMass"),
                    "physiqueRating": weight_dict.get("physiqueRating"),
                    "visceralFat": weight_dict.get("visceralFat"),
                    # "metabolicAge": datetime.fromtimestamp(int(weight_dict.get("metabolicAge")/1000), tz=pytz.timezone("UTC")).isoformat() if weight_dict.get("metabolicAge") else None
                }
            if not all(value is None for value in data_fields.values()):
                points_list.append({
                    "measurement":  "BodyComposition",
                    "time": datetime.fromtimestamp((weight_dict['timestampGMT']/1000) , tz=pytz.timezone("UTC")).isoformat() if weight_dict['timestampGMT'] else datetime.strptime(date_str, "%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 is timestamp is not available (issue #15)
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE,
                        "Frequency" : "Intraday",
                        "SourceType" : weight_dict.get('sourceType', "Unknown")
                    },
                    "fields": data_fields
                })
        logging.info(f"Success : Fetching intraday Body Composition (Weight, BMI etc) for date {date_str}")
    return points_list

# %%
def get_activity_summary(date_str):
    points_list = []
    activity_with_gps_id_dict = {}
    strength_activity_id_dict = {}
    activity_list = garmin_obj.get_activities_by_date(date_str, date_str)
    if ACTIVITY_TYPE_FILTER:
        activity_list = [a for a in activity_list if (a.get('activityType') or {}).get('typeKey', 'Unknown').lower() in ACTIVITY_TYPE_FILTER]
        logging.info(f"ACTIVITY_TYPE_FILTER active: kept {len(activity_list)} activities matching {ACTIVITY_TYPE_FILTER}")
    for activity in activity_list:
        activity_type_key = (activity.get('activityType') or {}).get('typeKey', "Unknown")
        if activity.get('hasPolyline') or ALWAYS_PROCESS_FIT_FILES: # will process FIT files lacking GPS data if ALWAYS_PROCESS_FIT_FILES is set to True
            if not activity.get('hasPolyline'):
                logging.warning(f"Activity ID {activity.get('activityId')} got no GPS data - yet, activity FIT file data will be processed as ALWAYS_PROCESS_FIT_FILES is on")
            activity_with_gps_id_dict[activity.get('activityId')] = activity_type_key
        # Collect strength training activities for API-based exercise set fetching
        if 'strength' in activity_type_key.lower() and activity.get('startTimeGMT'):
            strength_activity_id_dict[activity.get('activityId')] = {
                'typeKey': activity_type_key,
                'startTimeGMT': activity.get('startTimeGMT'),
                'activityName': activity.get('activityName'),
            }
        if "startTimeGMT" in activity: # "startTimeGMT" should be available for all activities (fix #13)
            activity_id = activity.get('activityId')
            hr_zones_data = garmin_obj.get_activity_hr_in_timezones(activity_id)
            hr_zone_boundaries = [None] * 5
            if hr_zones_data:
                for zone in hr_zones_data:
                    hr_zone_boundaries[int(zone.get('zoneNumber')) - 1] = zone.get('zoneLowBoundary')
            else:
                logging.warning(f"No HR zone data found for activity: {activity_id}")

            points_list.append({
                "measurement":  "ActivitySummary",
                "time": datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE,
                    "ActivityID": activity.get('activityId'),
                    "ActivitySelector": datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).strftime('%Y%m%dT%H%M%SUTC-') + (activity.get('activityType') or {}).get('typeKey', "Unknown")
                },
                "fields": {
                    "Activity_ID": activity_id,
                    'Device_ID': activity.get('deviceId'),
                    'activityName': activity.get('activityName'),
                    'description': activity.get('description'),
                    'activityType': (activity.get('activityType') or {}).get('typeKey',None),
                    'distance': activity.get('distance'),
                    'elevationGain': activity.get('elevationGain'),
                    'elevationLoss': activity.get('elevationLoss'),
                    'elapsedDuration': activity.get('elapsedDuration') if activity.get('elapsedDuration') else activity.get('duration'),
                    'movingDuration': activity.get('movingDuration'),
                    'averageSpeed': activity.get('averageSpeed'),
                    'maxSpeed': activity.get('maxSpeed'),
                    'calories': activity.get('calories'),
                    'bmrCalories': activity.get('bmrCalories'),
                    'averageHR': activity.get('averageHR'),
                    'maxHR': activity.get('maxHR'),
                    'vO2MaxValue': activity.get('vO2MaxValue'),
                    'locationName': activity.get('locationName'),
                    'lapCount': activity.get('lapCount'),
                    'hrTimeInZone_1': int(val) if (val := activity.get('hrTimeInZone_1')) is not None else None,
                    'hrTimeInZone_2': int(val) if (val := activity.get('hrTimeInZone_2')) is not None else None,
                    'hrTimeInZone_3': int(val) if (val := activity.get('hrTimeInZone_3')) is not None else None,
                    'hrTimeInZone_4': int(val) if (val := activity.get('hrTimeInZone_4')) is not None else None,
                    'hrTimeInZone_5': int(val) if (val := activity.get('hrTimeInZone_5')) is not None else None,
                    'hrZoneLowBoundary_1': hr_zone_boundaries[0],
                    'hrZoneLowBoundary_2': hr_zone_boundaries[1],
                    'hrZoneLowBoundary_3': hr_zone_boundaries[2],
                    'hrZoneLowBoundary_4': hr_zone_boundaries[3],
                    'hrZoneLowBoundary_5': hr_zone_boundaries[4],
                    'aerobicTrainingEffect': activity.get('aerobicTrainingEffect'),
                    'anaerobicTrainingEffect': activity.get('anaerobicTrainingEffect'),
                    'activityTrainingLoad': activity.get('activityTrainingLoad'),
                    'moderateIntensityMinutes': activity.get('moderateIntensityMinutes'),
                    'vigorousIntensityMinutes': activity.get('vigorousIntensityMinutes'),
                }
            })
            points_list.append({
                "measurement":  "ActivitySummary",
                "time": (datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC) + timedelta(seconds=int(activity.get('elapsedDuration', activity.get('duration', 0))))).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE,
                    "ActivityID": activity.get('activityId'),
                    "ActivitySelector": datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).strftime('%Y%m%dT%H%M%SUTC-') + (activity.get('activityType') or {}).get('typeKey', "Unknown")
                },
                "fields": {
                    "Activity_ID": activity.get('activityId'),
                    'Device_ID': activity.get('deviceId'),
                    'activityName': "END",
                    'activityType': "No Activity",
                }
            })
            logging.info(f"Success : Fetching Activity summary with id {activity.get('activityId')} for date {date_str}")
        else:
            logging.warning(f"Skipped : Start Timestamp missing for activity id {activity.get('activityId')} for date {date_str}")
    return points_list, activity_with_gps_id_dict, strength_activity_id_dict

# %%
def purge_existing_strength_exercise_sets(activity_id):
    """Delete stale strength rows before rewriting the current Garmin snapshot.

    Edited Garmin exercises can change exercise tags. Without removing the
    previous series first, InfluxDB keeps the stale and corrected rows in
    parallel because the tags no longer match.
    """
    if INFLUXDB_VERSION != '1':
        logging.warning(
            f"InfluxDB version {INFLUXDB_VERSION} does not support purging StrengthExerciseSet series for activity {activity_id}. "
            "Applying the default refresh behavior; edited exercises may produce duplicated rows."
        )
        return True

    try:
        INFLUXDB_STORAGE.delete_series(
            measurement='StrengthExerciseSet',
            tags={'ActivityID': str(activity_id)},
        )
        logging.info(f"Purged existing StrengthExerciseSet series for activity {activity_id}")
        return True
    except (InfluxDBClientError, InfluxDBError) as err:
        logging.warning(
            f"Failed to purge existing StrengthExerciseSet series for activity {activity_id}: {err}"
        )
        return False


# %%
def get_strength_training_data(strength_activity_id_dict):
    """Fetch strength training exercise sets and HR zones from Garmin Connect API.
    Uses API data (not FIT files) to get corrected exercise names and details.
    See: https://github.com/arpanghosh8453/garmin-grafana/issues/189
    """
    points_list = []
    for activity_id, activity_info in strength_activity_id_dict.items():
        activity_type = activity_info['typeKey']
        start_time_str = activity_info['startTimeGMT']
        activity_start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC)
        activity_selector = activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
        activity_name = activity_info.get('activityName', activity_type)

        exercise_set_points = None
        try:
            exercise_sets_data = garmin_obj.get_activity_exercise_sets(activity_id)
            exercises = exercise_sets_data.get('exerciseSets', []) or []
            exercise_set_points = []
            set_counter = 0
            for exercise in exercises:
                set_type = exercise.get('setType', '')
                if set_type == 'REST':
                    continue
                set_counter += 1
                exercise_info = (exercise.get('exercises') or [{}])[0]
                category = exercise_info.get('category', 'UNKNOWN')
                exercise_name = exercise_info.get('name', '')
                exercise_label = f"{category}/{exercise_name}" if exercise_name else category
                weight_g = float(exercise.get('weight', 0) or 0)
                weight_kg = weight_g / 1000.0
                duration_s = float(exercise.get('duration', 0) or 0)
                start_ts = exercise.get('startTime')
                if start_ts:
                    set_time = datetime.strptime(start_ts.split('.')[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.UTC).isoformat()
                else:
                    set_time = (activity_start_time + timedelta(seconds=set_counter)).isoformat()

                data_fields = {
                    "Activity_ID": activity_id,
                    "ActivityName": activity_name,
                    "SetOrder": int(exercise.get('setOrder', set_counter)),
                    "SetType": set_type,
                    "Reps": int(exercise.get('repetitionCount', 0)),
                    "Weight_kg": weight_kg,
                    "Duration_s": duration_s,
                }
                exercise_set_points.append({
                    "measurement": "StrengthExerciseSet",
                    "time": set_time,
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE,
                        "ActivityID": activity_id,
                        "ActivitySelector": activity_selector,
                        "ExerciseCategory": category,
                        "ExerciseLabel": exercise_label,
                    },
                    "fields": data_fields
                })
            logging.info(f"Success : Fetching {set_counter} strength exercise sets for activity {activity_id}")
        except Exception as err:
            logging.warning(f"Failed to fetch exercise sets for activity {activity_id}: {err}")

        if exercise_set_points is not None:
            if purge_existing_strength_exercise_sets(activity_id):
                points_list.extend(exercise_set_points)
            else:
                logging.warning(
                    f"Skipped : StrengthExerciseSet refresh for activity {activity_id} because stale rows could not be purged"
                )

        try:
            hr_zones_data = garmin_obj.get_activity_hr_in_timezones(activity_id)
            for zone_info in hr_zones_data:
                zone_number = zone_info.get('zoneNumber', zone_info.get('zone'))
                if zone_number is None:
                    continue
                data_fields = {
                    "Activity_ID": activity_id,
                    "ActivityName": activity_name,
                    "ZoneNumber": int(zone_number),
                    "SecsInZone": zone_info.get('secsInZone'),
                    "ZoneLowBoundary": zone_info.get('zoneLowBoundary'),
                }
                points_list.append({
                    "measurement": "StrengthHRZones",
                    "time": (activity_start_time + timedelta(milliseconds=int(zone_number))).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE,
                        "ActivityID": activity_id,
                        "ActivitySelector": activity_selector,
                    },
                    "fields": data_fields
                })
            logging.info(f"Success : Fetching strength HR zones for activity {activity_id}")
        except Exception as err:
            logging.warning(f"Failed to fetch HR zones for activity {activity_id}: {err}")

    return points_list

# %%
def _build_cycling_dynamics_point(all_records_list, all_sessions_list, activityID, activity_type, activity_start_time):
    def avg_nonzero(records, key):
        vals = [r[key] for r in records if r.get(key) not in (None, 0)]
        return sum(vals) / len(vals) if vals else None

    def session_phase_component(session, key, index):
        """Extract one angle from a power phase tuple field; skip None/0 entries."""
        v = session.get(key)
        if v is None:
            return None
        try:
            item = v[index] if hasattr(v, '__getitem__') else v
            return float(item) if item not in (None, 0) else None
        except (IndexError, TypeError):
            return None

    def record_phase_avg(records, key, index):
        """Average one component of a per-record power phase tuple field."""
        vals = []
        for r in records:
            v = r.get(key)
            if v is None:
                continue
            try:
                item = v[index] if hasattr(v, '__getitem__') else v
                if item not in (None, 0):
                    vals.append(item)
            except (IndexError, TypeError):
                pass
        return sum(vals) / len(vals) if vals else None

    fields = {}

    # --- Session-level pre-computed averages (primary source) ---
    if all_sessions_list:
        session = all_sessions_list[0]

        # Scalar fields — ANT+ standard
        for src, dst in [
            ('avg_left_torque_effectiveness',  'avg_left_torque_effectiveness'),
            ('avg_right_torque_effectiveness', 'avg_right_torque_effectiveness'),
            ('avg_left_pedal_smoothness',      'avg_left_pedal_smoothness'),
            ('avg_right_pedal_smoothness',     'avg_right_pedal_smoothness'),
            ('avg_left_pco',                   'avg_left_pco'),
            ('avg_right_pco',                  'avg_right_pco'),
        ]:
            v = session.get(src)
            if v is not None:
                fields[dst] = float(v)

        # Power phase tuples — Garmin Vector/Rally exclusive
        # fitparse returns avg_left_power_phase as (start, end, ...) in degrees
        for field_key, idx, dst in [
            ('avg_left_power_phase',       0, 'avg_left_power_phase_start'),
            ('avg_left_power_phase',       1, 'avg_left_power_phase_end'),
            ('avg_right_power_phase',      0, 'avg_right_power_phase_start'),
            ('avg_right_power_phase',      1, 'avg_right_power_phase_end'),
            ('avg_left_power_phase_peak',  0, 'avg_left_power_phase_peak_start'),
            ('avg_left_power_phase_peak',  1, 'avg_left_power_phase_peak_end'),
            ('avg_right_power_phase_peak', 0, 'avg_right_power_phase_peak_start'),
            ('avg_right_power_phase_peak', 1, 'avg_right_power_phase_peak_end'),
        ]:
            v = session_phase_component(session, field_key, idx)
            if v is not None:
                fields[dst] = v

        # Power summary fields
        for src, dst in [
            ('normalized_power',      'normalized_power'),
            ('training_stress_score', 'training_stress_score'),
            ('intensity_factor',      'intensity_factor'),
        ]:
            v = session.get(src)
            if v is not None:
                fields[dst] = float(v)

        # left_right_balance: FIT uint16 bitmask — bit15 set means right% is known,
        # lower 15 bits / 100 = right power percentage; we store left% for readability.
        lrb = session.get('left_right_balance')
        if lrb is not None:
            try:
                raw = int(lrb)
                if raw & 0x8000:
                    fields['left_right_balance'] = round(100.0 - (raw & 0x7FFF) / 100.0, 2)
                elif raw > 0:
                    fields['left_right_balance'] = float(raw)
            except (ValueError, TypeError):
                pass

    # --- Per-record fallback (for devices that store dynamics in record messages) ---
    for src, dst in [
        ('left_torque_effectiveness',  'avg_left_torque_effectiveness'),
        ('right_torque_effectiveness', 'avg_right_torque_effectiveness'),
        ('left_pedal_smoothness',      'avg_left_pedal_smoothness'),
        ('right_pedal_smoothness',     'avg_right_pedal_smoothness'),
        ('left_pco',                   'avg_left_pco'),
        ('right_pco',                  'avg_right_pco'),
    ]:
        if dst not in fields:
            v = avg_nonzero(all_records_list, src)
            if v is not None:
                fields[dst] = v

    for field_key, idx, dst in [
        ('left_power_phase',       0, 'avg_left_power_phase_start'),
        ('left_power_phase',       1, 'avg_left_power_phase_end'),
        ('right_power_phase',      0, 'avg_right_power_phase_start'),
        ('right_power_phase',      1, 'avg_right_power_phase_end'),
        ('left_power_phase_peak',  0, 'avg_left_power_phase_peak_start'),
        ('left_power_phase_peak',  1, 'avg_left_power_phase_peak_end'),
        ('right_power_phase_peak', 0, 'avg_right_power_phase_peak_start'),
        ('right_power_phase_peak', 1, 'avg_right_power_phase_peak_end'),
    ]:
        if dst not in fields:
            v = record_phase_avg(all_records_list, field_key, idx)
            if v is not None:
                fields[dst] = v

    # Guard: write nothing if no cycling dynamics data was found
    if not fields:
        return None

    fields['ActivityName'] = activity_type
    fields['Activity_ID'] = activityID

    return {
        "measurement": "CyclingDynamics",
        "time": activity_start_time.isoformat(),
        "tags": {
            "Device": GARMIN_DEVICENAME,
            "Database_Name": INFLUXDB_DATABASE,
            "ActivityID": activityID,
            "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
        },
        "fields": fields
    }

# %%
def fetch_activity_GPS(activityIDdict): # Uses FIT file by default, falls back to TCX
    points_list = []
    for activityID in activityIDdict.keys():
        activity_type = activityIDdict[activityID]
        if (activityID in PARSED_ACTIVITY_ID_LIST) and (not FORCE_REPROCESS_ACTIVITIES):
            logging.info(f"Skipping : Activity ID {activityID} has already been processed within current runtime")
            return []
        if (activityID in PARSED_ACTIVITY_ID_LIST) and (FORCE_REPROCESS_ACTIVITIES):
            logging.info(f"Re-processing : Activity ID {activityID} (FORCE_REPROCESS_ACTIVITIES is on)")
        try:
            zip_data = garmin_obj.download_activity(activityID, dl_fmt=garmin_obj.ActivityDownloadFormat.ORIGINAL)
            logging.info(f"Processing : Activity ID {activityID} FIT file data - this may take a while...")
            zip_buffer = io.BytesIO(zip_data)
            with zipfile.ZipFile(zip_buffer) as zip_ref:
                fit_filename = next((f for f in zip_ref.namelist() if f.endswith('.fit')), None)
                if not fit_filename:
                    raise FileNotFoundError(f"No FIT file found in the downloaded zip archive for Activity ID {activityID}")
                else:
                    fit_data = zip_ref.read(fit_filename)
                    fit_file_buffer = io.BytesIO(fit_data)
                    fitfile = FitFile(fit_file_buffer)
                    fitfile.parse()
                    all_records_list = [record.get_values() for record in fitfile.get_messages('record')]
                    all_sessions_list = [record.get_values() for record in fitfile.get_messages('session')]
                    all_lengths_list = [record.get_values() for record in fitfile.get_messages('length')]
                    all_laps_list = [record.get_values() for record in fitfile.get_messages('lap')]
                    if len(all_records_list) == 0:
                        raise FileNotFoundError(f"No records found in FIT file for Activity ID {activityID} - Discarding FIT file")
                    else:
                        activity_start_time = all_records_list[0]['timestamp'].replace(tzinfo=pytz.UTC)
                    for parsed_record in all_records_list:
                        if parsed_record.get('timestamp'):
                            point = {
                                "measurement": "ActivityGPS",
                                "time": parsed_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Latitude": int(parsed_record['position_lat']) * ( 180 / 2**31 ) if parsed_record.get('position_lat') else None,
                                    "Longitude": int(parsed_record['position_long']) * ( 180 / 2**31 ) if parsed_record.get('position_long') else None,
                                    "Altitude": parsed_record.get('enhanced_altitude', None) or parsed_record.get('altitude', None),
                                    "Distance": parsed_record.get('distance', None),
                                    "DurationSeconds": (parsed_record['timestamp'].replace(tzinfo=pytz.UTC) - activity_start_time).total_seconds(),
                                    "HeartRate": float(parsed_record.get('heart_rate', None)) if parsed_record.get('heart_rate', None) else None,
                                    "Speed": parsed_record.get('enhanced_speed', None) or parsed_record.get('speed', None),
                                    "GradeAdjustedSpeed": (parsed_record.get("unknown_140") / 1000.0) if parsed_record.get("unknown_140") else None,
                                    "RunningEfficiency": ((parsed_record.get("unknown_140") / 1000.0)/parsed_record.get('heart_rate')) if (parsed_record.get("unknown_140") and parsed_record.get('heart_rate')) else None,
                                    "Cadence": parsed_record.get('cadence', None),
                                    "Fractional_Cadence": parsed_record.get('fractional_cadence', None),
                                    "Temperature": parsed_record.get('temperature', None),
                                    "Accumulated_Power": parsed_record.get('accumulated_power', None),
                                    "Power": parsed_record.get('power', None),
                                    "Vertical_Oscillation": parsed_record.get('vertical_oscillation', None),
                                    "Stance_Time": parsed_record.get('stance_time', None),
                                    "Vertical_Ratio": parsed_record.get('vertical_ratio', None),
                                    "Step_Length": parsed_record.get('step_length', None)
                                }
                            }
                            points_list.append(point)
                    for session_record in all_sessions_list:
                        if session_record.get('start_time') or session_record.get('timestamp'):
                            point = {
                                "measurement": "ActivitySession",
                                "time": session_record['start_time'].replace(tzinfo=pytz.UTC).isoformat() or session_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "Index": (int(v) if str(v := session_record.get('message_index', -1)).isdigit() else -1) + 1,
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Sport": str(session_record.get('sport', None)), # Avoid partial write error 400 see #152#issuecomment-3084539416
                                    "Sub_Sport": str(session_record.get('sub_sport', None)),
                                    "Pool_Length": session_record.get('pool_length', None),
                                    "Pool_Length_Unit": session_record.get('pool_length_unit', None),
                                    "Lengths": session_record.get('num_laps', None),
                                    "Laps": session_record.get('num_lengths', None),
                                    "Aerobic_Training": session_record.get('total_training_effect', None),
                                    "Anaerobic_Training": session_record.get('total_anaerobic_training_effect', None),
                                    "Primary_Benefit": session_record.get('primary_benefit', None),
                                    "Recovery_Time": session_record.get('recovery_time', None)
                                }
                            }
                            points_list.append(point)
                    for length_record in all_lengths_list:
                        if length_record.get('start_time') or length_record.get('timestamp'):
                            point = {
                                "measurement": "ActivityLength",
                                "time": length_record['start_time'].replace(tzinfo=pytz.UTC).isoformat() or length_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "Index": int(length_record.get('message_index', -1)) + 1,
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Elapsed_Time": length_record.get('total_elapsed_time', None),
                                    "Strokes": length_record.get('total_strokes', None),
                                    "Swim_Stroke": length_record.get('swim_stroke', None),
                                    "Avg_Speed": length_record.get('avg_speed', None),
                                    "Calories": length_record.get('total_calories', None),
                                    "Avg_Cadence": length_record.get('avg_swimming_cadence', None)
                                }
                            }
                            points_list.append(point)
                    for lap_record in all_laps_list:
                        if lap_record.get('start_time') or lap_record.get('timestamp'):
                            point = {
                                "measurement": "ActivityLap",
                                "time": lap_record['start_time'].replace(tzinfo=pytz.UTC).isoformat() or lap_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "Index": int(lap_record.get('message_index', -1)) + 1,
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Elapsed_Time": lap_record.get('total_elapsed_time', None),
                                    "Sport": str(lap_record.get('sport', None)),
                                    "Lengths": lap_record.get('num_lengths', None),
                                    "Length_Index": lap_record.get('first_length_index', None),
                                    "Distance": lap_record.get('total_distance', None),
                                    "Ascent": lap_record.get('total_ascent', None),
                                    "Descent": lap_record.get('total_descent', None),
                                    "Cycles": lap_record.get('total_cycles', None),
                                    "Avg_Stroke_Distance": lap_record.get('avg_stroke_distance', None),
                                    "Moving_Duration": lap_record.get('total_moving_time', None),
                                    "Standing_Duration": lap_record.get('time_standing', None),
                                    "Avg_Speed": lap_record.get('enhanced_avg_speed', None),
                                    "Max_Speed": lap_record.get('enhanced_max_speed', None),
                                    "Calories": lap_record.get('total_calories', None),
                                    "Avg_Power": lap_record.get('avg_power', None),
                                    "Avg_HR": lap_record.get('avg_heart_rate', None),
                                    "Max_HR": lap_record.get('max_heart_rate', None),
                                    "Avg_Cadence": lap_record.get('avg_cadence', None),
                                    "Avg_Temperature": lap_record.get('avg_temperature', None),
                                    "Avg_Vertical_Oscillation": lap_record.get('avg_vertical_oscillation', None),
                                    "Avg_Stance_Time": lap_record.get('avg_stance_time', None),
                                    "Avg_Vertical_Ratio": lap_record.get('avg_vertical_ratio', None),
                                    "Avg_Step_Length": lap_record.get('avg_step_length', None)
                                }
                            }
                            points_list.append(point)
                    # Extract cycling dynamics and advanced power metrics
                    if 'cycling_dynamics' in FETCH_SELECTION:
                        cycling_point = _build_cycling_dynamics_point(
                            all_records_list, all_sessions_list,
                            activityID, activity_type, activity_start_time
                        )
                        if cycling_point:
                            points_list.append(cycling_point)
                            logging.info(f"Activity ID {activityID}: CyclingDynamics point added ({len(cycling_point['fields']) - 2} metrics)")

                    if KEEP_FIT_FILES:
                        os.makedirs(FIT_FILE_STORAGE_LOCATION, exist_ok=True)
                        fit_path = os.path.join(FIT_FILE_STORAGE_LOCATION, activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type + ".fit")
                        with open(fit_path, "wb") as f:
                            f.write(fit_data)
                        logging.info(f"Success : Activity ID {activityID} stored in output file {fit_path}")
        except (FileNotFoundError, FitParseError) as err:
            logging.error(err)
            logging.warning(f"Fallback : Failed to use FIT file for activityID {activityID} - Trying TCX file...")
            
            ns = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2", "ns3": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"}
            try:
                tcx_file_data = garmin_obj.download_activity(activityID, dl_fmt=garmin_obj.ActivityDownloadFormat.TCX).decode("UTF-8")
                root = ET.fromstring(tcx_file_data)
                if KEEP_FIT_FILES:
                    os.makedirs(FIT_FILE_STORAGE_LOCATION, exist_ok=True)
                    activity_start_time = datetime.fromisoformat(root.findall("tcx:Activities/tcx:Activity", ns)[0].find("tcx:Id", ns).text.strip("Z"))
                    tcx_path = os.path.join(FIT_FILE_STORAGE_LOCATION, activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type + ".tcx")
                    with open(tcx_path, "w") as f:
                        f.write(tcx_file_data)
                    logging.info(f"Success : Activity ID {activityID} stored in output file {tcx_path}")
            except requests.exceptions.Timeout as err:
                logging.warning(f"Request timeout for fetching large activity record {activityID} - skipping record")
                return []
            except Exception as err:
                logging.exception(f"Unable to fetch TCX for activity record {activityID} : skipping record")
                return []

            for activity in root.findall("tcx:Activities/tcx:Activity", ns):
                activity_start_time = datetime.fromisoformat(activity.find("tcx:Id", ns).text.strip("Z"))
                lap_index = 1
                for lap in activity.findall("tcx:Lap", ns):
                    lap_start_time = datetime.fromisoformat(lap.attrib.get("StartTime").strip("Z"))
                    for tp in lap.findall(".//tcx:Trackpoint", ns):
                        time_obj = datetime.fromisoformat(tp.findtext("tcx:Time", default=None, namespaces=ns).strip("Z"))
                        lat = tp.findtext("tcx:Position/tcx:LatitudeDegrees", default=None, namespaces=ns)
                        lon = tp.findtext("tcx:Position/tcx:LongitudeDegrees", default=None, namespaces=ns)
                        alt = tp.findtext("tcx:AltitudeMeters", default=None, namespaces=ns)
                        dist = tp.findtext("tcx:DistanceMeters", default=None, namespaces=ns)
                        hr = tp.findtext("tcx:HeartRateBpm/tcx:Value", default=None, namespaces=ns)
                        speed = tp.findtext("tcx:Extensions/ns3:TPX/ns3:Speed", default=None, namespaces=ns)

                        try: lat = float(lat)
                        except: lat = None
                        try: lon = float(lon)
                        except: lon = None
                        try: alt = float(alt)
                        except: alt = None
                        try: dist = float(dist)
                        except: dist = None
                        try: hr = float(hr)
                        except: hr = None
                        try: speed = float(speed)
                        except: speed = None

                        point = {
                            "measurement": "ActivityGPS",
                            "time": time_obj.isoformat(), 
                            "tags": {
                                "Device": GARMIN_DEVICENAME,
                                "Database_Name": INFLUXDB_DATABASE,
                                "ActivityID": activityID,
                                "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                            },
                            "fields": {
                                "ActivityName": activity_type,
                                "Activity_ID": activityID,
                                "Latitude": lat,
                                "Longitude": lon,
                                "Altitude": alt,
                                "Distance": dist,
                                "DurationSeconds": (time_obj - activity_start_time).total_seconds(),
                                "HeartRate": hr,
                                "Speed": speed,
                                "lap": lap_index
                            }
                        }
                        points_list.append(point)
                    
                    lap_index += 1
        logging.info(f"Success : Fetching detailed activity for Activity ID {activityID}")
        PARSED_ACTIVITY_ID_LIST.append(activityID)
    return points_list

def get_lactate_threshold(date_str):
    points_list = []
    endpoints = {}
    
    for ltsport in LACTATE_THRESHOLD_SPORTS:
        endpoints[f"SpeedThreshold_{ltsport}"] = f"/biometric-service/stats/lactateThresholdSpeed/range/{date_str}/{date_str}?aggregation=daily&sport={ltsport}"
        endpoints[f"HeartRateThreshold_{ltsport}"] = f"/biometric-service/stats/lactateThresholdHeartRate/range/{date_str}/{date_str}?aggregation=daily&sport={ltsport}"

    for label, endpoint in endpoints.items():
        lt_list_all = garmin_obj.connectapi(endpoint)
        if lt_list_all:
            for lt_dict in lt_list_all:
                value = lt_dict.get("value")
                if value is not None:
                    points_list.append({
                        "measurement": "LactateThreshold",
                        "time": datetime.fromtimestamp(datetime.strptime(date_str, "%Y-%m-%d").timestamp(), tz=pytz.timezone("UTC")).isoformat(),
                        "tags": {
                            "Device": GARMIN_DEVICENAME,
                            "Database_Name": INFLUXDB_DATABASE
                        },
                        "fields": {f"{label}": value}
                    })
                    logging.info(f"Success : Fetching {label} for date {date_str}")

    return points_list
    
def get_training_status(date_str):
    points_list = []
    ts_list_all = garmin_obj.get_training_status(date_str)
    ts_training_data_all = (ts_list_all.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData", {})

    if ts_training_data_all:
        for device_id, ts_dict in ts_training_data_all.items():
            logging.info(f"Success : Processing Training Status for Device {device_id}")
            data_fields = {
                "trainingStatus": ts_dict.get("trainingStatus"),
                "trainingStatusFeedbackPhrase": ts_dict.get("trainingStatusFeedbackPhrase"),
                "weeklyTrainingLoad": ts_dict.get("weeklyTrainingLoad"),
                "fitnessTrend": ts_dict.get("fitnessTrend"),
                "acwrPercent": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("acwrPercent"),
                "dailyTrainingLoadAcute": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyTrainingLoadAcute"),
                "dailyTrainingLoadChronic": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyTrainingLoadChronic"),
                "maxTrainingLoadChronic": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("maxTrainingLoadChronic"),
                "minTrainingLoadChronic": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("minTrainingLoadChronic"),
                "dailyAcuteChronicWorkloadRatio": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyAcuteChronicWorkloadRatio"),
            }
            if ts_dict.get("timestamp") and any(value is not None for value in data_fields.values()):
                points_list.append({
                    "measurement": "TrainingStatus",
                    "time": datetime.fromtimestamp(ts_dict["timestamp"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": data_fields
                })
                logging.info(f"Success : Fetching Training Status for date {date_str}")
    return points_list

# Contribution from PR #17 by @arturgoms 
def get_training_readiness(date_str):
    points_list = []
    tr_list_all = garmin_obj.get_training_readiness(date_str)
    if tr_list_all:
        for tr_dict in tr_list_all:
            data_fields = {
                    "level": tr_dict.get("level"),
                    "score": tr_dict.get("score"),
                    "sleepScore": tr_dict.get("sleepScore"),
                    "sleepScoreFactorPercent": tr_dict.get("sleepScoreFactorPercent"),
                    "recoveryTime": tr_dict.get("recoveryTime"),
                    "recoveryTimeFactorPercent": tr_dict.get("recoveryTimeFactorPercent"),
                    "acwrFactorPercent": tr_dict.get("acwrFactorPercent"),
                    "acuteLoad": tr_dict.get("acuteLoad"),
                    "stressHistoryFactorPercent": tr_dict.get("stressHistoryFactorPercent"),
                    "hrvFactorPercent": tr_dict.get("hrvFactorPercent"),
                }
            if (not all(value is None for value in data_fields.values())) and tr_dict.get('timestamp'):
                points_list.append({
                    "measurement":  "TrainingReadiness",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(tr_dict['timestamp'],"%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": data_fields
                })
                logging.info(f"Success : Fetching Training Readiness for date {date_str}")
    return points_list

# Contribution from PR #17 by @arturgoms 
def get_hillscore(date_str):
    points_list = []
    hill = garmin_obj.get_hill_score(date_str)
    if hill:
        data_fields = {
            "strengthScore": hill.get("strengthScore"),
            "enduranceScore": hill.get("enduranceScore"),
            "hillScoreClassificationId": hill.get("hillScoreClassificationId"),
            "overallScore": hill.get("overallScore"),
            "hillScoreFeedbackPhraseId": hill.get("hillScoreFeedbackPhraseId"),
            "vo2MaxPreciseValue": hill.get("vo2MaxPreciseValue")
        }
        if not all(value is None for value in data_fields.values()):
            points_list.append({
                "measurement":  "HillScore",
                "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": data_fields
            })
            logging.info(f"Success : Fetching Hill Score for date {date_str}")
    return points_list

# Contribution from PR #17 by @arturgoms 
def get_race_predictions(date_str):
    points_list = []
    rp_all_list = garmin_obj.get_race_predictions(startdate=date_str, enddate=date_str, _type="daily")
    rp_all = rp_all_list[0] if len(rp_all_list) > 0 else {}
    if rp_all:
        data_fields = {
            "time5K": rp_all.get("time5K"),
            "time10K": rp_all.get("time10K"),
            "timeHalfMarathon": rp_all.get("timeHalfMarathon"),
            "timeMarathon": rp_all.get("timeMarathon"),
        }
        if not all(value is None for value in data_fields.values()):
            points_list.append({
                "measurement":  "RacePredictions",
                "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": data_fields
            })
            logging.info(f"Success : Fetching Race Predictions for date {date_str}")
    return points_list

def get_fitness_age(date_str):
    points_list = []
    fitness_age = garmin_obj.get_fitnessage_data(date_str)

    if fitness_age:
            data_fields = {
                "chronologicalAge": float(fitness_age.get("chronologicalAge")) if fitness_age.get("chronologicalAge") else None,
                "fitnessAge": fitness_age.get("fitnessAge"),
                "achievableFitnessAge": fitness_age.get("achievableFitnessAge"),
            }

            if not all(value is None for value in data_fields.values()):
                points_list.append({
                    "measurement": "FitnessAge",
                    "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": data_fields
                })
                logging.info(f"Success : Fetching Fitness Age for date {date_str}")
    return points_list

def get_vo2_max(date_str):
    points_list = []
    max_metrics = garmin_obj.get_max_metrics(date_str)
    try:
        if max_metrics:
            vo2_max_value = (max_metrics[0].get("generic") or {}).get("vo2MaxPreciseValue", None)
            vo2_max_value_cycling = (max_metrics[0].get("cycling") or {}).get("vo2MaxPreciseValue", None)
            if vo2_max_value or vo2_max_value_cycling:
                points_list.append({
                    "measurement":  "VO2_Max",
                    "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {"VO2_max_value" : vo2_max_value, "VO2_max_value_cycling" : vo2_max_value_cycling}
                })
                logging.info(f"Success : Fetching VO2-max for date {date_str}")
        return points_list
    except AttributeError as err:
        return []

def get_endurance_score(date_str):
    points_list = []
    endurance_dict = garmin_obj.get_endurance_score(date_str)
    if endurance_dict:
        if endurance_dict.get("overallScore"):
            points_list.append({
                "measurement":  "EnduranceScore",
                "time": pytz.timezone("UTC").localize(datetime.strptime(date_str,"%Y-%m-%d")).isoformat(), # Use GMT 00:00 is timestamp is not available
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": {
                    "EnduranceScore": endurance_dict.get("overallScore")
                    }
            })
            logging.info(f"Success : Fetching Endurance Score for date {date_str}")
    return points_list

def get_blood_pressure(date_str):
    points_list = []
    bp_all = garmin_obj.get_blood_pressure(date_str, date_str).get('measurementSummaries',[])
    if len(bp_all) > 0:
        bp_list = bp_all[0].get('measurements',[])
        for bp_measurement in bp_list:
            data_fields = {
                'Systolic': bp_measurement.get('systolic', None),
                "Diastolic": bp_measurement.get('diastolic', None),
                "Pulse": bp_measurement.get('pulse', None)
            }
            if not all(value is None for value in data_fields.values()) and 'measurementTimestampGMT' in bp_measurement:
                points_list.append({
                    "measurement":  "BloodPressure",
                    "time": pytz.UTC.localize(datetime.strptime(bp_measurement['measurementTimestampGMT'], '%Y-%m-%dT%H:%M:%S.%f')),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE,
                        "Source": bp_measurement.get('sourceType', None)
                    },
                    "fields": data_fields
                })
        logging.info(f"Success : Fetching Blood Pressure for date {date_str}")
    return points_list

def get_hydration(date_str):
    points_list = []
    hydration_dict = garmin_obj.get_hydration_data(date_str)
    data_fields = {
        'ValueInML': hydration_dict.get('valueInML', None),
        "SweatLossInML": hydration_dict.get('sweatLossInML', None),
        "GoalInML": hydration_dict.get('goalInML', None),
        "ActivityIntakeInML": hydration_dict.get('activityIntakeInML', None)
    }
    if not all(value is None for value in data_fields.values()):
        points_list.append({
            "measurement":  "Hydration",
            "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
            "tags": {
                "Device": GARMIN_DEVICENAME,
                "Database_Name": INFLUXDB_DATABASE
            },
            "fields": data_fields
        })
        logging.info(f"Success : Fetching Hydration data for date {date_str}")
    return points_list


def get_solar_intensity(date_str):
    points_list = []

    if not GARMIN_DEVICEID:
        logging.warning("Skipping Solar Intensity data fetch as GARMIN_DEVICEID is not set.")
        return points_list

    si_all = garmin_obj.get_device_solar_data(GARMIN_DEVICEID, date_str) or {}
    if len(si_all.get('solarDailyDataDTOs', [])) > 0:
        si_list = si_all['solarDailyDataDTOs'][0].get('solarInputReadings', [])
        for si_measurement in si_list:
            data_fields = {
                'solarUtilization': si_measurement.get('solarUtilization', None),
                'activityTimeGainMs': si_measurement.get('activityTimeGainMs', None),
            }
            if not all(value is None for value in data_fields.values()) and 'readingTimestampGmt' in si_measurement:
                points_list.append({
                    "measurement":  "SolarIntensity",
                    "time": pytz.UTC.localize(datetime.strptime(si_measurement['readingTimestampGmt'], '%Y-%m-%dT%H:%M:%S.%f')),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": data_fields
                })
        logging.info(f"Success : Fetching Solar Intensity data for date {date_str}")
    if len(points_list) == 0:
        logging.warning(f"No Solar Intensity data available for date {date_str}")
    return points_list

# %%
def get_lifestyle_data(date_str):
    points_list = []
    try:
        logging.info(f"Fetching Lifestyle Journaling data for date {date_str}")
        journal_data = garmin_obj.get_lifestyle_logging_data(date_str)
        
        daily_logs = journal_data.get('dailyLogsReport', [])
        
        for log in daily_logs:
            behavior_name = log.get('name') or log.get('behavior')
            if not behavior_name:
                continue

            category = log.get('category', 'UNKNOWN')
            log_status = log.get('logStatus')
            details = log.get('details', [])
            
            # status: 1 for YES, 0 for NO
            status = 1 if log_status == "YES" else 0
            
            # value: sum of detail amounts if available, else 0.0
            value = 0.0
            if details:
                for detail in details:
                    amount = detail.get('amount')
                    if amount is not None:
                        value += float(amount)

            fields = {
                "status": status,
                "value": value
            }

            points_list.append({
                "measurement": "LifestyleJournal",
                "time": pytz.timezone("UTC").localize(datetime.strptime(date_str, "%Y-%m-%d")).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE,
                    "behavior": behavior_name,
                    "category": category
                },
                "fields": fields
            })
            
        logging.info(f"Success : Fetching Lifestyle Journaling data for date {date_str}")

    except Exception as e:
        logging.warning(f"Failed to fetch Lifestyle Journaling data for date {date_str}: {e}")
    
    return points_list


# %%
def daily_fetch_write(date_str):
    if REQUEST_INTRADAY_DATA_REFRESH and (datetime.strptime(date_str, "%Y-%m-%d") <= (datetime.today() - timedelta(days=IGNORE_INTRADAY_DATA_REFRESH_DAYS))):
        data_refresh_response = garmin_obj.connectapi(f"wellness-service/wellness/epoch/request/{date_str}", method="POST").get("status", "Unknown")
        logging.info(f"Intraday data refresh request status: {data_refresh_response}")
        if data_refresh_response == "SUBMITTED":
            logging.info(f"Waiting 10 seconds for refresh request to process...")
            time.sleep(10)
        elif data_refresh_response == "COMPLETE":
            logging.info(f"Data for date {date_str} is already available")
        elif data_refresh_response == "NO_FILES_FOUND":
            logging.info(f"No Data is available for date {date_str} to refresh")
            return None
        elif data_refresh_response == "DENIED":
            logging.info(f"Daily refresh limit reached. Pausing script for 24 hours to ensure Intraday data fetching. Disable REQUEST_INTRADAY_DATA_REFRESH to avoid this!")
            time.sleep(86500)
            data_refresh_response = garmin_obj.connectapi(f"wellness-service/wellness/epoch/request/{date_str}", method="POST").get("status", "Unknown")
            logging.info(f"Intraday data refresh request status: {data_refresh_response}")
            logging.info(f"Waiting 10 seconds...")
            time.sleep(10)
        else:
            logging.info(f"Refresh response is unknown!")
            time.sleep(5)
    if 'daily_avg' in FETCH_SELECTION:
        write_points_to_influxdb(get_daily_stats(date_str))
    if 'sleep' in FETCH_SELECTION:
        write_points_to_influxdb(get_sleep_data(date_str))
    if 'steps' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_steps(date_str))
    if 'heartrate' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_hr(date_str))
    if 'stress' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_stress(date_str))
    if 'breathing' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_br(date_str))
    if 'hrv' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_hrv(date_str))
    if 'fitness_age' in FETCH_SELECTION:
        write_points_to_influxdb(get_fitness_age(date_str))
    if 'vo2' in FETCH_SELECTION:
        write_points_to_influxdb(get_vo2_max(date_str))
    if 'race_prediction' in FETCH_SELECTION:
        write_points_to_influxdb(get_race_predictions(date_str))
    if 'body_composition' in FETCH_SELECTION:
        write_points_to_influxdb(get_body_composition(date_str))
    if 'lactate_threshold' in FETCH_SELECTION:
        write_points_to_influxdb(get_lactate_threshold(date_str))
    if 'training_status' in FETCH_SELECTION:
        write_points_to_influxdb(get_training_status(date_str))
    if 'training_readiness' in FETCH_SELECTION:
        write_points_to_influxdb(get_training_readiness(date_str))
    if 'hill_score' in FETCH_SELECTION:
        write_points_to_influxdb(get_hillscore(date_str))
    if 'endurance_score' in FETCH_SELECTION:
        write_points_to_influxdb(get_endurance_score(date_str))
    if 'blood_pressure' in FETCH_SELECTION:
        write_points_to_influxdb(get_blood_pressure(date_str))
    if 'hydration' in FETCH_SELECTION:
        write_points_to_influxdb(get_hydration(date_str))
    if 'activity' in FETCH_SELECTION:
        activity_summary_points_list, activity_with_gps_id_dict, strength_activity_id_dict = get_activity_summary(date_str)
        write_points_to_influxdb(activity_summary_points_list)
        write_points_to_influxdb(fetch_activity_GPS(activity_with_gps_id_dict))
        if strength_activity_id_dict:
            write_points_to_influxdb(get_strength_training_data(strength_activity_id_dict))
    if 'solar_intensity' in FETCH_SELECTION:
        write_points_to_influxdb(get_solar_intensity(date_str))
    if 'lifestyle' in FETCH_SELECTION:
        write_points_to_influxdb(get_lifestyle_data(date_str))


# %%
def fetch_write_bulk(start_date_str, end_date_str):
    global garmin_obj
    consecutive_500_errors = 0
    logging.info("Fetching data for the given period in reverse chronological order")
    time.sleep(3)
    write_points_to_influxdb(get_last_sync())
    for current_date in iter_days(start_date_str, end_date_str):
        repeat_loop = True
        while repeat_loop:
            try:
                daily_fetch_write(current_date)
                # Reset consecutive 500 error counter on successful fetch
                if consecutive_500_errors > 0:
                    logging.info(f"Successfully fetched data after {consecutive_500_errors} consecutive 500 errors - resetting error counter")
                    consecutive_500_errors = 0
                logging.info(f"Success : Fetched all available health metrics for date {current_date} (skipped any if unavailable)")
                if RATE_LIMIT_CALLS_SECONDS > 0:
                    logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds")
                    time.sleep(RATE_LIMIT_CALLS_SECONDS)
                repeat_loop = False
            except GarminConnectTooManyRequestsError as err:
                logging.error(err)
                logging.info(f"Too many requests (429) : Failed to fetch one or more metrics - will retry for date {current_date}")
                logging.info(f"Waiting : for {FETCH_FAILED_WAIT_SECONDS} seconds")
                time.sleep(FETCH_FAILED_WAIT_SECONDS)
                repeat_loop = True
            except (requests.exceptions.HTTPError, GarminConnectConnectionError) as err:
                # Check if this is a 500 error
                is_500_error = _is_http_status_error(err, 500)
                
                if is_500_error:
                    consecutive_500_errors += 1
                    logging.error(f"HTTP 500 error ({consecutive_500_errors}/{MAX_CONSECUTIVE_500_ERRORS}) for date {current_date}: {err}")
                    if consecutive_500_errors >= MAX_CONSECUTIVE_500_ERRORS:
                        logging.warning(f"Received {consecutive_500_errors} consecutive HTTP 500 errors. Logging error and continuing backward in time to fetch remaining data.")
                        logging.warning(f"Skipping date {current_date} due to persistent 500 errors from Garmin API")
                        logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds before continuing")
                        time.sleep(RATE_LIMIT_CALLS_SECONDS)
                        repeat_loop = False
                    else:
                        logging.info(f"HTTP 500 error encountered - will retry for date {current_date} (attempt {consecutive_500_errors}/{MAX_CONSECUTIVE_500_ERRORS})")
                        logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds before retry")
                        time.sleep(RATE_LIMIT_CALLS_SECONDS)
                        repeat_loop = True
                else:
                    # Non-500 HTTP errors - handle as before
                    logging.error(err)
                    logging.info(f"HTTP Error (non-500) : Failed to fetch one or more metrics - skipping date {current_date}")
                    logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds")
                    time.sleep(RATE_LIMIT_CALLS_SECONDS)
                    repeat_loop = False
            except (
                    GarminConnectConnectionError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout
                    ) as err:
                logging.error(err)
                logging.info(f"Connection Error : Failed to fetch one or more metrics - skipping date {current_date}")
                logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds")
                time.sleep(RATE_LIMIT_CALLS_SECONDS)
                repeat_loop = False
            except GarminConnectAuthenticationError as err:
                logging.error(err)
                logging.info(f"Authentication Failed : Retrying login with given credentials (won't work automatically for MFA/2FA enabled accounts)")
                garmin_obj = garmin_login(CONFIG)
                time.sleep(5)
                repeat_loop = True
            except Exception as err:
                if IGNORE_ERRORS:
                    logging.warning("IGNORE_ERRORS Enabled >> Failed to process %s:", current_date)
                    logging.exception(err)
                    repeat_loop = False
                else:
                    raise err


if __name__ == "__main__":
    try:
        INFLUXDB_STORAGE.check_connection()
    except (InfluxDBClientError, InfluxDBError):
        # check_connection() already wraps the underlying error into a
        # descriptive InfluxDBClientError -- re-raise it as-is rather than
        # wrapping it again, which previously produced a doubled message
        # ("InfluxDB connection failed:InfluxDB connection failed:...").
        logging.error("Unable to connect with influxdb database! Aborted")
        raise

    garmin_obj = garmin_login(CONFIG)

    # %%
    if MANUAL_START_DATE:
        fetch_write_bulk(MANUAL_START_DATE, MANUAL_END_DATE)
        logging.info(f"Bulk update success : Fetched all available health metrics for date range {MANUAL_START_DATE} to {MANUAL_END_DATE}")
        exit(0)
    else:
        try:
            last_sync_rows = INFLUXDB_STORAGE.query("SELECT * FROM HeartRateIntraday ORDER BY time DESC LIMIT 1")
            if INFLUXDB_VERSION == "1":
                last_influxdb_sync_time_UTC = pytz.utc.localize(datetime.strptime(last_sync_rows[0]['time'], "%Y-%m-%dT%H:%M:%SZ"))
            else:
                last_influxdb_sync_time_UTC = pytz.utc.localize(last_sync_rows[0]['time'])
        except Exception as err:
            logging.error(err)
            logging.warning("No previously synced data found in local InfluxDB database, defaulting to 7 day initial fetching. Use specific start date ENV variable to bulk update past data")
            last_influxdb_sync_time_UTC = (datetime.today() - timedelta(days=7)).astimezone(pytz.timezone("UTC"))
        try:
            if USER_TIMEZONE: # If provided by user, using that. 
                local_timediff = datetime.now(tz=pytz.timezone(USER_TIMEZONE)).utcoffset()
            else: # otherwise try to set automatically
                last_activity_dict = garmin_obj.get_last_activity() # (very unlineky event that this will be empty given Garmin's userbase, everyone should have at least one activity)
                local_timediff = datetime.strptime(last_activity_dict['startTimeLocal'], '%Y-%m-%d %H:%M:%S') - datetime.strptime(last_activity_dict['startTimeGMT'], '%Y-%m-%d %H:%M:%S')
            if local_timediff >= timedelta(0):
                logging.info("Using user's local timezone as UTC+" + str(local_timediff))
            else:
                logging.info("Using user's local timezone as UTC-" + str(-local_timediff))
        except (KeyError, TypeError) as err:
            logging.warning(f"Unable to determine user's timezone - Defaulting to UTC. Consider providing TZ identifier with USER_TIMEZONE environment variable")
            local_timediff = timedelta(hours=0)
        
        while True:
            last_watch_sync_time_UTC = datetime.fromtimestamp(int(garmin_obj.get_device_last_used().get('lastUsedDeviceUploadTime')/1000)).astimezone(pytz.timezone("UTC"))
            if last_influxdb_sync_time_UTC < last_watch_sync_time_UTC:
                logging.info(f"Update found : Current watch sync time is {last_watch_sync_time_UTC} UTC")
                fetch_write_bulk((last_influxdb_sync_time_UTC + local_timediff).strftime('%Y-%m-%d'), (last_watch_sync_time_UTC + local_timediff).strftime('%Y-%m-%d')) # Using local dates for deciding which dates to fetch in current iteration (see issue #25)
                last_influxdb_sync_time_UTC = last_watch_sync_time_UTC
            else:
                logging.info(f"No new data found : Current watch and influxdb sync time is {last_watch_sync_time_UTC} UTC")
            logging.info(f"waiting for {UPDATE_INTERVAL_SECONDS} seconds before next automatic update calls")
            time.sleep(UPDATE_INTERVAL_SECONDS)
