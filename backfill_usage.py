import os
import argparse
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

TOTAL_YEARLY_LITERS = 4000.0
DAILY_HOT_WATER_LITERS = 2.0
HEATING_YEARLY_LITERS = TOTAL_YEARLY_LITERS - (DAILY_HOT_WATER_LITERS * 365)
BASE_TEMP_C = 18.0

DRY_RUN = True

def get_historical_temp() -> pd.DataFrame:
    print("Fetching historical temp_mean from InfluxDB...")
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    query_api = client.query_api()
    
    query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
          |> range(start: 0)
          |> filter(fn: (r) => r["_measurement"] == "daily_metrics")
          |> filter(fn: (r) => r["_field"] == "temp_mean")
    '''
    
    df = query_api.query_data_frame(org=INFLUXDB_ORG, query=query)
    
    if isinstance(df, list):
        if len(df) == 0:
            print("No data found in InfluxDB.")
            return pd.DataFrame()
        df = pd.concat(df)
        
    if df.empty:
        print("No data found in InfluxDB.")
        return df

    df = df[['_time', '_value']].copy()
    df.rename(columns={'_time': 'time', '_value': 'temp_mean'}, inplace=True)
    
    df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    
    return df

def calculate_consumption(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    df['hdd'] = df['temp_mean'].apply(lambda temp: max(0.0, BASE_TEMP_C - temp))
    
    df['year'] = df.index.year
    df['liters_consumed'] = 0.0
    
    for year in df['year'].unique():
        year_mask = df['year'] == year
        total_hdd_for_year = df.loc[year_mask, 'hdd'].sum()
        pass

    total_days = len(df)
    years_in_dataset = total_days / 365.25
    
    total_heating_liters_expected = HEATING_YEARLY_LITERS * years_in_dataset
    total_hdd_in_dataset = df['hdd'].sum()
    
    liters_per_hdd = total_heating_liters_expected / total_hdd_in_dataset
    
    df['liters_consumed'] = (df['hdd'] * liters_per_hdd) + DAILY_HOT_WATER_LITERS
    
    print(f"\n--- Synthetic Consumption Stats ---")
    print(f"Total Years in Dataset: {years_in_dataset:.2f}")
    print(f"Liters burned per HDD: {liters_per_hdd:.3f}")
    print(f"Average Liters per Year: {df['liters_consumed'].sum() / years_in_dataset:.2f} L")
    print(f"Max Single Day Consumption: {df['liters_consumed'].max():.2f} L")
    print(f"Min Single Day Consumption: {df['liters_consumed'].min():.2f} L")
    
    return df

def write_to_influxdb(df: pd.DataFrame):
    print(f"\nConnecting to InfluxDB at {INFLUXDB_URL}...")
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    print(f"Writing {len(df)} points to InfluxDB bucket '{INFLUXDB_BUCKET}'...")
    
    for index, row in df.iterrows():
        point = {
            "measurement": "daily_metrics", 
            "tags": {
                "location": "Adelschlag"
            },
            "time": index.isoformat() + "Z", 
            "fields": {
                "liters_consumed": float(row['liters_consumed'])
            }
        }
        
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
    
    print("Done!")

def main():
    parser = argparse.ArgumentParser(description="Backfill synthetic consumption data.")
    parser.add_argument("--commit", action="store_true", help="Actually write to the database (disables DRY_RUN).")
    args = parser.parse_args()
    
    global DRY_RUN
    if args.commit:
        DRY_RUN = False
        
    df = get_historical_temp()
    if df.empty:
        return
        
    df_calc = calculate_consumption(df)
    
    print("\nPreview of Summer Day (low consumption):")
    print(df_calc.sort_values('temp_mean', ascending=False).head(3)[['temp_mean', 'hdd', 'liters_consumed']])
    
    print("\nPreview of Winter Day (high consumption):")
    print(df_calc.sort_values('temp_mean', ascending=True).head(3)[['temp_mean', 'hdd', 'liters_consumed']])
    
    if DRY_RUN:
        print("\nDRY_RUN is True. Skipping InfluxDB injection.")
        print("Run with --commit to write the data.")
    else:
        write_to_influxdb(df_calc)

if __name__ == "__main__":
    main()
