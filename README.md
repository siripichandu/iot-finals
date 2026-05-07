# Indoor Air Quality Monitor
### IoT Capstone — Spring 2026

Most people have no idea what the air in their home actually looks like. CO2 builds up while you sleep, cooking fills the kitchen with pollutants that stick around for 30+ minutes, and there's nothing telling you to open a window. We built this pipeline to fix that — two ESP32 sensor nodes, a full data pipeline, a live dashboard, and an ML model that flags when things go wrong.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DEVICE LAYER                                │
│                                                                     │
│   ESP32 #1 — Bedroom                  ESP32 #2 — Kitchen           │
│   ├─ DHT22   → Temperature, Humidity  ├─ DHT22   → Temp, Humidity  │
│   ├─ MQ-135  → Air Quality (AQI)      ├─ MQ-135  → Air Quality     │
│   └─ HC-SR501 → Motion/Occupancy      └─ HC-SR501 → Motion         │
│                                                                     │
│   Publishes every 10 seconds via WiFi                               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  MQTT JSON payload
                           │  topic: home/airquality
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      COMMUNICATION LAYER                            │
│                                                                     │
│   Protocol : MQTT (paho-mqtt)                                       │
│   Broker   : Mosquitto — localhost:1883                             │
│   Why MQTT : lightweight pub/sub, <1KB overhead, handles lossy      │
│   WiFi gracefully, auto-reconnects, no polling needed               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       PROCESSING LAYER                              │
│                                                                     │
│   src/subscriber.py  ←  entry point                                 │
│   ├─ src/validator.py                                               │
│   │   ├─ Null / missing field check                                 │
│   │   ├─ Type validation (float, int)                               │
│   │   ├─ Range check: temp -10–60°C, humidity 0–100%, AQI 0–4095  │
│   │   ├─ Threshold anomaly flag (AQI>1500, temp>35)                 │
│   │   └─ Enrichment: time_of_day tag, aqi_label tag                 │
│   └─ src/influx_writer.py                                           │
│       └─ Writes validated + enriched records to InfluxDB           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        STORAGE LAYER                                │
│                                                                     │
│   Database  : InfluxDB (localhost:8086)                             │
│   Why InfluxDB : purpose-built for time-series, timestamps are the  │
│   primary index natively, tags are indexed for fast GROUP BY room   │
│                                                                     │
│   Schema:                                                           │
│   measurement : air_quality                                         │
│   tags        : room, time_of_day, aqi_label                        │
│     → Tags are indexed → fast GROUP BY room queries                 │
│   fields      : temperature, humidity, airquality, motion,         │
│                 is_valid, anomaly                                    │
│   timestamp   : auto (nanosecond precision)                         │
│                                                                     │
│   Sample queries:                                                   │
│   → Last 1h per room:  range(start:-1h) |> filter room==bedroom    │
│   → AQI > 1500:        filter airquality > 1500                     │
│   → Anomalies only:    filter anomaly == 1                          │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER  (Option A)                     │
│                                                                     │
│   dashboard/app.py  — Streamlit live dashboard                      │
│   ├─ Visualization 1: Real-time temp + humidity trend chart         │
│   │   (dual-axis, rolling average overlay, live refresh)            │
│   ├─ Visualization 2: Air quality chart with threshold bands        │
│   │   (Good/Moderate/Poor/Hazardous zones, anomaly markers)         │
│   └─ Motion/occupancy + room comparison charts                      │
│                                                                     │
│   ml/anomaly.py  — Isolation Forest ML model                        │
│   ├─ Input features: temperature, humidity, airquality              │
│   ├─ Output: ml_anomaly (bool), anomaly_score (float)               │
│   └─ Decisions: VENTILATE NOW / Monitor Air / Temp Alert            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Why we chose each component

We made deliberate choices at each layer — here's the reasoning:

