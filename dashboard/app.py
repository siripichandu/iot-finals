"""
dashboard/app.py — Full production dashboard
Connected to real InfluxDB data.
Run: streamlit run dashboard/app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import time
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import cfg
from influxdb_client import InfluxDBClient

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Indoor Air Quality Monitor",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.kpi{background:#fff;border:1px solid #e8e8e8;border-radius:12px;padding:18px 20px 14px;margin-bottom:4px;}
.kpi-label{font-size:11px;color:#999;font-weight:500;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;}
.kpi-value{font-size:28px;font-weight:600;color:#1a1a1a;line-height:1.1;}
.kpi-sub{font-size:12px;color:#bbb;margin-top:4px;}
.kpi-trend{font-size:13px;margin-top:3px;}
.alert-warn{background:#FFF8E7;border-left:4px solid #EF9F27;color:#854F0B;padding:10px 14px;border-radius:6px;margin-bottom:6px;font-size:13px;}
.alert-crit{background:#FFF0F0;border-left:4px solid #E24B4A;color:#A32D2D;padding:10px 14px;border-radius:6px;margin-bottom:6px;font-size:13px;}
.online{background:#E6F9F0;color:#0F6E56;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:500;}
.offline{background:#FDE8E8;color:#A32D2D;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:500;}
.stale{background:#FFF3CD;color:#856404;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:500;}
.block-container{padding-top:1.5rem!important;}
</style>
""", unsafe_allow_html=True)

ROOM_COLORS = {"bedroom": "#378ADD", "kitchen": "#D85A30"}
THRESHOLDS  = cfg["thresholds"]

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Controls")
    time_range   = st.selectbox("Time range", ["1h","6h","24h","7d"], index=1)
    auto_refresh = st.checkbox("Auto-refresh", value=True)
    refresh_sec  = st.slider("Refresh every (s)", 5, 60, 10, step=5)
    st.markdown("---")
    st.caption(f"InfluxDB: {cfg['influxdb']['url']}")
    st.caption(f"Bucket  : {cfg['influxdb']['bucket']}")

# ─── Fetch from InfluxDB ──────────────────────────────────────────────────────
hours_map = {"1h":1,"6h":6,"24h":24,"7d":168}
hours     = hours_map.get(time_range, 6)

@st.cache_data(ttl=10)
def fetch(hours):
    try:
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
        api    = client.query_api()
        tables = api.query_data_frame(query, org=cfg["influxdb"]["org"])
        client.close()
        if isinstance(tables, list):
            df = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
        else:
            df = tables
        if df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"_time":"time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
        return df.sort_values("time").reset_index(drop=True)
    except Exception as e:
        st.error(f"InfluxDB error: {e}")
        return pd.DataFrame()

df = fetch(hours)

# ─── Process ──────────────────────────────────────────────────────────────────
def rolling_avg(df, window=18):
    df = df.copy()
    for room, grp in df.groupby("room"):
        for m in ["temperature","humidity","airquality"]:
            if m in df.columns:
                df.loc[grp.index, f"{m}_roll"] = (
                    grp[m].rolling(window, min_periods=1).mean().round(2))
    return df

def detect_anomaly(df):
    df = df.copy()
    for room, grp in df.groupby("room"):
        for m in ["temperature","humidity","airquality"]:
            if m not in df.columns: continue
            std = grp[m].std()
            if std == 0 or pd.isna(std):
                df.loc[grp.index, f"{m}_anom"] = False
            else:
                z = (grp[m] - grp[m].mean()).abs() / std
                df.loc[grp.index, f"{m}_anom"] = z > cfg["anomaly"]["z_score_threshold"]
    return df

def get_trend(series):
    s = series.dropna().tail(6)
    if len(s) < 2: return "stable"
    slope = np.polyfit(range(len(s)), s.values, 1)[0]
    return "↑ Rising" if slope > 0.05 else ("↓ Falling" if slope < -0.05 else "→ Stable")

