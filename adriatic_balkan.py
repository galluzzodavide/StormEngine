import pandas as pd
import os
import json
import requests
import numpy as np
from datetime import datetime
import time

# ══════════════════════════════════════════════════════════════
# ~210 Virtual Stations: Adriatic Sea + Balkan Coast
# Using Open-Meteo forecast API (NWP-interpolated values)
# ══════════════════════════════════════════════════════════════

OUTPUT_DIR = "Adriatic_Balkan_virtual"
CSV_FILENAME = "adriatic_balkan_virtual_latest.csv"

SENSORS_MAP = {
    'temperature_2m': ('TARIA2M', 'Temperatura aria a 2m', '°C'),
    'surface_pressure': ('PRESS', 'Pressione atmosferica', 'hPa'),
    'wind_speed_10m': ('VV', 'Velocità vento', 'm/s'),
    'rain': ('PREC', 'Precipitazione', 'mm')
}


def generate_adriatic_balkan_stations(seed=42):
    np.random.seed(seed)
    stations = {}

    # ══════════════════════════════════════════════════════════
    # Zone 1: Adriatic Sea — wide spread across the basin
    # NO points touching Italian coast (covered by real ARPA stations)
    # ══════════════════════════════════════════════════════════

    adriatic_sea_points = {
        # ── Northern Adriatic (Gulf of Venice / Trieste) ──
        "ADR_N01": (45.50, 13.20), "ADR_N02": (45.40, 13.50),
        "ADR_N03": (45.30, 13.00), "ADR_N04": (45.20, 13.30),
        "ADR_N05": (45.10, 13.60), "ADR_N06": (45.00, 13.10),
        "ADR_N07": (44.90, 13.40), "ADR_N08": (44.80, 13.70),
        "ADR_N09": (44.70, 13.20), "ADR_N10": (44.60, 13.50),
        "ADR_N11": (45.35, 13.70), "ADR_N12": (45.15, 13.45),
        "ADR_N13": (44.95, 13.15), "ADR_N14": (44.75, 13.55),
        "ADR_N15": (44.85, 13.85),

        # ── Central-North Adriatic (wide part) ──
        "ADR_CN01": (44.50, 13.80), "ADR_CN02": (44.40, 14.10),
        "ADR_CN03": (44.30, 13.60), "ADR_CN04": (44.20, 14.00),
        "ADR_CN05": (44.10, 14.30), "ADR_CN06": (44.00, 13.80),
        "ADR_CN07": (43.90, 14.20), "ADR_CN08": (43.80, 14.50),
        "ADR_CN09": (44.50, 14.30), "ADR_CN10": (44.30, 14.50),
        "ADR_CN11": (44.10, 13.90), "ADR_CN12": (43.90, 14.60),
        "ADR_CN13": (44.20, 14.70), "ADR_CN14": (44.40, 14.80),
        "ADR_CN15": (44.00, 14.10),

        # ── Central Adriatic (mid basin) ──
        "ADR_CM01": (43.70, 14.30), "ADR_CM02": (43.60, 14.70),
        "ADR_CM03": (43.50, 14.40), "ADR_CM04": (43.40, 14.80),
        "ADR_CM05": (43.30, 15.10), "ADR_CM06": (43.20, 14.60),
        "ADR_CM07": (43.10, 15.00), "ADR_CM08": (43.00, 14.70),
        "ADR_CM09": (42.90, 15.20), "ADR_CM10": (42.80, 14.90),
        "ADR_CM11": (43.60, 15.10), "ADR_CM12": (43.40, 15.40),
        "ADR_CM13": (43.20, 15.50), "ADR_CM14": (43.00, 15.60),
        "ADR_CM15": (42.80, 15.40),

        # ── Central-South Adriatic ──
        "ADR_CS01": (42.70, 15.60), "ADR_CS02": (42.60, 15.90),
        "ADR_CS03": (42.50, 15.50), "ADR_CS04": (42.40, 16.00),
        "ADR_CS05": (42.30, 15.70), "ADR_CS06": (42.20, 16.20),
        "ADR_CS07": (42.10, 15.90), "ADR_CS08": (42.00, 16.40),
        "ADR_CS09": (41.90, 16.10), "ADR_CS10": (41.80, 16.50),
        "ADR_CS11": (42.60, 16.30), "ADR_CS12": (42.40, 16.50),
        "ADR_CS13": (42.20, 16.70), "ADR_CS14": (42.00, 16.80),
        "ADR_CS15": (41.80, 16.20),

        # ── Southern Adriatic (deep basin) ──
        "ADR_SD01": (41.70, 16.80), "ADR_SD02": (41.60, 17.10),
        "ADR_SD03": (41.50, 16.70), "ADR_SD04": (41.40, 17.20),
        "ADR_SD05": (41.30, 16.90), "ADR_SD06": (41.20, 17.40),
        "ADR_SD07": (41.10, 17.10), "ADR_SD08": (41.00, 17.50),
        "ADR_SD09": (40.90, 17.20), "ADR_SD10": (40.80, 17.60),
        "ADR_SD11": (41.60, 17.50), "ADR_SD12": (41.40, 17.60),
        "ADR_SD13": (41.20, 17.70), "ADR_SD14": (41.00, 17.80),
        "ADR_SD15": (40.80, 17.40),

        # ── Strait of Otranto ──
        "ADR_OT01": (40.60, 17.80), "ADR_OT02": (40.50, 18.10),
        "ADR_OT03": (40.40, 17.90), "ADR_OT04": (40.30, 18.30),
        "ADR_OT05": (40.20, 18.00), "ADR_OT06": (40.10, 18.40),
        "ADR_OT07": (40.00, 18.20), "ADR_OT08": (39.90, 18.50),
        "ADR_OT09": (39.80, 18.30), "ADR_OT10": (39.70, 18.60),
        "ADR_OT11": (40.50, 18.50), "ADR_OT12": (40.30, 18.70),
        "ADR_OT13": (40.10, 18.80), "ADR_OT14": (39.90, 18.90),
        "ADR_OT15": (39.70, 19.00),

        # ── Longitudinal transects (cross-Adriatic) ──
        "ADR_T01": (44.50, 14.60), "ADR_T02": (44.00, 14.80),
        "ADR_T03": (43.50, 15.30), "ADR_T04": (43.00, 15.80),
        "ADR_T05": (42.50, 16.30), "ADR_T06": (42.00, 16.60),
        "ADR_T07": (41.50, 17.00), "ADR_T08": (41.00, 17.60),
        "ADR_T09": (40.50, 18.30), "ADR_T10": (40.00, 18.70),

        # ── Extra spread points (fill gaps) ──
        "ADR_X01": (45.45, 13.35), "ADR_X02": (44.65, 13.95),
        "ADR_X03": (44.15, 14.45), "ADR_X04": (43.65, 14.95),
        "ADR_X05": (43.15, 15.35), "ADR_X06": (42.65, 15.75),
        "ADR_X07": (42.15, 16.15), "ADR_X08": (41.65, 16.55),
        "ADR_X09": (41.15, 17.25), "ADR_X10": (40.65, 17.95),
        "ADR_X11": (40.15, 18.55), "ADR_X12": (39.85, 18.75),
        "ADR_X13": (44.85, 14.15), "ADR_X14": (43.85, 14.75),
        "ADR_X15": (42.85, 15.65),
    }
    stations.update(adriatic_sea_points)

    # ══════════════════════════════════════════════════════════
    # Zone 2: Balkan / East Adriatic Coast
    # ══════════════════════════════════════════════════════════

    balkan_coast_points = {
        # Slovenia coast
        "BAL_SLO01": (45.54, 13.72), "BAL_SLO02": (45.50, 13.60),
        # Croatian coast (North to South)
        "BAL_CRO01": (45.33, 14.44), "BAL_CRO02": (45.20, 14.50),
        "BAL_CRO03": (44.87, 14.85), "BAL_CRO04": (44.75, 14.70),
        "BAL_CRO05": (44.50, 14.90), "BAL_CRO06": (44.30, 15.10),
        "BAL_CRO07": (44.12, 15.23), "BAL_CRO08": (43.95, 15.40),
        "BAL_CRO09": (43.80, 15.60), "BAL_CRO10": (43.51, 16.44),
        "BAL_CRO11": (43.30, 16.70), "BAL_CRO12": (43.15, 16.85),
        "BAL_CRO13": (43.07, 17.01), "BAL_CRO14": (42.95, 17.15),
        "BAL_CRO15": (42.75, 17.40), "BAL_CRO16": (42.65, 17.95),
        "BAL_CRO17": (42.65, 18.09), "BAL_CRO18": (42.45, 18.50),
        # Croatian islands
        "BAL_ISL01": (44.95, 14.40), "BAL_ISL02": (44.55, 14.60),
        "BAL_ISL03": (43.85, 15.25), "BAL_ISL04": (43.40, 16.20),
        "BAL_ISL05": (43.00, 16.50), "BAL_ISL06": (42.75, 16.90),
        # Montenegro coast
        "BAL_MNE01": (42.29, 18.84), "BAL_MNE02": (42.10, 19.08),
        "BAL_MNE03": (42.00, 19.00), "BAL_MNE04": (41.85, 19.30),
        # Albanian coast
        "BAL_ALB01": (41.70, 19.45), "BAL_ALB02": (41.33, 19.82),
        "BAL_ALB03": (41.00, 19.80), "BAL_ALB04": (40.85, 19.65),
        "BAL_ALB05": (40.65, 19.50), "BAL_ALB06": (40.45, 19.48),
        "BAL_ALB07": (40.30, 19.45), "BAL_ALB08": (40.10, 19.80),
        "BAL_ALB09": (39.90, 20.00), "BAL_ALB10": (39.85, 19.85),
        # Greek NW coast
        "BAL_GRE01": (39.62, 19.92), "BAL_GRE02": (39.50, 19.80),
        "BAL_GRE03": (39.40, 20.00),
    }
    stations.update(balkan_coast_points)

    # ══════════════════════════════════════════════════════════
    # Zone 3: Ionian / South of Otranto
    # ══════════════════════════════════════════════════════════

    ionian_points = {
        "ION_01": (39.60, 19.00), "ION_02": (39.50, 19.30),
        "ION_03": (39.70, 19.40), "ION_04": (39.40, 19.50),
        "ION_05": (39.80, 19.60), "ION_06": (39.60, 19.70),
        "ION_07": (39.50, 18.80), "ION_08": (39.40, 19.10),
    }
    stations.update(ionian_points)

    print(f'Generated {len(stations)} virtual stations:')
    print(f'  Adriatic Sea (open water): {len(adriatic_sea_points)}')
    print(f'  Balkan Coast:              {len(balkan_coast_points)}')
    print(f'  Ionian/South Otranto:      {len(ionian_points)}')
    print(f'  TOTAL:                     {len(stations)}')

    return stations


