#!/bin/bash
# run_pipeline.sh — starts the subscriber in background
# Usage: bash scripts/run_pipeline.sh

echo "Starting IoT Pipeline..."
echo "Press Ctrl+C to stop"
echo ""

# make sure mosquitto is running
brew services start mosquitto 2>/dev/null
echo "✅ Mosquitto broker started"

# activate venv
source venv/bin/activate

# start subscriber
python src/subscriber.py
