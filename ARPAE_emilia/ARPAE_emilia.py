import pandas as pd
import os
import json
from datetime import datetime

# 1. Setup Configuration
URL_REALTIME = "https://dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl"
OUTPUT_DIR = "ARPAE_emilia"
CSV_FILENAME = "ARPAE_latest.csv"

# Geographic bounding box (Adriatic Coast / Eastern plain)
LAT_MIN, LAT_MAX = 43.7, 45.1
LON_MIN, LON_MAX = 11.0, 13.0

# Mapping of BUFR codes to ARPAV-style Metadata
METADATA_MAP = {
    'b12101': ('TARIA2M', 'Temperatura aria a 2m', '°C'),
    'b10004': ('PRESS', 'Pressione atmosferica', 'hPa'),
    'b11002': ('VV', 'Velocità vento', 'm/s'),
    'b13011': ('PREC', 'Precipitazione', 'mm'),
    'b14102': ('RADSOL', 'Radiazione solare globale', 'W/m2')
}

def extract_meteo_vars(data_list):
    """ Extracts BUFR codes from ARPAE's nested structure. """
    extracted = {}
    if isinstance(data_list, list):
        for block in data_list:
            if isinstance(block, dict):
                target_dict = block.get('vars', block)
                for key, val in target_dict.items():
                    key_lower = str(key).lower()
                    if key_lower in METADATA_MAP:
                        if isinstance(val, dict) and 'v' in val:
                            extracted[key_lower] = val['v']
                        elif isinstance(val, list) and len(val) > 0:
                            extracted[key_lower] = val[0]
                        else:
                            extracted[key_lower] = val
    return extracted

def run_pipeline():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print("Step 1: Downloading real-time data from ARPAE...")
    try:
        df = pd.read_json(URL_REALTIME, lines=True)
    except Exception as e:
        print(f"Error downloading data: {e}")
        return

    # Step 2: Normalize coordinates
    df = df.dropna(subset=['lat', 'lon'])
    df['lat'] = df['lat'] / 100000.0
    df['lon'] = df['lon'] / 100000.0

    # Filter by Adriatic Coast bounding box
    df = df[(df['lat'] >= LAT_MIN) & (df['lat'] <= LAT_MAX) &
            (df['lon'] >= LON_MIN) & (df['lon'] <= LON_MAX)].copy()

    if df.empty:
        print("[!] No stations found in range.")
        return

    # --- FIX: Create a fallback unique ID if 'ident' is NaN ---
    # We combine Lat and Lon to identify the physical station location
    df['fallback_id'] = "STA_" + df['lat'].round(4).astype(str) + "_" + df['lon'].round(4).astype(str)
    
    if 'ident' in df.columns:
        df['final_id'] = df['ident'].fillna(df['fallback_id'])
    else:
        df['final_id'] = df['fallback_id']

    print("Step 3: Unpacking and melting data...")
    # Extract nested variables
    extracted_data = df['data'].apply(extract_meteo_vars).apply(pd.Series)
    df = pd.concat([df.drop(columns=['data']), extracted_data], axis=1)

    # Unit conversions
    if 'b12101' in df.columns:
        df['b12101'] = pd.to_numeric(df['b12101'], errors='coerce') - 273.15
    if 'b10004' in df.columns:
        df['b10004'] = pd.to_numeric(df['b10004'], errors='coerce') / 100.0

    found_bufr_codes = [c for c in METADATA_MAP.keys() if c in df.columns]

    # Transform to Long format
    long_df = df.melt(
        id_vars=['final_id', 'lat', 'lon', 'date'],
        value_vars=found_bufr_codes,
        var_name='bufr_code',
        value_name='value'
    ).dropna(subset=['value'])

    # Step 4: Latest value aggregation per Station/Sensor
    print("Step 4: Aggregating by sensor and selecting the most recent value...")
    long_df['date'] = pd.to_datetime(long_df['date'])
    long_df = long_df.sort_values(by='date')
    
    # Use 'final_id' to ensure we don't collapse different stations
    long_df = long_df.drop_duplicates(subset=['final_id', 'bufr_code'], keep='last')

    print("Step 5: Aligning columns with ARPAV structure...")
    long_df['sensor_code'] = long_df['bufr_code'].apply(lambda x: METADATA_MAP[x][0])
    long_df['quantity'] = long_df['bufr_code'].apply(lambda x: METADATA_MAP[x][1])
    long_df['unit'] = long_df['bufr_code'].apply(lambda x: METADATA_MAP[x][2])

    # Mapping IDs and Names
    long_df['station_id'] = long_df['final_id']
    long_df['codseqst'] = long_df['final_id']
    long_df['sensor_name'] = long_df['final_id'].apply(lambda x: f"ARPAE Station {x}")
    
    long_df['dt'] = long_df['date'].dt.strftime("%Y-%m-%dT%H:%M:%S")
    long_df['point'] = long_df.apply(lambda r: json.dumps({"type": "Point", "coordinates": [r['lon'], r['lat']]}), axis=1)
    long_df['quota'] = 0.0
    long_df['aggiornamento'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    long_df['gestore'] = 'ARPAE'
    long_df['provincia'] = 'Emilia-Romagna'

    # Final Column Selection
    final_columns = [
        'station_id', 'sensor_name', 'sensor_code', 'quantity', 'unit', 
        'dt', 'value', 'lat', 'lon', 'codseqst', 'point', 'quota', 
        'aggiornamento', 'gestore', 'provincia'
    ]
    
    output_df = long_df[final_columns]

    # 6. Save to CSV
    output_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    output_df.to_csv(output_path, index=False)
    
    print("-" * 40)
    print("SUCCESS!")
    print(f"File saved at: {output_path}")
    print(f"Total aggregated coastal observations: {len(output_df)}")
    print("-" * 40)
    print(output_df.head())

if __name__ == "__main__":
    run_pipeline()