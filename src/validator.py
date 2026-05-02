import logging
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import cfg

log = logging.getLogger(__name__)

THRESHOLDS = cfg["thresholds"]

def validate(data: dict) -> tuple:
    """
    Validates a sensor reading dict.
    Returns (is_valid: bool, reason: str)
    Checks: required fields, type checks, range checks
    """
    required = ["room", "temperature", "humidity"]
    for field in required:
        if field not in data or data[field] is None:
            return False, f"Missing field: {field}"

    temp  = data.get("temperature")
    humid = data.get("humidity")
    aqi   = data.get("airquality")

    if not isinstance(temp, (int, float)):
        return False, f"Bad temperature type: {temp}"
    if not isinstance(humid, (int, float)):
        return False, f"Bad humidity type: {humid}"

    if not (-10 <= temp <= 60):
        return False, f"Temperature out of range: {temp}"
    if not (0 <= humid <= 100):
        return False, f"Humidity out of range: {humid}"
    if aqi is not None and not (0 <= aqi <= 4095):
        return False, f"Air quality out of range: {aqi}"

    return True, "ok"


def is_anomaly(data: dict) -> bool:
    """
    Threshold-based anomaly detection at ingest time.
    Z-score anomaly detection runs separately in ml/anomaly.py
    """
    aqi  = data.get("airquality", 0) or 0
    temp = data.get("temperature", 20) or 20

    if aqi  > THRESHOLDS["airquality"]["alert"]:  return True
    if temp > THRESHOLDS["temperature"]["alert"]:  return True
    if temp < 5:                                   return True
    return False


def enrich(data: dict) -> dict:
    """
    Adds derived fields before saving:
    - time_of_day: morning/afternoon/evening/night
    - aqi_label: Good / Moderate / Poor / Hazardous
    """
    from datetime import datetime
    hour = datetime.utcnow().hour

    if   5  <= hour < 12: tod = "morning"
    elif 12 <= hour < 17: tod = "afternoon"
    elif 17 <= hour < 21: tod = "evening"
    else:                 tod = "night"

    aqi = data.get("airquality", 0) or 0
    if   aqi < 300:  label = "Good"
    elif aqi < 800:  label = "Moderate"
    elif aqi < 1500: label = "Poor"
    else:            label = "Hazardous"

    return {**data, "time_of_day": tod, "aqi_label": label}