def aqi_label(v):
    if v is None: return "Unknown","#888"
    if v < 300:   return "Good",   "#27A96C"
    if v < 800:   return "Moderate","#EF9F27"
    if v < 1500:  return "Poor",    "#D85A30"
    return "Hazardous","#E24B4A"

if not df.empty:
    df = rolling_avg(df)
    df = detect_anomaly(df)

rooms  = sorted(df["room"].unique().tolist()) if not df.empty else []
latest = {}
if not df.empty:
    for r, grp in df.groupby("room"):
        latest[r] = grp.sort_values("time").iloc[-1].to_dict()

# ─── Alerts ───────────────────────────────────────────────────────────────────
alerts = []
for room, r in latest.items():
    temp  = r.get("temperature")
    humid = r.get("humidity")
    aqi   = r.get("airquality")
    if temp  and temp  >= THRESHOLDS["temperature"]["alert"]:  alerts.append(("crit", f"🔴 {room.title()}: Temperature critically high ({temp}°C)"))
    elif temp and temp >= THRESHOLDS["temperature"]["warn"]:   alerts.append(("warn", f"🟡 {room.title()}: Temperature elevated ({temp}°C)"))
    if aqi   and aqi   >= THRESHOLDS["airquality"]["alert"]:   alerts.append(("crit", f"🔴 {room.title()}: Poor air quality — ventilate now (AQI {aqi})"))
    elif aqi  and aqi  >= THRESHOLDS["airquality"]["warn"]:    alerts.append(("warn", f"🟡 {room.title()}: Moderate air quality (AQI {aqi})"))
    if humid and humid >= THRESHOLDS["humidity"]["alert"]:     alerts.append(("crit", f"🔴 {room.title()}: Humidity critically high ({humid}%)"))
    elif humid and humid >= THRESHOLDS["humidity"]["high_warn"]:alerts.append(("warn", f"🟡 {room.title()}: High humidity ({humid}%)"))
    elif humid and humid <= THRESHOLDS["humidity"]["low_warn"]: alerts.append(("warn", f"🟡 {room.title()}: Air is dry ({humid}%)"))

# stale check
from datetime import timedelta
stale_rooms = []
now = datetime.utcnow()
for r, v in latest.items():
    t = v.get("time")
    if t and hasattr(t,"to_pydatetime"):
        t = t.to_pydatetime()
    if t and (now - t.replace(tzinfo=None)) > timedelta(seconds=cfg["stale_data_seconds"]):
        stale_rooms.append(r)

# ─── Header ───────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([3,1.5,1.5])
with c1:
    st.markdown("## 🏠 Indoor Air Quality Monitor")
    st.caption("IoT Capstone — Spring 2026  |  ESP32 + DHT22 + MQ-135 + PIR")
