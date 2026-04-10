import pandas as pd
import os
import json
import requests
from datetime import datetime

# 1. Configuration
OUTPUT_DIR = "ARPA_puglia"
CSV_FILENAME = "ARPA_puglia_coastal_latest.csv"

# High-density mapping of the Apulian Adriatic Coast (North to South)
PUGLIA_COAST_STATIONS = {
    "Chieuti_Marina": (41.92, 15.15),
    "Lesina_Marina": (41.90, 15.40),
    "Rodi_Garganico": (41.93, 15.88),
    "Peschici": (41.95, 16.01),
    "Vieste": (41.88, 16.17),
    "Mattinata": (41.71, 16.05),
    "Manfredonia": (41.63, 15.91),
    "Zapponeta": (41.45, 15.96),
    "Margherita_di_Savoia": (41.37, 16.15),
    "Barletta": (41.32, 16.28),
    "Trani": (41.27, 16.42),
    "Bisceglie": (41.24, 16.50),
    "Molfetta": (41.20, 16.59),
    "Giovinazzo": (41.18, 16.67),
    "Bari": (41.12, 16.87),
    "Mola_di_Bari": (41.06, 17.08),
    "Polignano_a_Mare": (40.99, 17.22),
    "Monopoli": (40.95, 17.30),
    "Torre_Canne": (40.84, 17.47),
    "Rosa_Marina": (40.78, 17.58),
    "Torre_Guaceto": (40.71, 17.66),
    "Brindisi": (40.63, 17.94),
    "Torre_San_Gennaro": (40.54, 18.06),
    "Casalabate": (40.51, 18.12),
    "San_Cataldo_Lecce": (40.38, 18.30),
    "Torre_dell_Orso": (40.27, 18.42),
    "Otranto": (40.14, 18.49),
    "Santa_Cesarea_Terme": (40.03, 18.46),
    "Castro": (40.00, 18.43),
    "Santa_Maria_di_Leuca": (39.80, 18.36)
}

# Standard sensor mapping for StormEngine compatibility
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
        print(f"  [!] Error fetching {lat}, {lon}: {e}")
        return None

def run_pipeline():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"Step 1: Fetching real-time data for {len(PUGLIA_COAST_STATIONS)} nodes in Puglia...")
    
    rows = []
    current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for name, coords in PUGLIA_COAST_STATIONS.items():
        lat, lon = coords
        print(f"  > Processing: {name}")
        data = fetch_open_meteo_data(lat, lon)
        
        if data:
            for api_key, (s_code, q_name, unit) in SENSORS_MAP.items():
                val = data.get(api_key)
                if val is not None:
                    # Convert wind from km/h to m/s
                    if s_code == 'VV':
                        val = round(val / 3.6, 2)
                    
                    rows.append({
                        'station_id': f"PUG_{name.upper()}",
                        'sensor_name': f"Puglia Virtual - {name.replace('_', ' ')}",
                        'sensor_code': s_code,
                        'quantity': q_name,
                        'unit': unit,
                        'dt': data['time'],
                        'value': val,
                        'lat': lat,
                        'lon': lon,
                        'codseqst': f"77{str(lat).replace('.','')[:4]}{str(lon).replace('.','')[:4]}",
                        'point': json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                        'quota': 10.0,
                        'aggiornamento': current_time,
                        'gestore': 'ARPA_PUGLIA_VIRTUAL',
                        'provincia': 'Puglia'
                    })

    if not rows:
        print("Error: No data retrieved.")
        return

    # 2. Save result
    output_df = pd.DataFrame(rows)
    output_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    output_df.to_csv(output_path, index=False)
    
    print("-" * 50)
    print(f"SUCCESS! Puglia Adriatic wall completed.")
    print(f"Total observations: {len(output_df)}")
    print(f"File saved: {output_path}")
    print("-" * 50)

if __name__ == "__main__":
    run_pipeline()