"""
Download HadISD station data for the Adriatic region.
Extracts: sea-level pressure, wind speed/direction (→ u10, v10), temperature.
Output: CSV matching ARPA station format.
Period: 2024 (full year)

HadISD v3.4.1.2024f
Data source: https://www.metoffice.gov.uk/hadobs/hadisd/
Correct URL format: hadisd.3.4.1.2024f_19310101-20250101_{station_code}.nc.gz
"""

import os
import json
import gzip
import requests
import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

OUTPUT_DIR = "HadISD_Adriatic"
CSV_FILENAME = "hadisd_adriatic_2024.csv"

# Adriatic bounding box (same as encoder)
LAT_MIN, LAT_MAX = 39.0, 46.5
LON_MIN, LON_MAX = 12.0, 20.0

# Time range
TIME_START = "2024-11-01"
TIME_END   = "2025-02-01"

# HadISD version
HADISD_VERSION = "v341_2024f"
HADISD_BASE_URL = f"https://hadleyserver.metoffice.gov.uk/hadobs/hadisd/{HADISD_VERSION}/data"
STATION_LIST_URL = f"https://hadleyserver.metoffice.gov.uk/hadobs/hadisd/{HADISD_VERSION}/files/hadisd_station_info_{HADISD_VERSION}.txt"

# Sensor mapping for CSV output (matching ARPA format)
SENSORS_MAP = {
    'msl':  ('PRESS', 'Pressione atmosferica', 'hPa'),
    'u10':  ('U10', 'Componente zonale vento 10m', 'm/s'),
    'v10':  ('V10', 'Componente meridionale vento 10m', 'm/s'),
    't2m':  ('TARIA2M', 'Temperatura aria a 2m', '°C'),
}


# ══════════════════════════════════════════════════════════════
# Step 1: Download and parse station list
# ══════════════════════════════════════════════════════════════

def download_station_list():
    """Download HadISD station list and filter by Adriatic bounding box."""
    print("Downloading HadISD station list...")

    urls_to_try = [
        STATION_LIST_URL,
        f"https://hadleyserver.metoffice.gov.uk/hadobs/hadisd/{HADISD_VERSION}/files/station_list_{HADISD_VERSION}.txt",
        f"https://www.metoffice.gov.uk/hadobs/hadisd/{HADISD_VERSION}/files/hadisd_station_info_{HADISD_VERSION}.txt",
        f"https://www.metoffice.gov.uk/hadobs/hadisd/{HADISD_VERSION}/files/station_list_{HADISD_VERSION}.txt",
    ]

    lines = None
    for url in urls_to_try:
        try:
            print(f"  Trying: {url}")
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            lines = r.text.strip().split('\n')
            print(f"  OK — {len(lines)} lines")
            break
        except Exception as e:
            print(f"  Failed: {e}")
            continue

    if lines is None:
        local_file = "hadisd_station_list.txt"
        if os.path.exists(local_file):
            print(f"Found local file: {local_file}")
            with open(local_file) as f:
                lines = f.read().strip().split('\n')
        else:
            print("Could not download station list. Exiting.")
            return None

    stations = []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            code = parts[0]
            lat = float(parts[-3])
            lon = float(parts[-2])
            elev = float(parts[-1])
            name = ' '.join(parts[1:-3])

            if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
                stations.append({
                    'code': code,
                    'name': name.strip(),
                    'lat': lat,
                    'lon': lon,
                    'elevation': elev
                })
        except (ValueError, IndexError):
            continue

    print(f"\nFound {len(stations)} stations in Adriatic bounding box")
    for s in stations:
        print(f"  {s['code']}  {s['name'][:30]:30s}  ({s['lat']:.2f}, {s['lon']:.2f})  elev={s['elevation']:.0f}m")

    return stations


# ══════════════════════════════════════════════════════════════
# Step 2: Download individual station .nc.gz files
# ══════════════════════════════════════════════════════════════

