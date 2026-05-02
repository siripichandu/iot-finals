"""
anomaly.py — ML anomaly detection using Isolation Forest + Z-score
Run after collecting data. Works with Excel file OR InfluxDB live data.

Usage:
    python ml/anomaly.py --csv data/sensor_data.xlsx     # from Excel (use now)
    python ml/anomaly.py --hours 24                       # from InfluxDB (use later)
    python ml/anomaly.py --hours 48                       # last 48 hours from InfluxDB

Outputs:
    data/anomaly_report_YYYYMMDD_HHMMSS.csv   — full labelled dataset
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import logging
import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)


# ── Load from Excel / CSV file ────────────────────────────────────────────────
def load_from_file(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        log.error(f"File not found: {path}")
        sys.exit(1)

    if path.endswith(".xlsx"):
        df = pd.read_excel(path, sheet_name="All Data")
        df = df.rename(columns={
            "Timestamp":   "time",
            "Room":        "room",
            "Temperature": "temperature",
            "Humidity":    "humidity",
            "AQI":         "airquality",
            "Motion":      "motion",
        })
    else:
        df = pd.read_csv(path)

    df["time"] = pd.to_datetime(df["time"])
    df["room"] = df["room"].str.lower().str.strip()
    log.info(f"Loaded {len(df)} records from {path}")
    log.info(f"Rooms found: {df['room'].value_counts().to_dict()}")
    return df.sort_values("time").reset_index(drop=True)


# ── Load from InfluxDB ────────────────────────────────────────────────────────
def fetch_data(hours: int = 24) -> pd.DataFrame:
    try:
        from influxdb_client import InfluxDBClient
    except ImportError:
        log.error("influxdb-client not installed. Run: pip install influxdb-client")
        sys.exit(1)

    client = InfluxDBClient(
        url=cfg["influxdb"]["url"],
        token=cfg["influxdb"]["token"],
        org=cfg["influxdb"]["org"],
    )

    query = f"""
    from(bucket: "{cfg['influxdb']['bucket']}")
      |> range(start: -{hours}h)
      |> filter(fn: (r) => r["_measurement"] == "air_quality")
      |> pivot(rowKey:["_time","room"], columnKey: ["_field"], valueColumn: "_value")
      |> sort(columns: ["_time"])
    """

    try:
        api    = client.query_api()
        tables = api.query_data_frame(query, org=cfg["influxdb"]["org"])
        if isinstance(tables, list):
            df = pd.concat(tables, ignore_index=True)
        else:
            df = tables
        df = df.rename(columns={"_time": "time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
        log.info(f"Fetched {len(df)} records from InfluxDB")
        return df.sort_values("time").reset_index(drop=True)
    except Exception as e:
        log.error(f"InfluxDB query failed: {e}")
        sys.exit(1)
    finally:
        client.close()


# ── Isolation Forest ──────────────────────────────────────────────────────────
def run_isolation_forest(df: pd.DataFrame,
                          features: list = None,
                          contamination: float = 0.05) -> pd.DataFrame:
    """
    Runs Isolation Forest per room.
    contamination = expected fraction of anomalies (5% default).
    Adds column: ml_anomaly (True/False)

    Input features  : temperature, humidity, airquality
    Output          : ml_anomaly boolean per row
    Decision use    : dashboard highlights anomaly rows in red
                      VENTILATE alert if anomaly + AQI > 1500
    """
    if features is None:
        features = [c for c in ["temperature", "humidity", "airquality"]
                    if c in df.columns]

    log.info(f"Isolation Forest features: {features}")
    df = df.copy()
    df["ml_anomaly"] = False

    for room, grp in df.groupby("room"):
        X = grp[features].dropna()

        if len(X) < 10:
            log.warning(f"[{room}] Too few records ({len(X)}) — skipping ML")
            continue

        scaler   = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
        )
        preds        = model.fit_predict(X_scaled)
        anomaly_mask = preds == -1

        df.loc[X.index[anomaly_mask], "ml_anomaly"] = True

        n_anomalies = anomaly_mask.sum()
        log.info(f"[{room.upper():8}] {len(X)} records → "
                 f"{n_anomalies} anomalies ({100*n_anomalies/len(X):.1f}%)")

    return df


# ── Z-score (secondary method) ────────────────────────────────────────────────
def run_zscore(df: pd.DataFrame, threshold: float = None) -> pd.DataFrame:
    """
    Z-score anomaly detection per metric per room.
    Adds columns: temperature_z_anomaly, humidity_z_anomaly, airquality_z_anomaly
    Used alongside Isolation Forest to cross-validate findings.
    """
    if threshold is None:
        threshold = cfg["anomaly"]["z_score_threshold"]

    df      = df.copy()
    metrics = [c for c in ["temperature", "humidity", "airquality"] if c in df.columns]

    for room, grp in df.groupby("room"):
        for m in metrics:
            mean = grp[m].mean()
            std  = grp[m].std()
            if std == 0 or pd.isna(std):
                continue
            z = (grp[m] - mean).abs() / std
            df.loc[grp.index, f"{m}_z_anomaly"] = z > threshold

    return df


# ── Decision engine ───────────────────────────────────────────────────────────
def generate_decisions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Translates ML anomaly flags into actionable decisions.
    These are what a real system would act on.
    """
    df = df.copy()
    df["decision"] = "Normal"

    if "airquality" in df.columns:
        df.loc[df["ml_anomaly"] & (df["airquality"] > 1500), "decision"] = "VENTILATE NOW"
        df.loc[df["ml_anomaly"] & df["airquality"].between(500, 1500), "decision"] = "Monitor Air"

    if "temperature" in df.columns:
        df.loc[df["ml_anomaly"] & (df["temperature"] > 30), "decision"] = "Temp Alert"

    if "humidity" in df.columns:
        df.loc[df["ml_anomaly"] & (df["humidity"] > 75), "decision"] = "High Humidity"

    return df


