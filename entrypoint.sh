#!/bin/bash

echo "Running initial daily data fetch..."
python daily_update.py

(
    while true; do
        sleep 86400
        echo "Running scheduled daily data fetch..."
        python daily_update.py
    done
) &

echo "Starting Streamlit dashboard..."
exec streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0
