import pandas as pd
import os
import json
import requests
from datetime import datetime

# 1. Configurazione
OUTPUT_DIR = "ARPAM_marche"
CSV_FILENAME = "ARPAM_coastal_latest.csv"

# Definiamo le stazioni costiere "chiave" delle Marche (Lat, Lon)
MARCHE_COAST_STATIONS = {
    "Pesaro": (43.91, 12.91),
    "Fano": (43.84, 13.01),
    "Senigallia": (43.71, 13.21),
    "Ancona": (43.61, 13.51),
    "Civitanova Marche": (43.30, 13.72),
    "San Benedetto del Tronto": (42.95, 13.88)
}

# Mapping delle variabili verso lo standard ARPAV
SENSORS_MAP = {
    'temperature_2m': ('TARIA2M', 'Temperatura aria a 2m', '°C'),
    'surface_pressure': ('PRESS', 'Pressione atmosferica', 'hPa'),
    'wind_speed_10m': ('VV', 'Velocità vento', 'm/s'),
    'rain': ('PREC', 'Precipitazione', 'mm')
}

def fetch_open_meteo_data(name, lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,surface_pressure,wind_speed_10m,rain&timezone=Europe%2FRome"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()['current']
        return data
    except:
        return None

def run_pipeline():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print("Step 1: Fetching real-time data for Marche Coastal Nodes via Open-Meteo...")
    
    rows = []
    current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for name, coords in MARCHE_COAST_STATIONS.items():
        lat, lon = coords
        print(f"  > Retrieving data for {name}...")
        data = fetch_open_meteo_data(name, lat, lon)
        
        if data:
            for api_key, (s_code, q_name, unit) in SENSORS_MAP.items():
                val = data.get(api_key)
                if val is not None:
                    # Trasformiamo il vento da km/h (default Open-Meteo) a m/s
                    if s_code == 'VV':
                        val = round(val / 3.6, 2)
                    
                    rows.append({
                        'station_id': f"MAR_{name.replace(' ', '_')}",
                        'sensor_name': f"Marche Virtual - {name}",
                        'sensor_code': s_code,
                        'quantity': q_name,
                        'unit': unit,
                        'dt': data['time'],
                        'value': val,
                        'lat': lat,
                        'lon': lon,
                        'codseqst': f"99{lat}{lon}".replace('.', ''),
                        'point': json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                        'quota': 5.0,
                        'aggiornamento': current_time,
                        'gestore': 'ARPAM_VIRTUAL',
                        'provincia': 'Marche'
                    })

    if not rows:
        print("Error: No data retrieved.")
        return

    # 2. Creazione DataFrame e salvataggio
    output_df = pd.DataFrame(rows)
    output_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    output_df.to_csv(output_path, index=False)
    
    print("-" * 40)
    print(f"SUCCESS! Marche virtual coastal dataset created.")
    print(f"Total observations: {len(output_df)}")
    print(f"Saved at: {output_path}")
    print("-" * 40)

if __name__ == "__main__":
    run_pipeline()