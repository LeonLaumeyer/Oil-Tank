import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

def main():
    print("Fetching 3 years of ^OVX data...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1095)
    
    data = yf.download("^OVX", start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
    
    if data.empty:
        print("Failed to fetch ^OVX data.")
        return
        
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    points = []
    
    closes = data['Close']['^OVX']
    
    for date, value in closes.items():
        if pd.isna(value):
            continue
            
        point = Point("daily_metrics") \
            .tag("location", "Adelschlag") \
            .field("oil_market_mood_ovx", float(value)) \
            .time(date.strftime("%Y-%m-%dT12:00:00Z"))
            
        points.append(point)
        
    print(f"Writing {len(points)} points to InfluxDB...")
    write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=points)
    print("Done!")

if __name__ == "__main__":
    main()