with c2:
    st.markdown("<div style='margin-top:14px'>", unsafe_allow_html=True)
    if not rooms:
        st.markdown('<span class="offline">● No data</span>', unsafe_allow_html=True)
    elif stale_rooms:
        st.markdown(f'<span class="stale">⚠ {", ".join(stale_rooms)} stale</span>', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="online">● {len(rooms)} node{"s" if len(rooms)!=1 else ""} live</span>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
with c3:
    st.markdown(f"<div style='text-align:right;color:#aaa;font-size:12px;margin-top:14px'>Updated<br><b>{datetime.now().strftime('%I:%M:%S %p')}</b></div>", unsafe_allow_html=True)

st.markdown("---")

# ─── Room filter ──────────────────────────────────────────────────────────────
selected = st.radio("Room filter", ["All"] + rooms, horizontal=True,
                    label_visibility="collapsed") if rooms else "All"
fdf     = df if selected == "All" else df[df["room"]==selected]
flatest = {k:v for k,v in latest.items() if selected=="All" or k==selected}

# ─── Alerts ───────────────────────────────────────────────────────────────────
for level, msg in alerts:
    css = "alert-crit" if level == "crit" else "alert-warn"
    st.markdown(f'<div class="{css}">{msg}</div>', unsafe_allow_html=True)

# ─── Insight bar (bigger, dark card, clearly visible) ────────────────────────
if flatest:
    parts = []
    for room, r in flatest.items():
        lbl, _ = aqi_label(r.get("airquality"))
        trend  = get_trend(df[df["room"]==room]["temperature"]) if not df.empty else "stable"
        motion = "Occupied" if r.get("motion")==1 else "Empty"
        parts.append(f"{room.title()}: {lbl} air, {r.get('temperature','?')}°C {trend}, {motion}")
    if len(flatest)==2:
        rooms_list = list(flatest.keys())
        a1 = flatest[rooms_list[0]].get("airquality",0) or 0
        a2 = flatest[rooms_list[1]].get("airquality",0) or 0
        worse = rooms_list[0] if a1 > a2 else rooms_list[1]
        parts.append(f"Worse air in {worse}")
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 10px;
        padding: 16px 22px;
        margin-bottom: 12px;
        border-left: 5px solid #378ADD;
    ">
        <div style="font-size:11px;color:#7aa3cc;font-weight:600;
                    text-transform:uppercase;letter-spacing:.08em;
                    margin-bottom:6px;">
            💡 Live Insight
        </div>
        <div style="font-size:16px;color:#ffffff;font-weight:500;
                    line-height:1.6;">
            {"<br>".join(parts)}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ─── KPI Cards ───────────────────────────────────────────────────────────────
def avg_val(key, fmt=".1f"):
    vals = [v.get(key) for v in flatest.values() if v.get(key) is not None]
    if not vals: return "—", "no data"
    avg = sum(vals)/len(vals)
    sub = list(flatest.keys())[0].title() if len(vals)==1 else f"avg {len(vals)} rooms"
    return f"{avg:{fmt}}", sub

def kpi(label, value, unit, sub, trend="", color="#1a1a1a"):
    tc = {"↑ Rising":"#E24B4A","↓ Falling":"#378ADD","→ Stable":"#888"}.get(trend,"#888")
    t  = f'<div class="kpi-trend" style="color:{tc}">{trend}</div>' if trend else ""
    return f"""<div class="kpi"><div class="kpi-label">{label}</div>
    <div class="kpi-value" style="color:{color}">{value}<span style="font-size:16px;color:#bbb;font-weight:400"> {unit}</span></div>
    <div class="kpi-sub">{sub}</div>{t}</div>"""

k1,k2,k3,k4 = st.columns(4)
tv,ts = avg_val("temperature")
hv,hs = avg_val("humidity")

# FIXED: ignore NaN airquality values before converting to int
aqi_vals_list = [
    v.get("airquality")
    for v in flatest.values()
    if v.get("airquality") is not None and not pd.isna(v.get("airquality"))
]
av   = str(int(sum(aqi_vals_list)/len(aqi_vals_list))) if aqi_vals_list else "—"

albl, acol = aqi_label(int(av) if av != "—" else None)
motion_rooms = [r for r,v in flatest.items() if v.get("motion")==1]
mv   = "Detected" if motion_rooms else "Clear"
ms   = ", ".join([r.title() for r in motion_rooms]) if motion_rooms else "No motion"
mc   = "#D85A30" if motion_rooms else "#27A96C"
tt   = get_trend(fdf["temperature"]) if not fdf.empty and "temperature" in fdf.columns else ""

with k1: st.markdown(kpi("Temperature", tv, "°C", ts, trend=tt), unsafe_allow_html=True)
with k2: st.markdown(kpi("Humidity", hv, "%", hs), unsafe_allow_html=True)
with k3: st.markdown(kpi("Air Quality", av, "AQI", f"{albl} · {ts}", color=acol), unsafe_allow_html=True)
with k4: st.markdown(kpi("Motion", mv, "", ms, color=mc), unsafe_allow_html=True)

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# ─── Charts ───────────────────────────────────────────────────────────────────
if not fdf.empty:
    TMPL = "plotly_white"
    GC   = "rgba(0,0,0,0.06)"

    # Temperature + Humidity
    st.markdown("#### 📈 Temperature & Humidity")
    fig = go.Figure()
    for room in (fdf["room"].unique() if selected=="All" else [selected]):
        rdf = fdf[fdf["room"]==room].sort_values("time")
        col = ROOM_COLORS.get(room,"#888")
        fig.add_trace(go.Scatter(x=rdf["time"], y=rdf["temperature"],
            name=f"{room.title()} Temp", line=dict(color=col,width=2),
            hovertemplate="%{y:.1f}°C"))
        if "temperature_roll" in rdf.columns:
            fig.add_trace(go.Scatter(x=rdf["time"], y=rdf["temperature_roll"],
                name=f"{room.title()} Avg", line=dict(color=col,width=1.5,dash="dot"),
                opacity=0.6, hovertemplate="%{y:.1f}°C"))
        fig.add_trace(go.Scatter(x=rdf["time"], y=rdf["humidity"],
            name=f"{room.title()} Humid", line=dict(color=col,width=2,dash="dash"),
            yaxis="y2", hovertemplate="%{y:.1f}%"))
    fig.update_layout(template=TMPL, height=320, margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(title="Temp (°C)",showgrid=True,gridcolor=GC),
        yaxis2=dict(title="Humidity (%)",overlaying="y",side="right",showgrid=False),
        legend=dict(orientation="h",y=1.08), hovermode="x unified",
        plot_bgcolor="white",paper_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})

    # Air Quality
    st.markdown("#### 💨 Air Quality")
    fig2 = go.Figure()
    fig2.add_hrect(y0=0,   y1=300,  fillcolor="#27A96C",opacity=0.06,line_width=0,annotation_text="Good",    annotation_position="left")
    fig2.add_hrect(y0=300, y1=800,  fillcolor="#EF9F27",opacity=0.06,line_width=0,annotation_text="Moderate",annotation_position="left")
    fig2.add_hrect(y0=800, y1=1500, fillcolor="#D85A30",opacity=0.06,line_width=0,annotation_text="Poor",    annotation_position="left")
    fig2.add_hrect(y0=1500,y1=4096, fillcolor="#E24B4A",opacity=0.06,line_width=0,annotation_text="Hazardous",annotation_position="left")
    for room in (fdf["room"].unique() if selected=="All" else [selected]):
        rdf = fdf[fdf["room"]==room].sort_values("time")
        if "airquality" not in rdf.columns: continue
        col = ROOM_COLORS.get(room,"#888")
        fig2.add_trace(go.Scatter(x=rdf["time"],y=rdf["airquality"],
            name=room.title(),line=dict(color=col,width=2),
            fill="tozeroy",fillcolor="rgba(55,138,221,0.10)",hovertemplate="%{y} AQI"))
        if "airquality_anom" in rdf.columns:
            anom = rdf[rdf["airquality_anom"]==True]
            if not anom.empty:
                fig2.add_trace(go.Scatter(x=anom["time"],y=anom["airquality"],
                    mode="markers",name=f"{room.title()} Anomaly",
                    marker=dict(color="#E24B4A",size=9,symbol="x"),
                    hovertemplate="⚠ %{y} AQI"))
    fig2.update_layout(template=TMPL,height=300,margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(title="AQI (raw)",showgrid=True,gridcolor=GC),
        legend=dict(orientation="h",y=1.08),hovermode="x unified",
        plot_bgcolor="white",paper_bgcolor="white")
    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar":False})

    # Motion + Comparison
    cm, cc = st.columns(2)
    with cm:
        st.markdown("#### 🚶 Motion / Occupancy")
        fig3 = go.Figure()
        for room in (fdf["room"].unique() if selected=="All" else [selected]):
            rdf = fdf[fdf["room"]==room].sort_values("time")
            if "motion" not in rdf.columns: continue
            col = ROOM_COLORS.get(room,"#888")
            fig3.add_trace(go.Scatter(x=rdf["time"],y=rdf["motion"],
                name=room.title(),line=dict(color=col,width=1.5,shape="hv"),
                fill="tozeroy",fillcolor="rgba(55,138,221,0.13)"))
        fig3.update_layout(template=TMPL,height=220,margin=dict(l=10,r=10,t=30,b=10),
            yaxis=dict(tickvals=[0,1],ticktext=["Empty","Occupied"],showgrid=True,gridcolor=GC),
            legend=dict(orientation="h",y=1.08),plot_bgcolor="white",paper_bgcolor="white")
        st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar":False})

    with cc:
        st.markdown("#### 🏠 Room Comparison")
        if len(rooms) < 2:
            st.info("Appears automatically when kitchen node starts publishing.", icon="ℹ️")
        else:
            mp = st.selectbox("Metric",["temperature","humidity","airquality"],
                              label_visibility="collapsed")
            rows = []
            for r, grp in df.groupby("room"):
                if mp in grp.columns:
                    rows.append({"room":r.title(),"min":grp[mp].min(),
                                 "mean":grp[mp].mean(),"max":grp[mp].max()})
            if rows:
                cdf = pd.DataFrame(rows)
                cols_r = [ROOM_COLORS.get(r.lower(),"#888") for r in cdf["room"]]
                fig4 = go.Figure()
                fig4.add_trace(go.Bar(x=cdf["room"],y=cdf["mean"],
                    name="Mean",marker_color=cols_r,
                    text=cdf["mean"].round(1),textposition="outside"))
                fig4.add_trace(go.Scatter(x=cdf["room"],y=cdf["min"],
                    mode="markers",name="Min",
                    marker=dict(color="gray",size=8,symbol="line-ew-open",line_width=2)))
                fig4.add_trace(go.Scatter(x=cdf["room"],y=cdf["max"],
                    mode="markers",name="Max",
                    marker=dict(color="#333",size=8,symbol="line-ew-open",line_width=2)))
                fig4.update_layout(template=TMPL,height=220,
                    margin=dict(l=10,r=10,t=30,b=10),
                    plot_bgcolor="white",paper_bgcolor="white",
                    legend=dict(orientation="h",y=1.08))
                st.plotly_chart(fig4,use_container_width=True,
                                config={"displayModeBar":False})

    # Stats table
    st.markdown("#### 📊 Summary Statistics")
    stat_rows = []
    for room, grp in df.groupby("room"):
        if selected != "All" and room != selected: continue
        for m in ["temperature","humidity","airquality"]:
            if m in grp.columns:
                stat_rows.append({
                    "Room":room.title(),"Metric":m.title(),
                    "Min":round(grp[m].min(),2),"Mean":round(grp[m].mean(),2),
                    "Max":round(grp[m].max(),2),"Std":round(grp[m].std(),2),
                })
    if stat_rows:
        st.dataframe(pd.DataFrame(stat_rows),use_container_width=True,hide_index=True)

    # Raw data
    with st.expander("🗃️ Recent raw data (last 20 records)"):
        show = fdf.sort_values("time",ascending=False).head(20).copy()
        show["time"] = show["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        cols = [c for c in ["time","room","temperature","humidity","airquality","motion"] if c in show.columns]
        st.dataframe(show[cols],use_container_width=True,hide_index=True)

else:
    st.info("⏳ Waiting for data from InfluxDB. Make sure subscriber.py is running.", icon="⏳")

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
anom_count = int(df["airquality_anom"].sum()) if not df.empty and "airquality_anom" in df.columns else 0
f1,f2,f3,f4 = st.columns(4)
f1.metric("Total records", f"{len(df):,}" if not df.empty else "0")
f2.metric("Active rooms",  len(rooms))
f3.metric("Active alerts", len(alerts))
f4.metric("Anomalies",     anom_count)

# ─── Auto-refresh without full page reload ────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()