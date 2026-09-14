import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google import genai
from google.genai import types
import warnings

warnings.filterwarnings('ignore')

import predict_oil_price
import predict_consumption

load_dotenv()

LOOK_THRESHOLD_LITERS = 4000.0
MINIMUM_TANK_LITERS = 1000.0
EVAL_DAYS = 30
FORECAST_DAYS = 90

def calculate_mae(actual, predicted):
    combined = pd.DataFrame({'actual': actual, 'predicted': predicted}).dropna()
    if combined.empty:
        return float('inf')
    return np.mean(np.abs(combined['actual'] - combined['predicted']))

def evaluate_models(df_price):
    if len(df_price) < EVAL_DAYS + 30:
        return None, None
        
    train_df = df_price.iloc[:-EVAL_DAYS].copy()
    test_df = df_price.iloc[-EVAL_DAYS:].copy()
    
    actual_prices = test_df['heating_oil_eur_per_100l']
    
    last_train_date = train_df.index[-1]
    last_test_date = test_df.index[-1]
    calendar_days_to_predict = (last_test_date - last_train_date).days
    
    uni_pred = predict_oil_price.predict_prophet_univariate(train_df, days_ahead=calendar_days_to_predict)
    uni_mae = calculate_mae(actual_prices, uni_pred['prophet_univariate'])
    
    multi_pred = predict_oil_price.predict_prophet_multivariate(train_df, days_ahead=calendar_days_to_predict)
    multi_mae = calculate_mae(actual_prices, multi_pred['prophet_multivariate'])
    
    lr_pred = predict_oil_price.predict_linear_regression(train_df, days_ahead=calendar_days_to_predict)
    lr_mae = calculate_mae(actual_prices, lr_pred['linear_regression'])
    
    models = {
        'Univariate Prophet': uni_mae,
        'Multivariate Prophet': multi_mae,
        'Linear Regression': lr_mae
    }
    
    champion_name = min(models, key=models.get)
    
    eval_data = {
        'test_df': test_df,
        'uni_pred': uni_pred,
        'multi_pred': multi_pred,
        'lr_pred': lr_pred,
        'maes': models
    }
    
    return champion_name, eval_data

def run_champion_model(df_price, champion_name, days_ahead):
    if champion_name == 'Univariate Prophet':
        return predict_oil_price.predict_prophet_univariate(df_price, days_ahead)
    elif champion_name == 'Multivariate Prophet':
        return predict_oil_price.predict_prophet_multivariate(df_price, days_ahead)
    elif champion_name == 'Linear Regression':
        return predict_oil_price.predict_linear_regression(df_price, days_ahead)
    return None

def generate_llm_notification(prompt_context):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return f"[LLM] GEMINI_API_KEY not found in .env. Fallback deterministic prompt:\n\n{prompt_context}"
        
    client = genai.Client(api_key=api_key)
    system_instruction = "You are a helpful smart home assistant managing a heating oil tank. Write a short, friendly, and actionable notification for the user based on the provided data. Keep it under 3 sentences."
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_context,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
            ),
        )
        return response.text
    except Exception as e:
        return f"Error calling Gemini API: {e}\nFallback Prompt:\n{prompt_context}"

