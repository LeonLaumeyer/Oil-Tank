import os
import argparse
import pandas as pd
import numpy as np
from datetime import timedelta
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from xgboost import XGBRegressor

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

BASE_TEMP_C = 18.0

def get_historical_data() -> pd.DataFrame:
    print("Fetching historical data from InfluxDB...")
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=30000)
    query_api = client.query_api()
    
    query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
          |> range(start: -3y)
          |> filter(fn: (r) => r["_measurement"] == "daily_metrics")
          |> filter(fn: (r) => r["_field"] == "temp_mean" or 
                               r["_field"] == "temp_max" or 
                               r["_field"] == "temp_min" or 
                               r["_field"] == "liters_consumed" or
                               r["_field"] == "tank_level_liters")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    
    df = query_api.query_data_frame(org=INFLUXDB_ORG, query=query)
    
    if isinstance(df, list):
        if len(df) == 0:
            return pd.DataFrame()
        df = pd.concat(df)
        
    if df.empty:
        return df

    cols_to_keep = ['_time']
    for col in ['temp_mean', 'temp_max', 'temp_min', 'liters_consumed', 'tank_level_liters']:
        if col in df.columns:
            cols_to_keep.append(col)
            
    df = df[cols_to_keep].copy()
    df.rename(columns={'_time': 'time'}, inplace=True)
    df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    
    df['month_day'] = df.index.strftime('%m-%d')
    
    if 'temp_mean' in df.columns:
        df['hdd'] = df['temp_mean'].apply(lambda t: max(0.0, BASE_TEMP_C - t) if pd.notnull(t) else 0.0)
    else:
        df['hdd'] = 0.0
        
    return df

def generate_synthetic_weather(df: pd.DataFrame, days_ahead: int = 90) -> pd.DataFrame:
    daily_avg = df.groupby('month_day')[['temp_mean', 'temp_max', 'temp_min']].mean()
    
    last_date = df.index[-1]
    future_dates = [last_date + timedelta(days=i) for i in range(1, days_ahead + 1)]
    
    synth_df = pd.DataFrame({'date': future_dates})
    synth_df.set_index('date', inplace=True)
    synth_df['month_day'] = synth_df.index.strftime('%m-%d')
    
    synth_df = synth_df.join(daily_avg, on='month_day')
    
    synth_df['hdd'] = synth_df['temp_mean'].apply(lambda t: max(0.0, BASE_TEMP_C - t) if pd.notnull(t) else 0.0)
    
    return synth_df

def main():
    parser = argparse.ArgumentParser(description="Predict 3-Month Oil Consumption.")
    parser.add_argument("--days", type=int, default=90, help="Number of days to predict")
    args = parser.parse_args()
    
    df = get_historical_data()
    if df.empty:
        print("No historical data found in InfluxDB.")
        return
        
    if 'tank_level_liters' in df.columns:
        valid_tank_levels = df['tank_level_liters'].dropna()
        if len(valid_tank_levels) > 0:
            current_tank_level = valid_tank_levels.iloc[-1]
        else:
            print("No tank level data found. Cannot calculate Zero Liter Date.")
            return
    else:
        print("tank_level_liters field missing in InfluxDB. Cannot calculate Zero Liter Date.")
        return

    print(f"Current Tank Level: {current_tank_level:.2f} Liters")
    
def predict_future_consumption(df: pd.DataFrame, current_tank_level: float, days_ahead: int = 90) -> pd.DataFrame:
    features = ['temp_mean', 'temp_max', 'temp_min', 'hdd']
    if not all(col in df.columns for col in features + ['liters_consumed']):
        print(f"Missing required columns. Found: {list(df.columns)}")
        return pd.DataFrame()
        
    train_df = df.dropna(subset=features + ['liters_consumed'])
    if len(train_df) == 0:
        print("No valid training rows found (missing values).")
        return pd.DataFrame()
        
    X = train_df[features]
    y = train_df['liters_consumed']
    
    print(f"Training XGBoost model on {len(train_df)} days of historical data...")
    model = XGBRegressor(n_estimators=100, learning_rate=0.1, max_depth=4, random_state=42)
    model.fit(X, y)
    
    print(f"Generating synthetic {days_ahead}-day weather forecast...")
    synth_weather = generate_synthetic_weather(df, days_ahead=days_ahead)
    
    synth_weather[features] = synth_weather[features].ffill().bfill()
    
    print("Predicting daily consumption...")
    X_pred = synth_weather[features]
    predicted_consumption = model.predict(X_pred)
    
    predicted_consumption = np.maximum(predicted_consumption, 0)
    synth_weather['predicted_liters_consumed'] = predicted_consumption
    
    tank_level_series = []
    current_level = current_tank_level
    zero_liter_date = None
    
    for date, row in synth_weather.iterrows():
        current_level -= row['predicted_liters_consumed']
        tank_level_series.append(current_level)
        if current_level <= 0 and zero_liter_date is None:
            zero_liter_date = date
            
    synth_weather['projected_tank_level'] = tank_level_series
    
    return synth_weather

def main():
    parser = argparse.ArgumentParser(description="Predict 3-Month Oil Consumption.")
    parser.add_argument("--days", type=int, default=90, help="Number of days to predict")
    args = parser.parse_args()
    
    df = get_historical_data()
    if df.empty:
        print("No historical data found in InfluxDB.")
        return
        
    if 'tank_level_liters' in df.columns:
        valid_tank_levels = df['tank_level_liters'].dropna()
        if len(valid_tank_levels) > 0:
            current_tank_level = valid_tank_levels.iloc[-1]
        else:
            print("No tank level data found. Cannot calculate Zero Liter Date.")
            return
    else:
        print("tank_level_liters field missing in InfluxDB. Cannot calculate Zero Liter Date.")
        return

    print(f"Current Tank Level: {current_tank_level:.2f} Liters")
    
    synth_weather = predict_future_consumption(df, current_tank_level, args.days)
    if synth_weather.empty:
        return
        
    zero_liter_date = None
    if (synth_weather['projected_tank_level'] <= 0).any():
        zero_liter_date = synth_weather[synth_weather['projected_tank_level'] <= 0].index[0]

    total_consumption = synth_weather['predicted_liters_consumed'].sum()
    
    print("\n=======================================================")
    print(f" PREDICTED OIL CONSUMPTION FOR NEXT {args.days} DAYS")
    print("=======================================================")
    
    print("\nNext 7 Days Preview:")
    preview = synth_weather.head(7)[['temp_mean', 'predicted_liters_consumed', 'projected_tank_level']]
    print(preview.round(2).to_string())
    
    if zero_liter_date:
        print(f"\n[ALERT] ZERO LITER DATE PREDICTED: {zero_liter_date.strftime('%Y-%m-%d')}")
    else:
        print(f"\n[OK] Tank will not empty in the next {args.days} days.")
    print("=======================================================")

if __name__ == "__main__":
    main()
