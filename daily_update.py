import os
import requests
import pandas as pd
import yfinance as yf
import xmltodict
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")
INFLUXDB_BUCKET_RAW = os.getenv("INFLUXDB_BUCKET_RAW")
LATITUDE = 48.8333
LONGITUDE = 11.2167

DRY_RUN = False

def calculate_liters(height_m: float) -> float:
    height_cm = height_m * 100
    liters = -0.004326 * height_cm**3 + 1.025 * height_cm**2 + 30.99 * height_cm - 34.9
    return max(0.0, liters) 

def fetch_weather_yesterday(target_date: str) -> dict:
    print(f"Fetching weather for {target_date}...")
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": target_date,
        "end_date": target_date,
        "daily": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"],
        "timezone": "Europe/Berlin"
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()['daily']
    
    return {
        "temp_max": data['temperature_2m_max'][0],
        "temp_min": data['temperature_2m_min'][0],
        "temp_mean": data['temperature_2m_mean'][0]
    }

def fetch_financials_yesterday(target_date: str) -> dict:
    print(f"Fetching financial data for {target_date}...")
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    end_date_yf = (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    start_date_yf = (target_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    
    data = yf.download(["BZ=F", "HO=F", "EUR=X", "^OVX"], start=start_date_yf, end=end_date_yf)
    closing_prices = pd.DataFrame({
        'Brent_Crude_USD': data['Close']['BZ=F'],
        'Heating_Oil_USD_per_Gallon': data['Close']['HO=F'],
        'EUR_Exchange_Rate': data['Close']['EUR=X'],
        'Oil_Volatility_OVX': data['Close']['^OVX']
    })
    closing_prices.ffill(inplace=True) 
    
    try:
        row = closing_prices.loc[:target_date].iloc[-1]
    except IndexError:
        print("Warning: Could not fetch financial data. Returning None.")
        return {"brent_crude_usd": None, "heating_oil_eur_per_100l": None, "oil_market_mood_ovx": None}

    brent_usd = float(row['Brent_Crude_USD'])
    heating_oil_usd = float(row['Heating_Oil_USD_per_Gallon'])
    eur_rate = float(row['EUR_Exchange_Rate'])
    ovx = float(row['Oil_Volatility_OVX'])
    
    heating_oil_eur = (heating_oil_usd / 3.78541) * eur_rate * 100
    
    return {
        "brent_crude_usd": brent_usd,
        "heating_oil_eur_per_100l": heating_oil_eur,
        "oil_market_mood_ovx": ovx
    }

def fetch_local_oil_price_heizoel24(zip_code="85111", liters="2000"):
    print(f"Fetching current local oil prices for {zip_code} from Heizoel24...")
    url = f"https://www.heizoel24.de/DailyPriceXml.ashx?zipCode={zip_code}&litre={liters}&unloadingpoints=1"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = xmltodict.parse(response.content)
        raw_price = data['result']['deliveries']['delivery']['price'][0]['#text']
        return float(raw_price.replace(',', '.'))
    except Exception as e:
        print(f"Error fetching Heizoel24 price: {e}")
        return None

def fetch_cheapest_dealer_heizoel24(zip_code="85111", liters="2000"):
    print(f"Fetching cheapest dealer for {zip_code} from Heizoel24...")
    url = "https://www.heizoel24.de/api/kalkulation/berechnen"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    payload = {
        "ZipCode": zip_code,
        "Amount": int(liters),
        "Stations": 1,
        "Product": {"Id": 1, "ClimateNeutral": False},
        "Parameters": [{"Id": 24}, {"Id": 6}, {"Id": 5}, {"Id": 11}, {"Id": 9}],
        "CountryId": 1,
        "Cn": False,
        "Ap": False,
        "ProductGroupId": 1
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        offers = response.json()['Items']
        cheapest = min(offers, key=lambda offer: offer['UnitPrice'])
        order_link = f"https://www.heizoel24.de/heizoel/angebotsliste?zipCode={zip_code}&amount={liters}&stations=1&product=1&options=24,6,5,11,9&cn=0&ap=0"
        return {"name": cheapest['Name'], "order_link": order_link}
    except Exception as e:
        print(f"Error fetching Heizoel24 dealer: {e}")
        return None

def fetch_local_oil_price_steil(zip_code="85111", liters="2000"):
    print(f"Fetching current local oil prices for {zip_code} from Steil Energie...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        import re
        import time

        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        driver.get("https://www.steil-energie.de/avia-heizoel/heizoel-bestellen")

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "cs_shop_zip_code"))
        )

        zip_input = driver.find_element(By.ID, "cs_shop_zip_code")
        zip_input.clear()
        zip_input.send_keys(zip_code)

        amount_input = driver.find_element(By.ID, "cs_shop_amount")
        amount_input.clear()
        amount_input.send_keys(liters)

        submit_btn = driver.find_element(By.XPATH, "//input[@name='submit1']")
        driver.execute_script("arguments[0].click();", submit_btn)

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Ihr Endpreis:')]|//*[contains(text(), 'AVIA Heizöl Standard')]"))
        )

        time.sleep(2)
        page_source = driver.page_source
        driver.quit()

        match = re.search(r'AVIA Heizöl Standard.*?Ihr Endpreis:\s*([\d\.]+,\d\d)', page_source, re.DOTALL | re.IGNORECASE)
        if match:
            price_str = match.group(1).replace('.', '').replace(',', '.')
            total_price = float(price_str)
            price_per_100l = (total_price / float(liters)) * 100
            return price_per_100l
        else:
            print("Could not find Steil price in response.")
            return None

    except Exception as e:
        print(f"Error fetching Steil price: {e}")
        return None