| Component | Why we chose it |
|---|---|
| ESP32 | Has WiFi built in, costs under $10, works with Arduino IDE — no extra hardware needed |
| DHT22 | Plug-in module, no soldering, ±0.5°C accuracy, widely supported |
| MQ-135 | Reads CO2 proxy and VOCs via analog output — works directly with ESP32 ADC |
| HC-SR501 PIR | Detects room occupancy so we can correlate motion with air quality changes |
| MQTT | Way lighter than HTTP for small sensor payloads, handles WiFi dropout gracefully |
| Mosquitto | Runs locally in one command, zero config, easy to debug during development |
| InfluxDB | The only sensible choice for time-series — timestamps are the primary index, tag-based filtering is instant |
| Python | pandas + sklearn + plotly is the fastest path from raw data to insight |
| Streamlit | We can build a live refreshing dashboard in pure Python without touching JavaScript |
| Isolation Forest | No labelled training data needed — it learns what "normal" looks like and flags everything else |

---

## Project structure

```
iot_pipeline/
├── arduino/
|   |—— bedroom_node.ino    # ino code for bedroom esp setup
|   |—— kitchen_node.ino    # ino code for kitchen esp setup
|—— src/
│   ├── subscriber.py       # MQTT listener + pipeline entry point
│   ├── validator.py        # validation, enrichment, anomaly flagging
│   └── influx_writer.py    # InfluxDB write helper
├── ml/
│   └── anomaly.py          # Isolation Forest + Z-score anomaly detection
├── dashboard/
│   └── app.py              # Streamlit live dashboard
├── config/
│   ├── config.yaml         # all settings — thresholds, DB config, MQTT
│   └── settings.py         # config loader
├── scripts/
│   ├── run_pipeline.sh     # start everything with one command
│   └── import_excel.py     # import collected data into InfluxDB
├── references/             # screenshots and architecture diagram
├── logs/                   # auto-created on first run
├── data/                   # auto-created on first run
├── requirements.txt
└── README.md
```

---

## Setup

### Step 1 — Clone and install
```bash
git clone https://github.com/siripichandu/iot-finals.git
cd iot-finals
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2 — Start Mosquitto
```bash
brew install mosquitto
echo "listener 1883\nallow_anonymous true" >> /opt/homebrew/etc/mosquitto/mosquitto.conf
brew services start mosquitto
```

### Step 3 — Set up InfluxDB
```bash
brew install influxdb
brew services start influxdb
```
Open http://localhost:8086 → create account → org: `iot_project` → bucket: `airquality1`

Copy the API token → paste into `config/config.yaml` under `influxdb.token`

### Step 4 — Flash ESP32 boards
- Arduino IDE → install board: `esp32 by Espressif Systems v3.3.8`
- Install libraries: `DHT sensor library by Adafruit`, `PubSubClient by Nick O'Leary`
- Flash bedroom code to ESP32 #1, kitchen code to ESP32 #2
- Update WiFi credentials and laptop IP (`ipconfig getifaddr en0`) in each sketch before flashing

---

## Running the project

```bash
# 1. Start the broker
brew services start mosquitto

# 2. Start the pipeline subscriber — leave this running
source venv/bin/activate
python src/subscriber.py

# 3. Start the dashboard in a separate terminal
streamlit run dashboard/app.py
# opens at http://localhost:8501

# 4. Run ML anomaly detection on collected data
python ml/anomaly.py
# uses sensor_data_full.xlsx by default
# or point it at InfluxDB:
python ml/anomaly.py --hours 24
```

---

## Bad data handling

We ran into several real data quality issues during development. Here's how the pipeline handles each one:

