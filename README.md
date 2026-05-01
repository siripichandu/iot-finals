# 🏠 Indoor Air Quality Monitor
### IoT Capstone Project — Spring 2026

> **Problem:** People spend 90% of their time indoors but have zero visibility into air quality. CO2 builds up in bedrooms during sleep, cooking spikes pollutants in kitchens, and there is no system to tell you when to ventilate. This pipeline makes the invisible visible and actionable.

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
│   Justification: MQTT is publish/subscribe, lightweight (<1KB       │
│   overhead), perfect for low-power ESP32 devices on WiFi.           │
│   Handles reconnection, QoS levels, and async delivery.             │
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
│   Justification: Purpose-built time-series DB. Handles high        │
│   write throughput, native timestamp indexing, tag-based queries,  │
│   and built-in data retention policies. Ideal for sensor data.     │
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
│   ├─ Input features: temperature, humidity, airquality,             │
│   │                  rolling mean deviations                         │
│   ├─ Output: ml_anomaly (bool), anomaly_score (float)               │
│   └─ Decision: anomaly + AQI>1500 → VENTILATE NOW alert             │
│                anomaly + temp>30  → Temperature Alert               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Why each component was chosen

| Component | Reason |
|---|---|
| **ESP32** | Built-in WiFi, cheap (~$6), Arduino IDE support, widely documented |
| **DHT22** | ±0.5°C accuracy, 3-wire module, no soldering, beginner-friendly |
| **MQ-135** | Detects CO2 proxy + VOCs, analog output works with ESP32 ADC |
| **HC-SR501** | PIR motion — detects occupancy to correlate with air quality |
| **MQTT** | Lightweight pub/sub, < 1KB overhead, handles lossy WiFi gracefully |
| **Mosquitto** | Open source, runs locally, zero-config for development |
| **InfluxDB** | Time-series native — timestamp indexing, tag-based grouping, fast range queries |
| **Python** | Rich ecosystem (pandas, sklearn, plotly), readable, modular |
| **Streamlit** | Python-native dashboard, live refresh with `st.rerun()`, zero JS needed |
| **Isolation Forest** | Unsupervised ML — no labelled training data required, works well on multivariate sensor data |

---

## Project Structure

```
iot_pipeline/
├── src/
│   ├── subscriber.py       # MQTT listener + pipeline entry point
│   ├── validator.py        # validation, anomaly flag, enrichment
│   └── influx_writer.py    # InfluxDB write helper
├── ml/
│   └── anomaly.py          # Isolation Forest + Z-score anomaly detection
├── dashboard/
│   └── app.py              # Streamlit live dashboard
├── config/
│   ├── config.yaml         # all settings — thresholds, DB config, MQTT
│   └── settings.py         # config loader
├── scripts/
│   └── run_pipeline.sh     # start pipeline with one command
├── logs/                   # auto-created — subscriber.log, bad_data.log
├── data/                   # auto-created — anomaly reports, CSV exports
├── requirements.txt
└── README.md
```

---

## Setup

### Step 1 — Clone and install
```bash
git clone https://github.com/YOUR_USERNAME/iot-air-quality.git
cd iot-air-quality
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2 — Install and start Mosquitto (MQTT broker)
```bash
brew install mosquitto
echo "listener 1883\nallow_anonymous true" >> /opt/homebrew/etc/mosquitto/mosquitto.conf
brew services start mosquitto
```

### Step 3 — Install and configure InfluxDB
```bash
brew install influxdb
brew services start influxdb
```
Open http://localhost:8086 → create account → org: `iot_project` → bucket: `airquality`
Copy the API token → paste into `config/config.yaml` under `influxdb.token`

### Step 4 — Flash ESP32 devices
- Open Arduino IDE
- Install board: `esp32 by Espressif Systems v3.3.8`
- Install libraries: `DHT sensor library by Adafruit`, `PubSubClient by Nick O'Leary`
- Flash `arduino/bedroom_node.ino` to ESP32 #1
- Flash `arduino/kitchen_node.ino` to ESP32 #2
- Update WiFi credentials and laptop IP in each sketch

---

## Run Commands

```bash
# Start MQTT broker
brew services start mosquitto

# Start pipeline subscriber (keeps running, saves all data)
source venv/bin/activate
python src/subscriber.py

# Start live dashboard (separate terminal)
streamlit run dashboard/app.py

# Run ML anomaly detection (after collecting data)
python ml/anomaly.py 24                              # last 24 hours from InfluxDB
python ml/anomaly.py --csv data/sensor_data.xlsx     # from Excel file
```

---

## Bad Data Handling

The pipeline handles these scenarios — all documented in `src/validator.py`:

| Scenario | How handled |
|---|---|
| Null / missing fields | Skipped — logged to `logs/bad_data.log` with reason |
| Out-of-range temperature (>60°C or <-10°C) | Flagged `is_valid=0`, not written to DB |
| Out-of-range humidity (>100%) | Same — flagged and logged |
| AQI warmup zeros (MQ-135 first 60 sec) | Filtered by range check |
| Anomalous spike (AQI>1500) | Saved with `anomaly=1` tag for ML training |
| JSON parse error | Caught, logged, skipped |
| MQTT reconnection | Auto-reconnect with exponential backoff |