def download_station_data(station_code):
    """Download a single HadISD station .nc.gz file and decompress."""
    nc_path = os.path.join(OUTPUT_DIR, "nc_files", f"{station_code}.nc")
    gz_path = nc_path + ".gz"
    os.makedirs(os.path.dirname(nc_path), exist_ok=True)

    # Skip if already downloaded and decompressed
    if os.path.exists(nc_path):
        return nc_path

    print(f"    Downloading {station_code}...")

    # Correct URL: hadisd.3.4.1.2024f_19310101-20250101_{code}.nc.gz
    filename = f"hadisd.3.4.1.2024f_19310101-20250101_{station_code}.nc.gz"
    url = f"{HADISD_BASE_URL}/{filename}"

    try:
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()

        # Save compressed .gz file
        with open(gz_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        # Decompress .gz → .nc
        with gzip.open(gz_path, 'rb') as f_in:
            with open(nc_path, 'wb') as f_out:
                f_out.write(f_in.read())

        # Remove .gz after decompression
        os.remove(gz_path)

        size_mb = os.path.getsize(nc_path) / 1e6
        print(f"    OK ({size_mb:.1f} MB)")
        return nc_path

    except Exception as e:
        print(f"    FAILED: {e}")
        # Clean up partial downloads
        if os.path.exists(gz_path):
            os.remove(gz_path)
        return None


# ══════════════════════════════════════════════════════════════
# Step 3: Process NetCDF → CSV rows
# ══════════════════════════════════════════════════════════════

def process_station_nc(nc_path, station_info):
    """Read a HadISD NetCDF file and extract msl, u10, v10, t2m."""
    try:
        ds = xr.open_dataset(nc_path)
    except Exception as e:
        print(f"    Error opening {nc_path}: {e}")
        return []

    # Print available variables for debugging
    print(f"    Variables in NC: {list(ds.data_vars)[:10]}")

    # Get time coordinate
    time_var = None
    for tv in ['time', 'ob_time', 'times']:
        if tv in ds.coords or tv in ds:
            time_var = tv
            break

    if time_var is None:
        print(f"    No time coordinate found. Coords: {list(ds.coords)}")
        ds.close()
        return []

    times = pd.DatetimeIndex(ds[time_var].values)

    # Filter to target period
    t_start = pd.Timestamp(TIME_START)
    t_end = pd.Timestamp(TIME_END)
    mask = (times >= t_start) & (times <= t_end)

    if mask.sum() == 0:
        print(f"    No data in target period ({TIME_START} → {TIME_END})")
        ds.close()
        return []

    print(f"    {mask.sum()} observations in target period")

    code = station_info['code']
    lat = station_info['lat']
    lon = station_info['lon']
    name = station_info['name']

    # HadISD variable names (try multiple naming conventions)
    var_map = {
        'temperatures': ('t2m', 1.0),
        'temperature': ('t2m', 1.0),
        'temp': ('t2m', 1.0),
        'slp': ('msl', 1.0),
        'sea_level_pressure': ('msl', 1.0),
        'sealevelpress': ('msl', 1.0),
        'stnlp': ('msl', 1.0),
        'windspeeds': ('ws', 1.0),
        'wind_speed': ('ws', 1.0),
        'wspd': ('ws', 1.0),
        'winddirs': ('wd', 1.0),
        'wind_direction': ('wd', 1.0),
        'wdir': ('wd', 1.0),
    }

    extracted = {}
    for nc_var, (our_var, scale) in var_map.items():
        if nc_var in ds:
            data = ds[nc_var].values
            if data.ndim > 1:
                data = data[:, 0] if data.shape[1] > 0 else data.flatten()
            data = data[mask].astype(float)
            data[data < -1e10] = np.nan
            data[data > 1e10] = np.nan
            data = data * scale
            extracted[our_var] = data

    times_filtered = times[mask]

    # Convert wind speed + direction → u10, v10
    if 'ws' in extracted and 'wd' in extracted:
        ws = extracted['ws']
        wd = extracted['wd']
        extracted['u10'] = -ws * np.sin(np.radians(wd))
        extracted['v10'] = -ws * np.cos(np.radians(wd))

    # Build rows in ARPA CSV format
    rows = []
    for var_key in ['msl', 'u10', 'v10', 't2m']:
        if var_key not in extracted:
            continue
        s_code, q_name, unit = SENSORS_MAP[var_key]
        values = extracted[var_key]

        for t, val in zip(times_filtered, values):
            if np.isnan(val):
                continue
            rows.append({
                'station_id': f"HADISD_{code}",
                'sensor_name': f"HadISD - {name}",
                'sensor_code': s_code,
                'quantity': q_name,
                'unit': unit,
                'dt': t.strftime('%Y-%m-%dT%H:%M:%S'),
                'value': round(float(val), 4),
                'lat': lat,
                'lon': lon,
                'codseqst': code,
                'point': json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                'quota': station_info['elevation'],
                'aggiornamento': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'gestore': 'HADISD',
                'provincia': determine_country(lat, lon)
            })

    ds.close()
    return rows


def determine_country(lat, lon):
    """Simple country classification based on coordinates."""
    if lon < 14.0:
        return "Italy"
    elif lon < 15.5 and lat > 44.0:
        return "Slovenia_Croatia"
    elif lon < 17.5 and lat > 42.5:
        return "Croatia"
    elif lon < 19.0 and lat > 42.0:
        return "Montenegro"
    elif lon < 20.0 and lat > 40.5:
        return "Albania"
    elif lat < 40.5:
        return "Greece"
    return "Balkans"


# ══════════════════════════════════════════════════════════════
# Step 4: Main pipeline
# ══════════════════════════════════════════════════════════════

def run_pipeline():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Get station list
    stations = download_station_list()
    if stations is None or len(stations) == 0:
        print("No stations found. Exiting.")
        return

    pd.DataFrame(stations).to_csv(
        os.path.join(OUTPUT_DIR, "adriatic_stations.csv"), index=False
    )

    # 2. Download and process each station
    print(f"\nProcessing {len(stations)} stations...")
    all_rows = []
    success_count = 0
    fail_count = 0

    for idx, station in enumerate(stations):
        print(f"\n[{idx+1}/{len(stations)}] {station['code']} — {station['name']}")

        nc_path = download_station_data(station['code'])
        if nc_path is None:
            fail_count += 1
            continue

        rows = process_station_nc(nc_path, station)
        all_rows.extend(rows)
        if rows:
            success_count += 1
        print(f"    Extracted {len(rows)} observations")

    print(f"\n\nDownload summary: {success_count} OK, {fail_count} failed out of {len(stations)}")

    if not all_rows:
        print("\nNo data extracted. Check network connection and URLs.")
        return

    # 3. Save CSV
    output_df = pd.DataFrame(all_rows)
    output_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    output_df.to_csv(output_path, index=False)

    n_stations = output_df['station_id'].nunique()
    print("\n" + "=" * 60)
    print(f"SUCCESS! HadISD Adriatic data extracted.")
    print(f"  Period:              {TIME_START} → {TIME_END}")
    print(f"  Unique stations:     {n_stations}")
    print(f"  Total observations:  {len(output_df)}")
    print(f"  File saved:          {output_path}")
    print("=" * 60)

    print("\nStations by country:")
    summary = output_df.drop_duplicates('station_id').groupby('provincia').size()
    print(summary.to_string())

    print("\nObservations by variable:")
    var_summary = output_df.groupby('sensor_code').size()
    print(var_summary.to_string())

    print("\nTime range per station:")
    for sid in sorted(output_df['station_id'].unique()):
        st = output_df[output_df['station_id'] == sid]
        t_min = st['dt'].min()
        t_max = st['dt'].max()
        n_obs = len(st)
        print(f"  {sid}: {t_min[:10]} → {t_max[:10]}  ({n_obs} obs)")


if __name__ == "__main__":
    run_pipeline()