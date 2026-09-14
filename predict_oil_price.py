import os
import argparse
import pandas as pd
import numpy as np
from datetime import timedelta
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from prophet import Prophet
from sklearn.linear_model import LinearRegression

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

def get_historical_data() -> pd.DataFrame:
    print("Fetching historical data from InfluxDB...")
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=30000)
    query_api = client.query_api()
    
    query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
          |> range(start: -3y)
          |> filter(fn: (r) => r["_measurement"] == "daily_metrics")
          |> filter(fn: (r) => r["_field"] == "heating_oil_eur_per_100l" or r["_field"] == "brent_crude_usd" or r["_field"] == "local_heating_oil_eur_per_100l" or r["_field"] == "oil_market_mood_ovx")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
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

    cols = ['_time', 'heating_oil_eur_per_100l', 'brent_crude_usd']
    if 'local_heating_oil_eur_per_100l' in df.columns:
        cols.append('local_heating_oil_eur_per_100l')
    if 'oil_market_mood_ovx' in df.columns:
        cols.append('oil_market_mood_ovx')
        
    df = df[cols].copy()
    df.rename(columns={'_time': 'time'}, inplace=True)
    df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    
    df.ffill(inplace=True)
    
    df = df.resample('D').last().ffill()
    
    df.dropna(subset=['heating_oil_eur_per_100l', 'brent_crude_usd'], inplace=True)
    
    return df

def predict_prophet_univariate(df: pd.DataFrame, days_ahead: int = 90) -> pd.DataFrame:
    print("\nTraining Univariate Prophet Model...")
    pdf = df.reset_index()[['time', 'heating_oil_eur_per_100l']].rename(columns={'time': 'ds', 'heating_oil_eur_per_100l': 'y'})
    
    model = Prophet(daily_seasonality=False, yearly_seasonality=True, weekly_seasonality=True)
    model.fit(pdf)
    
    future = model.make_future_dataframe(periods=days_ahead)
    forecast = model.predict(future)
    
    future_forecast = forecast.tail(days_ahead)[['ds', 'yhat']].rename(columns={'ds': 'date', 'yhat': 'prophet_univariate'})
    return future_forecast.set_index('date')

def predict_prophet_multivariate(df: pd.DataFrame, days_ahead: int = 90) -> pd.DataFrame:
    print("Training Multivariate Prophet Model...")
    
    print(" -> First, forecasting Brent Crude...")
    pdf_brent = df.reset_index()[['time', 'brent_crude_usd']].rename(columns={'time': 'ds', 'brent_crude_usd': 'y'})
    brent_model = Prophet(daily_seasonality=False, yearly_seasonality=True, weekly_seasonality=True)
    brent_model.fit(pdf_brent)
    brent_future = brent_model.make_future_dataframe(periods=days_ahead)
    brent_forecast = brent_model.predict(brent_future)
    
    print(" -> Second, forecasting Oil Market Mood (OVX)...")
    if 'oil_market_mood_ovx' in df.columns:
        pdf_ovx = df.reset_index()[['time', 'oil_market_mood_ovx']].dropna().rename(columns={'time': 'ds', 'oil_market_mood_ovx': 'y'})
        ovx_model = Prophet(daily_seasonality=False, yearly_seasonality=True, weekly_seasonality=True)
        ovx_model.fit(pdf_ovx)
        ovx_future = ovx_model.make_future_dataframe(periods=days_ahead)
        ovx_forecast = ovx_model.predict(ovx_future)
    else:
        ovx_forecast = None
    
    print(" -> Now forecasting Heating Oil using predicted regressors...")
    
    pdf_cols = ['time', 'heating_oil_eur_per_100l', 'brent_crude_usd']
    if 'oil_market_mood_ovx' in df.columns:
        pdf_cols.append('oil_market_mood_ovx')
        
    pdf_oil = df.reset_index()[pdf_cols].rename(columns={'time': 'ds', 'heating_oil_eur_per_100l': 'y'})
    pdf_oil.dropna(inplace=True)
    
    oil_model = Prophet(daily_seasonality=False, yearly_seasonality=True, weekly_seasonality=True)
    oil_model.add_regressor('brent_crude_usd')
    
    if ovx_forecast is not None:
        oil_model.add_regressor('oil_market_mood_ovx')
        
    oil_model.fit(pdf_oil)
    
    oil_future = oil_model.make_future_dataframe(periods=days_ahead)
    oil_future['brent_crude_usd'] = brent_forecast['yhat']
    
    if ovx_forecast is not None:
        oil_future['oil_market_mood_ovx'] = ovx_forecast['yhat']
        
    oil_forecast = oil_model.predict(oil_future)
    
    future_forecast = oil_forecast.tail(days_ahead)[['ds', 'yhat']].rename(columns={'ds': 'date', 'yhat': 'prophet_multivariate'})
    return future_forecast.set_index('date')

def predict_linear_regression(df: pd.DataFrame, days_ahead: int = 90) -> pd.DataFrame:
    print("Training Linear Regression Model...")
    
    lr_df = df.copy()
    lr_df['day_index'] = (lr_df.index - lr_df.index.min()).days
    
    y = lr_df['heating_oil_eur_per_100l'].values
    X = lr_df[['day_index']].values
    
    model = LinearRegression()
    model.fit(X, y)
    
    last_day_index = lr_df['day_index'].iloc[-1]
    future_indices = np.array([[last_day_index + i] for i in range(1, days_ahead + 1)])
    predictions = model.predict(future_indices)
    
    dates = [lr_df.index[-1] + timedelta(days=i) for i in range(1, days_ahead + 1)]
    future_forecast = pd.DataFrame({'date': dates, 'linear_regression': predictions})
    return future_forecast.set_index('date')

def main():
    parser = argparse.ArgumentParser(description="Predict future oil prices.")
    parser.add_argument("--days", type=int, default=90, help="Number of days to predict")
    args = parser.parse_args()
    
    df = get_historical_data()
    if df.empty:
        print("Cannot proceed without historical data.")
        return
        
    print(f"Loaded {len(df)} days of historical data.")
    
    uni_df = predict_prophet_univariate(df, days_ahead=args.days)
    
    multi_df = predict_prophet_multivariate(df, days_ahead=args.days)
    
    lr_df = predict_linear_regression(df, days_ahead=args.days)
    
    final_df = uni_df.join(multi_df).join(lr_df)
    
    print("\n=======================================================")
    print(f" PREDICTED HEATING OIL PRICES (EUR/100L) FOR NEXT {args.days} DAYS")
    print("=======================================================")
    print(final_df.round(2).to_string())
    print("=======================================================")
    print("Summary:")
    print(f"Current Price (last known): {df['heating_oil_eur_per_100l'].iloc[-1]:.2f}")
    print(f"Prophet Univariate End Price: {final_df['prophet_univariate'].iloc[-1]:.2f}")
    print(f"Prophet Multivariate End Price: {final_df['prophet_multivariate'].iloc[-1]:.2f}")
    print(f"Linear Regression End Price: {final_df['linear_regression'].iloc[-1]:.2f}")
    
if __name__ == "__main__":
    main()