def fetch_open_meteo_data(lat, lon):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,surface_pressure,wind_speed_10m,rain"
        f"&timezone=Europe%2FRome"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()['current']
    except Exception as e:
        print(f"  [!] Error fetching ({lat}, {lon}): {e}")
        return None


def determine_region(name):
    if name.startswith("ADR_"):
        return "Adriatic_Sea"
    elif name.startswith("ION_"):
        return "Ionian_Sea"
    elif "SLO" in name:
        return "Slovenia"
    elif "CRO" in name or "ISL" in name:
        return "Croatia"
    elif "MNE" in name:
        return "Montenegro"
    elif "ALB" in name:
        return "Albania"
    elif "GRE" in name:
        return "Greece"
    return "Unknown"


def run_pipeline():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stations = generate_adriatic_balkan_stations()

    print(f"\nFetching Open-Meteo data for {len(stations)} points...")
    rows = []
    current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for idx, (name, (lat, lon)) in enumerate(stations.items()):
        if idx % 30 == 0:
            print(f"  Progress: {idx}/{len(stations)}")

        data = fetch_open_meteo_data(lat, lon)

        if data:
            region = determine_region(name)
            for api_key, (s_code, q_name, unit) in SENSORS_MAP.items():
                val = data.get(api_key)
                if val is not None:
                    if s_code == 'VV':
                        val = round(val / 3.6, 2)

                    rows.append({
                        'station_id': f"VIRT_{name}",
                        'sensor_name': f"Virtual - {name.replace('_', ' ')}",
                        'sensor_code': s_code,
                        'quantity': q_name,
                        'unit': unit,
                        'dt': data['time'],
                        'value': val,
                        'lat': lat,
                        'lon': lon,
                        'codseqst': f"99{str(lat).replace('.','')[:4]}{str(lon).replace('.','')[:4]}",
                        'point': json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                        'quota': 10.0,
                        'aggiornamento': current_time,
                        'gestore': f'VIRTUAL_{region.upper()}',
                        'provincia': region
                    })

        if idx % 50 == 49:
            time.sleep(1)

    if not rows:
        print("Error: No data retrieved.")
        return

    output_df = pd.DataFrame(rows)
    output_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    output_df.to_csv(output_path, index=False)

    n_stations = output_df['station_id'].nunique()
    print("-" * 60)
    print(f"SUCCESS! Adriatic + Balkan virtual network complete.")
    print(f"  Unique stations:     {n_stations}")
    print(f"  Total observations:  {len(output_df)}")
    print(f"  File saved:          {output_path}")
    print("-" * 60)

    summary = output_df.drop_duplicates('station_id').groupby('provincia').size()
    print("\nStations per region:")
    print(summary.to_string())


if __name__ == "__main__":
    run_pipeline()