def get_advisor_data():
    data = {}
    
    df_cons = predict_consumption.get_historical_data()
    if df_cons.empty or 'tank_level_liters' not in df_cons.columns:
        return {"error": "Failed to load consumption data or tank levels."}
        
    valid_tank_levels = df_cons['tank_level_liters'].dropna()
    if len(valid_tank_levels) == 0:
        return {"error": "No valid tank levels found."}
        
    current_tank_level = valid_tank_levels.iloc[-1]
    data['current_tank_level'] = current_tank_level
    
    if len(valid_tank_levels) < 30:
        recent_cons = df_cons['liters_consumed'].dropna().tail(30)
        hist_levels = []
        level = current_tank_level
        for consumed in reversed(recent_cons.values):
            hist_levels.append(level)
            level += consumed
        hist_levels.reverse()
        data['historical_tank_level'] = pd.Series(hist_levels, index=recent_cons.index)
    else:
        data['historical_tank_level'] = valid_tank_levels
    
    df_proj = predict_consumption.predict_future_consumption(df_cons, current_tank_level, days_ahead=FORECAST_DAYS)
    data['consumption_proj'] = df_proj
    
    critical_mask = df_proj['projected_tank_level'] <= MINIMUM_TANK_LITERS
    if critical_mask.any():
        critical_date = df_proj[critical_mask].index[0]
        data['critical_date'] = critical_date
        data['is_critical_reached'] = True
    else:
        critical_date = df_proj.index[-1]
        data['critical_date'] = critical_date
        data['is_critical_reached'] = False
        
    df_price = predict_oil_price.get_historical_data()
    
    global_price = df_price['heating_oil_eur_per_100l'].iloc[-1]
    offset = 0
    local_price = global_price
    if 'local_heating_oil_eur_per_100l' in df_price.columns:
        valid_local = df_price['local_heating_oil_eur_per_100l'].dropna()
        if not valid_local.empty:
            local_price = valid_local.iloc[-1]
            offset = local_price - global_price
            
    data['current_global_price'] = global_price
    data['current_local_price'] = local_price
    data['historical_price'] = df_price
    data['regional_offset'] = offset
    
    champion_name, eval_data = evaluate_models(df_price)
    data['champion_name'] = champion_name
    data['eval_data'] = eval_data
    
    champion_forecast = run_champion_model(df_price, champion_name, FORECAST_DAYS)
    data['champion_forecast'] = champion_forecast
    
    local_forecast = champion_forecast.copy()
    forecast_col = local_forecast.columns[0]
    local_forecast[forecast_col] = local_forecast[forecast_col] + offset
    data['local_champion_forecast'] = local_forecast
    
    if current_tank_level > LOOK_THRESHOLD_LITERS:
        prompt = f"The user's oil tank is currently at {current_tank_level:.0f} Liters, which is comfortably above their {LOOK_THRESHOLD_LITERS}L threshold. Tell them no action is needed right now."
        data['llm_notification'] = generate_llm_notification(prompt)
        data['status'] = 'OK - Level High'
        return data
    
    valid_window = local_forecast[local_forecast.index <= critical_date]
    
    if valid_window.empty:
         optimal_date = datetime.now()
         optimal_price = local_price
    else:
         optimal_date = valid_window[forecast_col].idxmin()
         optimal_price = valid_window.loc[optimal_date, forecast_col]
         
    days_to_wait = (optimal_date.date() - datetime.now().date()).days
    if days_to_wait < 0: days_to_wait = 0
    
    price_diff = local_price - optimal_price
    
    data['optimal_buy_date'] = optimal_date
    data['optimal_buy_price'] = optimal_price
    data['days_to_wait'] = days_to_wait
    data['expected_savings'] = price_diff
    
    prompt = (
        f"The user's oil tank is at {current_tank_level:.0f}L. "
        f"It will hit their minimum safety reserve of {MINIMUM_TANK_LITERS}L on {critical_date.strftime('%Y-%m-%d')}. "
        f"The {champion_name} AI model predicts that the best time to buy oil is in {days_to_wait} days on {optimal_date.strftime('%Y-%m-%d')}, "
        f"when the local price is expected to drop from {local_price:.2f} EUR/100L to {optimal_price:.2f} EUR/100L. "
        f"Advise them on what to do."
    )
    
    data['llm_notification'] = generate_llm_notification(prompt)
    data['status'] = 'ACTION NEEDED' if days_to_wait == 0 else 'WAIT'
    
    return data

def main():
    data = get_advisor_data()
    if 'error' in data:
        print(data['error'])
        return
        
    print("==============================================")
    print(" HEATING OIL TANK ADVISOR")
    print("==============================================\n")
    print(f"Current Tank Level: {data.get('current_tank_level', 0):.2f} Liters")
    
    if data.get('status') == 'OK - Level High':
        print(f"Tank level is above the {LOOK_THRESHOLD_LITERS}L threshold.")
    else:
        print(f"Optimal Buy Date: {data.get('optimal_buy_date').strftime('%Y-%m-%d')} ({data.get('days_to_wait')} days from now)")
        print(f"Predicted Price: {data.get('optimal_buy_price'):.2f} EUR/100L")
        print(f"Expected Savings: {data.get('expected_savings'):.2f} EUR/100L")
        
    print("\n================== LLM NOTIFICATION ==================")
    print(data.get('llm_notification', ''))
    print("======================================================")

if __name__ == "__main__":
    main()
