import pandas as pd
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import yaml
import os

# Load config
config_path = os.path.expanduser("~/iot_pipeline/config/config.yaml")
with open(config_path, "r") as f:
    cfg = yaml.safe_load(f)

db = cfg["influxdb"]

# Load your Excel file — update filename if different
FILE = os.path.expanduser("~/iot_pipeline/data/sensor_data_full.xlsx")

df = pd.read_excel(FILE, sheet_name="All Data")
df = df.rename(columns={
    "Timestamp":   "time",
    "Room":        "room",
    "Temperature": "temperature",
    "Humidity":    "humidity",
    "AQI":         "airquality",
    "Motion":      "motion",
    "AQI_Label":   "aqi_label",
})
df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("UTC")
df["room"] = df["room"].str.lower()

client = InfluxDBClient(url=db["url"], token=db["token"], org=db["org"])
write_api = client.write_api(write_options=SYNCHRONOUS)

BATCH = 500
total = 0

for i in range(0, len(df), BATCH):
    batch = df.iloc[i:i+BATCH]
    points = []
    for _, row in batch.iterrows():
        hour = row["time"].hour
        if   5 <= hour < 12: tod = "morning"
        elif 12 <= hour < 17: tod = "afternoon"
        elif 17 <= hour < 21: tod = "evening"
        else: tod = "night"

        p = (Point("air_quality")
             .tag("room",        str(row["room"]))
             .tag("time_of_day", tod)
             .tag("aqi_label",   str(row.get("aqi_label", "Good")))
             .field("temperature", float(row["temperature"]))
             .field("humidity",    float(row["humidity"]))
             .field("airquality",  int(row["airquality"]) if pd.notna(row["airquality"]) else 0)
             .field("motion",      int(row["motion"]))
             .time(row["time"]))
        points.append(p)

    write_api.write(bucket=db["bucket"], org=db["org"], record=points)
    total += len(batch)
    print(f"Written {total}/{len(df)} records...")

client.close()
print(f"\nDone! {total} records imported into InfluxDB bucket: {db['bucket']}")