def get_tank_level_at_time(client, timestamp_iso: str) -> float:
    query_api = client.query_api()
    query = f'''
        from(bucket: "{INFLUXDB_BUCKET_RAW}")
          |> range(start: 0, stop: {timestamp_iso})
          |> filter(fn: (r) => r["_measurement"] == "m")
          |> filter(fn: (r) => r["entity_id"] == "oil_tank_sensor_liquid_depth")
          |> filter(fn: (r) => r["_field"] == "value")
          |> last()
    '''
    try:
        result = query_api.query(org=INFLUXDB_ORG, query=query)
        for table in result:
            for record in table.records:
                return float(record.get_value())
    except Exception as e:
        print(f"Error querying InfluxDB: {e}")
        
    fallback_query = f'''
        from(bucket: "{INFLUXDB_BUCKET_RAW}")
          |> range(start: {timestamp_iso})
          |> filter(fn: (r) => r["_measurement"] == "m")
          |> filter(fn: (r) => r["entity_id"] == "oil_tank_sensor_liquid_depth")
          |> filter(fn: (r) => r["_field"] == "value")
          |> first()
    '''
    try:
        result = query_api.query(org=INFLUXDB_ORG, query=fallback_query)
        for table in result:
            for record in table.records:
                return float(record.get_value())
    except Exception as e:
        print(f"Error querying InfluxDB (fallback): {e}")

    return None

def main():
    yesterday_dt = datetime.now() - timedelta(days=1)
    target_date = yesterday_dt.strftime("%Y-%m-%d")
    
    print(f"--- Running Daily CRON Job for {target_date} ---")
    
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    
    weather = fetch_weather_yesterday(target_date)
    finance = fetch_financials_yesterday(target_date)
    local_price = fetch_local_oil_price_heizoel24()
    local_dealer = fetch_cheapest_dealer_heizoel24()
    steil_price = fetch_local_oil_price_steil()
    
    start_of_yesterday = yesterday_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_yesterday = yesterday_dt.replace(hour=23, minute=59, second=59, microsecond=0)
    
    start_iso = start_of_yesterday.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = end_of_yesterday.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    start_height_m = get_tank_level_at_time(client, start_iso)
    end_height_m = get_tank_level_at_time(client, end_iso)
    
    if start_height_m is None or end_height_m is None:
        print(f"ERROR: Could not find raw tank data in InfluxDB bucket '{INFLUXDB_BUCKET_RAW}'. Cannot calculate consumption.")
        return
        
    start_liters = calculate_liters(start_height_m)
    end_liters = calculate_liters(end_height_m)
    
    liters_consumed = start_liters - end_liters
    
    print("\n--- Daily Summary ---")
    print(f"Date: {target_date}")
    print(f"Weather: {weather['temp_mean']}°C (Min: {weather['temp_min']}, Max: {weather['temp_max']})")
    print(f"Global Brent Crude: ${finance['brent_crude_usd']:.2f}")
    print(f"Global Heating Oil: {finance['heating_oil_eur_per_100l']:.2f} €/100L")
    if local_price:
        print(f"Local Heizoel24 Price: {local_price:.2f} €/100L")
    if local_dealer:
        print(f"Cheapest Heizoel24 Dealer: {local_dealer['name']}")
    if steil_price:
        print(f"Steil Energie Price: {steil_price:.2f} €/100L")
    print(f"Start Height: {start_height_m}m -> {start_liters:.1f} L")
    print(f"End Height: {end_height_m}m -> {end_liters:.1f} L")
    print(f"Consumed: {liters_consumed:.2f} Liters")
    print("---------------------\n")
    
    if DRY_RUN:
        print("DRY_RUN is True. Skipping InfluxDB write.")
        print("To fully automate this, set DRY_RUN=False and schedule it on Unraid.")
    else:
        print("Writing to InfluxDB...")
        write_api = client.write_api(write_options=SYNCHRONOUS)
        point = {
            "measurement": "daily_metrics",
            "tags": {"location": "Adelschlag"},
            "time": target_date + "T12:00:00Z",
            "fields": {
                "temp_max": float(weather['temp_max']) if weather['temp_max'] is not None else None,
                "temp_min": float(weather['temp_min']) if weather['temp_min'] is not None else None,
                "temp_mean": float(weather['temp_mean']) if weather['temp_mean'] is not None else None,
                "brent_crude_usd": float(finance['brent_crude_usd']) if finance['brent_crude_usd'] is not None else None,
                "heating_oil_eur_per_100l": float(finance['heating_oil_eur_per_100l']) if finance['heating_oil_eur_per_100l'] is not None else None,
                "oil_market_mood_ovx": float(finance['oil_market_mood_ovx']) if finance['oil_market_mood_ovx'] is not None else None,
                "local_heating_oil_eur_per_100l": float(local_price) if local_price is not None else None,
                "local_heating_oil_dealer": local_dealer['name'] if local_dealer is not None else None,
                "local_heating_oil_order_link": local_dealer['order_link'] if local_dealer is not None else None,
                "steil_heating_oil_eur_per_100l": float(steil_price) if steil_price is not None else None,
                "liters_consumed": float(liters_consumed),
                "tank_level_liters": float(end_liters),
                "tank_level_height_m": float(end_height_m)
            }
        }
        point["fields"] = {k: v for k, v in point["fields"].items() if v is not None}
        
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
        print("Done!")

if __name__ == "__main__":
    main()
