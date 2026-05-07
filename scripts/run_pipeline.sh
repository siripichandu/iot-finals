#!/bin/bash
# run_pipeline.sh — starts the full IoT pipeline
# Usage: bash scripts/run_pipeline.sh

echo "Starting IoT Pipeline..."
echo ""

# start services
brew services start mosquitto 2>/dev/null
echo "✅ Mosquitto broker started"

brew services start influxdb 2>/dev/null
echo "✅ InfluxDB started"

# activate venv
source venv/bin/activate

# start subscriber in background
echo ""
echo "Starting subscriber..."
python src/subscriber.py &
SUBSCRIBER_PID=$!
echo "✅ Subscriber running (PID $SUBSCRIBER_PID)"

# start dashboard in background
echo ""
echo "Starting dashboard..."
streamlit run dashboard/app.py &
DASHBOARD_PID=$!
echo "✅ Dashboard running at http://localhost:8501"

echo ""
echo "Everything is running. Press Ctrl+C to stop all."

# wait and catch Ctrl+C to kill both
trap "kill $SUBSCRIBER_PID $DASHBOARD_PID; echo 'Pipeline stopped.'; exit" INT
wait