# ── Summary report ────────────────────────────────────────────────────────────
def print_summary(df: pd.DataFrame):
    print("\n" + "=" * 65)
    print("  ML ANOMALY DETECTION — SUMMARY REPORT")
    print("=" * 65)
    print(f"  Total records analysed : {len(df)}")
    print(f"  Total ML anomalies     : {int(df['ml_anomaly'].sum())} "
          f"({100*df['ml_anomaly'].mean():.1f}%)")
    print(f"  Date range             : "
          f"{df['time'].min().strftime('%Y-%m-%d %H:%M')} → "
          f"{df['time'].max().strftime('%Y-%m-%d %H:%M')}")

    metrics = ["temperature", "humidity", "airquality"]

    for room, grp in df.groupby("room"):
        print(f"\n  📍 {room.upper()}")
        print(f"     Records     : {len(grp)}")
        print(f"     ML anomalies: {int(grp['ml_anomaly'].sum())} "
              f"({100*grp['ml_anomaly'].mean():.1f}%)")
        for m in metrics:
            if m not in grp.columns:
                continue
            z_col   = f"{m}_z_anomaly"
            z_count = int(grp[z_col].sum()) if z_col in grp.columns else 0
            print(f"     {m:13}: "
                  f"mean={grp[m].mean():.2f}  "
                  f"std={grp[m].std():.2f}  "
                  f"min={grp[m].min():.2f}  "
                  f"max={grp[m].max():.2f}  "
                  f"z_flags={z_count}")

    if "decision" in df.columns:
        decisions = df[df["decision"] != "Normal"]["decision"].value_counts()
        if not decisions.empty:
            print(f"\n  🚨 Actionable decisions triggered:")
            for dec, cnt in decisions.items():
                print(f"     {dec:20}: {cnt} times")

    print(f"\n  ML Model Info:")
    print(f"     Algorithm     : Isolation Forest (sklearn)")
    print(f"     Features      : {[c for c in metrics if c in df.columns]}")
    print(f"     Contamination : 5%")
    print(f"     Validation    : Z-score cross-check (threshold 2.5σ)")
    print("=" * 65 + "\n")


# ── Export to CSV ─────────────────────────────────────────────────────────────
def export_csv(df: pd.DataFrame) -> str:
    path = f"data/anomaly_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(path, index=False)
    log.info(f"Report exported to {path}")
    return path


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IoT ML Anomaly Detection")
    parser.add_argument("--hours", type=int, default=24,
                        help="Hours of data to fetch from InfluxDB (default: 24)")
    parser.add_argument("--csv",   type=str, default=None,
                        help="Path to Excel or CSV file — skips InfluxDB")
    parser.add_argument("--contamination", type=float, default=0.05,
                        help="Expected anomaly fraction (default: 0.05 = 5%%)")
    args = parser.parse_args()

    # Load data from file or InfluxDB
    if args.csv:
        log.info(f"Loading from file: {args.csv}")
        df = load_from_file(args.csv)
    else:
        log.info(f"Fetching last {args.hours}h from InfluxDB")
        df = fetch_data(hours=args.hours)

    if df.empty:
        log.error("No data found.")
        sys.exit(1)

    # Run ML pipeline
    df = run_isolation_forest(df, contamination=args.contamination)
    df = run_zscore(df)
    df = generate_decisions(df)

    # Output
    print_summary(df)
    path = export_csv(df)

    print(f"✅ Done.")
    print(f"   Report → {path}")
    print(f"   Open in Excel to see ml_anomaly and decision columns.")