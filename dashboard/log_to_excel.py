import re
import pandas as pd

LOG_FILE = "logs/subscriber.log"   # change path if needed
OUT_FILE = "data/sensor_data.xlsx"

pattern = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?"
    r"\[(\w+)\].*?"
    r"Temp=([\d.]+).*?"
    r"Humid=([\d.]+).*?"
    r"AQI=([\d.]+|N/A).*?"
    r"Motion=(\d)"
)

records = []
with open(LOG_FILE, "r") as f:
    for line in f:
        m = pattern.search(line)
        if m:
            aqi = m.group(5)
            records.append({
                "Timestamp":   m.group(1),
                "Room":        m.group(2).title(),
                "Temperature": float(m.group(3)),
                "Humidity":    float(m.group(4)),
                "AQI":         None if aqi == "N/A" else float(aqi),
                "Motion":      int(m.group(6)),
            })

df = pd.DataFrame(records)
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df = df.sort_values("Timestamp").reset_index(drop=True)

print(f"Total records extracted: {len(df)}")
print(df["Room"].value_counts())

df.to_excel(OUT_FILE, index=False)
print(f"Saved to {OUT_FILE}")