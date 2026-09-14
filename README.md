# 🛢️ Heating Oil Tank Advisor (OilTank-Advisor)

An intelligent, AI-powered dashboard that tracks your heating oil consumption, predicts future prices, and advises you on the optimal time to refill your tank to maximize savings.

This project is designed to run continuously as a container, fetching new market and weather data daily, and presenting an easy-to-read overview via a Streamlit web interface.

## ✨ Features

- **Tank Level Tracking:** Monitors the current level of your heating oil tank (via InfluxDB).
- **Consumption Forecasting:** Uses machine learning models to predict future oil consumption based on synthetic weather forecasts and historical heating degree days (HDD).
- **Price Forecasting:** Utilizes Prophet (univariate and multivariate) and Linear Regression to predict future local and global heating oil prices up to 90 days in advance.
- **AI-Powered Advice:** Generates personalized, natural language recommendations on whether to buy oil now or wait for better prices, powered by the Google Gemini API.
- **Interactive Dashboard:** A beautiful Streamlit dashboard to visualize historical data, tank depletion timelines, price forecasts, and the "fear index" of the oil market (OVX).

## 🏗️ Architecture

- **Web Dashboard:** Streamlit
- **Machine Learning / AI:** Prophet, XGBoost, Scikit-Learn, Google GenAI
- **Database:** InfluxDB (stores raw tank readings, weather data, and market metrics)

## 🚀 Setup & Installation

### Option 1: Docker / Unraid (Recommended)

This project is fully containerized and a template is provided for easy deployment on Unraid.
You can pull the latest image from: `ghcr.io/leonlaumeyer/oil-tank:latest`

**Required Environment Variables:**
- `INFLUXDB_URL`: The URL to your InfluxDB instance (e.g., `http://192.168.X.X:8086`).
- `INFLUXDB_TOKEN`: Your InfluxDB API token.
- `INFLUXDB_ORG`: Your InfluxDB Organization.
- `INFLUXDB_BUCKET`: The bucket used for time-series metrics (ML and weather data).
- `INFLUXDB_BUCKET_RAW`: The bucket where raw tank readings are written (e.g., from Home Assistant sensors).
- `GEMINI_API_KEY`: (Optional) Your Google Gemini API key to enable AI-generated summaries and advice.

The container exposes port `8501` for the Streamlit web dashboard.

### Option 2: Local Python Execution

1. Clone the repository.
2. Install the required system dependencies (like `build-essential` for Prophet) and Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your `.env` file in the project root with the environment variables listed above.
4. Run the daily update loop and dashboard via the entrypoint script:
   ```bash
   ./entrypoint.sh
   ```
   Or run them manually:
   ```bash
   python daily_update.py
   streamlit run dashboard.py
   ```

## ⏪ Backfilling Historical Data

If you have historical data or want to populate the database with past market and weather data for better ML training, you can use the included backfill scripts:
- `backfill_historical_data.py`: Fetches past financial and weather data.
- `backfill_usage.py`: Synthesizes past oil consumption based on historical temperatures and heating degree days.
- `backfill_ovx.py`: Fetches historical CBOE Crude Oil Volatility Index (OVX) data.

*(Note: Review and adjust the parameters inside these scripts before running them.)*
