import pandas as pd
import os
import json
import requests
from datetime import datetime

# 1. Configuration
OUTPUT_DIR = "ARTA_abruzzo"
CSV_FILENAME = "ARTA_coastal_latest.csv"

# Comprehensive list of Abruzzo Coastal Nodes (from North to South)
ABRUZZO_COAST_STATIONS = {
    "Martinsicuro": (42.88, 13.91),
    "Alba Adriatica": (42.83, 13.92),
    "Tortoreto": (42.80, 13.94),
    "Giulianova": (42.75, 13.97),
    "Roseto degli Abruzzi": (42.67, 14.01),
    "Pineto": (42.61, 14.06),
    "Silvi Marina": (42.55, 14.11),
    "Montesilvano": (42.51, 14.15),
    "Pescara": (42.46, 14.21),
    "Francavilla al Mare": (42.42, 14.28),
    "Ortona": (42.35, 14.40),
    "San Vito Chietino": (42.30, 14.44),
    "Fossacesia": (42.24, 14.48),
    "Casalbordino": (42.19, 14.58),
    "Vasto": (42.11, 14.71),
    "San Salvo": (42.04, 14.73)
}

# Mapping variables to your standard ARPAV/ARPAE structure
SENSORS_MAP = {
    'temperature_2m': ('TARIA2M', 'Temperatura aria a 2m', '°C'),
    'surface_pressure': ('PRESS', 'Pressione atmosferica', 'hPa'),
    'wind_speed_10m': ('VV', 'Velocità vento', 'm/s'),
    'rain': ('PREC', 'Precipitazione', 'mm')
}

def fetch_open_meteo_data(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,surface_pressure,wind_speed_10m,rain&timezone=Europe%2FRome"
    try:
        r = requests.get(url, timeout=10)
        return r.json()['current']
    except Exception as e:
        print(f"Error fetching {lat}, {lon}: {e}")
        return None

def run_pipeline():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"Step 1: Fetching real-time data for {len(ABRUZZO_COAST_STATIONS)} Abruzzo Coastal Nodes...")
    
    rows = []
    current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for name, coords in ABRUZZO_COAST_STATIONS.items():
        lat, lon = coords
        print(f"  > Processing: {name} ({lat}, {lon})")
        data = fetch_open_meteo_data(lat, lon)
        
        if data:
            for api_key, (s_code, q_name, unit) in SENSORS_MAP.items():
                val = data.get(api_key)
                if val is not None:
                    # Conversion Wind km/h -> m/s
                    if s_code == 'VV':
                        val = round(val / 3.6, 2)
                    
                    rows.append({
                        'station_id': f"ABR_{name.upper().replace(' ', '_')}",
                        'sensor_name': f"Abruzzo Virtual - {name}",
                        'sensor_code': s_code,
                        'quantity': q_name,
                        'unit': unit,
                        'dt': data['time'],
                        'value': val,
                        'lat': lat,
                        'lon': lon,
                        'codseqst': f"88{str(lat).replace('.','')[:4]}{str(lon).replace('.','')[:4]}",
                        'point': json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                        'quota': 5.0,
                        'aggiornamento': current_time,
                        'gestore': 'ARTA_VIRTUAL',
                        'provincia': 'Abruzzo'
                    })

    if not rows:
        print("CRITICAL: No data points were retrieved.")
        return

    # 2. DataFrame creation and save
    output_df = pd.DataFrame(rows)
    output_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    output_df.to_csv(output_path, index=False)
    
    print("-" * 50)
    print(f"SUCCESS! Abruzzo high-density coastal dataset created.")
    print(f"Total sensor observations: {len(output_df)}")
    print(f"File location: {output_path}")
    print("-" * 50)

if __name__ == "__main__":
    run_pipeline()