"""
subscriber.py — Pipeline entry point
Listens to MQTT, validates, enriches, and writes to InfluxDB.
Run this continuously while collecting data.
"""

import paho.mqtt.client as mqtt
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings    import cfg
from src.validator      import validate, is_anomaly, enrich
from src.influx_writer  import write

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/subscriber.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

bad_data_log = logging.getLogger("bad_data")
bad_data_handler = logging.FileHandler(cfg["pipeline"]["bad_data_log"])
bad_data_log.addHandler(bad_data_handler)
bad_data_log.setLevel(logging.WARNING)

# ── Record counter ────────────────────────────────────────────────────────────
record_count = {"total": 0, "valid": 0, "invalid": 0, "anomalies": 0}

# ── MQTT callbacks ────────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("Connected to MQTT broker")
        client.subscribe(cfg["mqtt"]["topic"])
        log.info(f"Subscribed to: {cfg['mqtt']['topic']}")
    else:
        log.error(f"MQTT connection failed rc={rc}")

def on_message(client, userdata, msg):
    try:
        raw  = msg.payload.decode("utf-8")
        data = json.loads(raw)

        # validate
        valid, reason = validate(data)
        anomaly       = is_anomaly(data)

        if not valid:
            bad_data_log.warning(
                f"{datetime.utcnow().isoformat()} | "
                f"room={data.get('room','?')} | "
                f"reason={reason} | raw={raw}"
            )
            record_count["invalid"] += 1
            log.warning(f"Invalid data [{reason}] — logged to bad_data.log")
            return   # do not save invalid records to InfluxDB

        # enrich
        data = enrich(data)

        # write
        write(data, valid, anomaly)

        # counters
        record_count["total"]  += 1
        record_count["valid"]  += 1
        if anomaly:
            record_count["anomalies"] += 1

        log.info(
            f"[{data.get('room','?').upper():8}] "
            f"Temp={data.get('temperature'):5.1f}°C  "
            f"Humid={data.get('humidity'):5.1f}%  "
            f"AQI={str(data.get('airquality','N/A')):>5}  "
            f"Motion={data.get('motion','N/A')}  "
            f"TOD={data.get('time_of_day'):11}  "
            f"{'⚠ ANOMALY' if anomaly else '          '}"
            f"  total={record_count['total']}"
        )

    except json.JSONDecodeError as e:
        log.error(f"JSON error: {e} — raw: {msg.payload}")
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)

def on_disconnect(client, userdata, rc):
    log.warning(f"Disconnected from MQTT (rc={rc}), will auto-reconnect")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 60)
    log.info("IoT Pipeline Subscriber Starting")
    log.info(f"Broker : {cfg['mqtt']['broker']}:{cfg['mqtt']['port']}")
    log.info(f"Topic  : {cfg['mqtt']['topic']}")
    log.info(f"InfluxDB: {cfg['influxdb']['url']}")
    log.info("=" * 60)

    client = mqtt.Client()
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    client.connect(
        cfg["mqtt"]["broker"],
        cfg["mqtt"]["port"],
        keepalive=60,
    )

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info(f"Stopped. Final counts: {record_count}")