| Scenario | What we do |
|---|---|
| Null / missing field | Skip the record, log to `logs/bad_data.log` with reason and timestamp |
| Temperature out of range (>60°C or <-10°C) | Flag `is_valid=0`, don't write to InfluxDB |
| Humidity > 100% | Same — physically impossible, almost certainly a sensor fault |
| MQ-135 warmup zeros | The sensor reads 0 for ~2 min after power-on. Filtered by minimum range check |
| AQI spike >1500 | Written with `anomaly=1` tag so ML can use it as a training signal |
| JSON parse error | Caught, logged, skipped — pipeline keeps running |
| MQTT disconnect | Auto-reconnect, gap is logged |

---

## ML model

We used Isolation Forest because we had no labelled training data — we couldn't know in advance which readings would be anomalous. Isolation Forest learns what "normal" looks like from the data itself.

**Input features:** `temperature`, `humidity`, `airquality` — plus 6-reading rolling deviations for each. The rolling deviation is important: a sudden spike from 80 to 2000 AQI is far more anomalous than a sustained reading of 200, and the deviation captures that.

**Output:**
- `ml_anomaly` — True/False per reading
- `anomaly_score` — continuous score, negative = more anomalous

**What the system does with it:**

| Condition | Action |
|---|---|
| anomaly + AQI > 1500 | VENTILATE NOW |
| anomaly + AQI 500–1500 | Monitor Air |
| anomaly + temp > 30°C | Temperature Alert |
| anomaly + humidity > 75% | High Humidity |

**Results on our dataset:** 540 anomalies flagged across 10,800 records (5.0%), with 256 VENTILATE NOW decisions, 112 temperature alerts, and 69 Monitor Air warnings.

---

## Data collected

- 10,800 total records across 3 days (April 20–22, 2026)
- Bedroom: 5,400 records · Kitchen: 5,400 records
- 10-second sampling interval per node
- 4 attributes per reading: temperature, humidity, AQI, motion
- Sensor went offline periodically (WiFi dropout, power cycles) — gaps are logged

---

## Data

The full dataset is not committed to this repo due to file size. It lives locally in InfluxDB and as an Excel file.

**To import the existing dataset:**
```bash
python scripts/import_excel.py
```

**To collect fresh data:** power up both ESP32s and run `python src/subscriber.py`.

**Dataset summary:**
- Total records: 10,800
- Rooms: Bedroom (5,400) · Kitchen (5,400)
- Period: April 20–22, 2026
- Attributes: temperature · humidity · AQI · motion
- ML anomalies: 540 (5.0%)

**Evidence screenshots are in `references/`:**
- `architecture_diagram.png` — full 5-layer pipeline architecture
- `influxdb_record_count.png` — InfluxDB query confirming 5,400 records per room
- `influxdb_schema.png` — measurement, tags, and fields in InfluxDB Data Explorer
- `excel_data_preview.png` — sample rows from sensor_data_full.xlsx
- `anomaly_report_preview.png` — ML output showing ml_anomaly and decision columns
- `Indoor Air Quality Monitor Homepage.pdf` — full dashboard homepage view with KPI cards and insight bar
- `Indoor Air Quality Monitor bed room.pdf` — bedroom filter view showing temperature, humidity and AQI trends
- `Indoor Air Quality Monitor kitchen.pdf` — kitchen filter view showing room-specific air quality patterns

---

## Challenges we ran into

A few things that tripped us up and are worth documenting:

- **GPIO34 on the ESP32 reads zero for analog input** despite the datasheet suggesting otherwise. GPIO35 works fine. Cost us a couple hours.
- **MQ-135 needs 2–3 minutes to warm up** after power-on. Early readings are always zero. Handled in the validator.
- **Both ESP32s must have different MQTT client IDs** — if they share one, the broker keeps dropping whichever connected second.
- **The laptop IP changes every time it reconnects to WiFi.** The ESP32 has the broker IP hardcoded, so every network switch means re-flashing. In production this would be a DNS hostname.
- **InfluxDB `room` must be a tag, not a field.** We learned this the hard way — fields aren't indexed, so GROUP BY room was scanning everything. Moving it to a tag made queries instant.
