import logging
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import cfg

log = logging.getLogger(__name__)

def get_client():
    from influxdb_client import InfluxDBClient
    return InfluxDBClient(
        url=cfg["influxdb"]["url"],
        token=cfg["influxdb"]["token"],
        org=cfg["influxdb"]["org"],
    )

def write(data: dict, is_valid: bool, anomaly: bool):
    """
    Writes one sensor reading to InfluxDB.
    Schema:
      measurement : air_quality
      tags        : room, time_of_day, aqi_label
      fields      : temperature, humidity, airquality, motion, is_valid, anomaly
    """
    from influxdb_client.client.write_api import SYNCHRONOUS
    from influxdb_client import Point

    point = (
        Point("air_quality")
        .tag("room",        data.get("room", "unknown"))
        .tag("time_of_day", data.get("time_of_day", "unknown"))
        .tag("aqi_label",   data.get("aqi_label",   "Unknown"))
        .field("temperature", float(data["temperature"]))
        .field("humidity",    float(data["humidity"]))
        .field("is_valid",    int(is_valid))
        .field("anomaly",     int(anomaly))
        .time(datetime.utcnow())
    )

    if data.get("airquality") is not None:
        point = point.field("airquality", int(data["airquality"]))
    if data.get("motion") is not None:
        point = point.field("motion", int(data["motion"]))

    client = get_client()
    write_api = client.write_api(write_options=SYNCHRONOUS)
    write_api.write(
        bucket=cfg["influxdb"]["bucket"],
        org=cfg["influxdb"]["org"],
        record=point,
    )
    client.close()
    log.debug(f"Written to InfluxDB: {data.get('room')} @ {datetime.utcnow().isoformat()}")