---

## ML Model — Isolation Forest

**Algorithm:** Isolation Forest (scikit-learn)

**Input features:**
- `temperature` — raw + 6-reading rolling deviation
- `humidity` — raw + 6-reading rolling deviation
- `airquality` — raw + 6-reading rolling deviation

**Why these features?** Anomalies in air quality rarely appear in one metric alone. A cooking event raises AQI *and* temperature *and* humidity together. The rolling deviation captures *sudden changes* which are more anomalous than sustained high values.

**Output:**
- `ml_anomaly` (bool) — True if Isolation Forest scores the reading as anomalous
- `anomaly_score` (float) — negative = more anomalous, used for severity ranking

**Decision rules:**
| Condition | Action |
|---|---|
| `ml_anomaly=True` AND `airquality > 1500` | → "VENTILATE NOW" alert |
| `ml_anomaly=True` AND `airquality 500–1500` | → "Monitor Air" warning |
| `ml_anomaly=True` AND `temperature > 30` | → "Temperature Alert" |
| `ml_anomaly=True` AND `humidity > 75` | → "High Humidity" warning |

**Contamination parameter:** 4% — based on observed anomaly rate in collected data (~3.8% of readings were flagged as out-of-range during validation).

---

## Data Collected

- **10,800 records** over 3 days (April 20–22, 2026)
- **2 sensor nodes:** Bedroom (5,400 records) + Kitchen (5,400 records)
- **4 attributes per reading:** temperature, humidity, air quality, motion
- **10-second intervals** within active windows
- **Sensor gaps** (offline 2–5 hours between sessions) — realistic WiFi dropout behavior

---

## Scaling to Enterprise

The current design runs on a laptop with local services. To scale to enterprise:

| Component | Current | Enterprise upgrade |
|---|---|---|
| MQTT broker | Mosquitto (local) | AWS IoT Core / HiveMQ cluster |
| Storage | InfluxDB (local) | InfluxDB Cloud / TimescaleDB on RDS |
| Processing | Python script | Apache Kafka + Flink stream processing |
| Dashboard | Streamlit (local) | Grafana with InfluxDB datasource |
| Devices | 2 ESP32s | Fleet management via AWS IoT Greengrass |
| Deployment | Manual | Dockerized, deployed via Kubernetes |

Key bottleneck at scale: the subscriber.py is single-threaded. At 1000+ devices, you'd need a message queue (Kafka) and parallel consumers.

---

## GitHub Commit History (Incremental Development)

```
git commit -m "init: project structure and requirements"
git commit -m "feat: ESP32 DHT22 basic sensor reading"
git commit -m "feat: add WiFi + MQTT publishing to ESP32"
git commit -m "feat: add MQ-135 and PIR sensors to bedroom node"
git commit -m "feat: add kitchen ESP32 node with DHT22 + PIR"
git commit -m "feat: Mosquitto broker setup and config"
git commit -m "feat: Python MQTT subscriber with JSON parsing"
git commit -m "feat: data validation module (null, range, type checks)"
git commit -m "feat: enrichment layer (time_of_day, aqi_label tags)"
git commit -m "feat: InfluxDB writer with proper schema (tags + fields)"
git commit -m "feat: Streamlit dashboard v1 - KPI cards and live data"
git commit -m "feat: add temperature + humidity trend chart"
git commit -m "feat: add air quality chart with threshold bands"
git commit -m "feat: add room comparison and motion charts"
git commit -m "feat: anomaly detection with Z-score in dashboard"
git commit -m "feat: Isolation Forest ML model with decision engine"
git commit -m "feat: ML visualization - 4-panel anomaly plot"
git commit -m "refactor: modular structure, config.yaml, logging"
git commit -m "docs: README with architecture diagram and setup steps"
git commit -m "fix: smooth dashboard refresh with st.rerun()"
git commit -m "fix: GPIO35 for MQ-135 (GPIO34 unreliable on this board)"
```

---

## Challenges, Learnings, Tradeoffs

**Challenges:**
- MQ-135 needs 2–3 min warmup — handled with range validation
- ESP32 GPIO34 proved unreliable for analog reads — switched to GPIO35
- Mosquitto required `allow_anonymous true` for local ESP32 connections
- MQTT client ID collision when two ESP32s connect — solved with unique client IDs

**Learnings:**
- IoT is not just code — hardware debugging (bad cables, wrong pins) takes as much time as software
- Time-series databases fundamentally differ from relational DBs — tags vs fields distinction matters for query performance
- Anomaly detection without labelled data is genuinely hard — Isolation Forest is a practical unsupervised solution

**IoT understanding shift:**
Before: IoT = sensors + cloud. After: IoT is an entire engineering discipline — device constraints, protocol tradeoffs, stream processing, time-series storage, edge intelligence.