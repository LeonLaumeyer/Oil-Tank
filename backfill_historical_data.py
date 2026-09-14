from PIL import GimpGradientFile
import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

# Adelschlag coordinates
LATITUDE = 48.8333
LONGITUDE = 11.2167

DRY_RUN = False  

def fetch_weather_data(start_date: str, end_date: str) -> pd.DataFrame:
    print(f"Fetching historical weather data from {start_date} to {end_date}...")
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": start_date,
        "end_date": end_date,
        "daily": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"],
        "timezone": "Europe/Berlin"
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    daily_data = data['daily']
    df = pd.DataFrame({
        'time': pd.to_datetime(daily_data['time']),
        'temp_max': daily_data['temperature_2m_max'],
        'temp_min': daily_data['temperature_2m_min'],
        'temp_mean': daily_data['temperature_2m_mean']
    })
    df.set_index('time', inplace=True)
    return df

def fetch_financial_data(start_date: str, end_date: str) -> pd.DataFrame:
    print(f"Fetching financial data (Oil & Forex) from {start_date} to {end_date}...")
    end_date_yf = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # BZ=F (Brent Crude), HO=F (Heating Oil), EUR=X (USD to EUR rate)
    data = yf.download(["BZ=F", "HO=F", "EUR=X"], start=start_date, end=end_date_yf)
    
    closing_prices = pd.DataFrame({
        'Brent_Crude_USD': data['Close']['BZ=F'],
        'Heating_Oil_USD_per_Gallon': data['Close']['HO=F'],
        'EUR_Exchange_Rate': data['Close']['EUR=X']
    })
    
    closing_prices.ffill(inplace=True)
    
    closing_prices['Heating_Oil_EUR_per_100L'] = (closing_prices['Heating_Oil_USD_per_Gallon'] / 3.78541) * closing_prices['EUR_Exchange_Rate'] * 100
    
    return closing_prices

def write_to_influxdb(df: pd.DataFrame):
    print(f"Connecting to InfluxDB at {INFLUXDB_URL}...")
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    print(f"Writing {len(df)} rows to InfluxDB bucket '{INFLUXDB_BUCKET}'...")
    
    for index, row in df.iterrows():
        point = {
            "measurement": "daily_metrics", 
            "tags": {
                "location": "Adelschlag"
            },
            "time": index.isoformat() + "Z", 
            "fields": {
                "temp_max": float(row['temp_max']) if pd.notnull(row.get('temp_max')) else None,
                "temp_min": float(row['temp_min']) if pd.notnull(row.get('temp_min')) else None,
                "temp_mean": float(row['temp_mean']) if pd.notnull(row.get('temp_mean')) else None,
                "brent_crude_usd": float(row['Brent_Crude_USD']) if pd.notnull(row.get('Brent_Crude_USD')) else None,
                "heating_oil_eur_per_100l": float(row['Heating_Oil_EUR_per_100L']) if pd.notnull(row.get('Heating_Oil_EUR_per_100L')) else None,
            }
        }
        point["fields"] = {k: v for k, v in point["fields"].items() if v is not None}
        
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
    
    print("Done!")

def main():
    start_date = "2023-01-01"
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = yesterday
    
    weather_df = fetch_weather_data(start_date, end_date)
    
    finance_df = fetch_financial_data(start_date, end_date)
    
    weather_df.index = weather_df.index.tz_localize(None)
    finance_df.index = finance_df.index.tz_localize(None)
    
    final_df = weather_df.join(finance_df, how='left')
    final_df.bfill(inplace=True)
    
    print("\n--- Final Merged Data Preview ---")
    print(final_df[['temp_mean', 'Brent_Crude_USD', 'Heating_Oil_EUR_per_100L']].head())
    print("...")
    print(final_df[['temp_mean', 'Brent_Crude_USD', 'Heating_Oil_EUR_per_100L']].tail())
    print("---------------------------------\n")
    
    if DRY_RUN:
        print("DRY_RUN is True. Skipping InfluxDB injection.")
    else:
        if not all([INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET]):
            print("ERROR: Missing InfluxDB credentials! Please fill out the .env file.")
            return
        write_to_influxdb(final_df)

if __name__ == "__main__":
    main()
