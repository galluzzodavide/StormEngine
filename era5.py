import os
import glob
import numpy as np
import pandas as pd
import xarray as xr
import cdsapi
import zipfile

# ==========================================
# 1. CONFIGURAZIONE CREDENZIALI COPERNICUS
# ==========================================
CDS_URL = "https://cds.climate.copernicus.eu/api"
CDS_KEY = "6e902f49-5d17-4d5e-95d1-8beb80d113ae"

client = cdsapi.Client(url=CDS_URL, key=CDS_KEY)

# ==========================================
# 2. DEFINIZIONE RICHIESTA E DOWNLOAD
# ==========================================
# ERA5-Land: risoluzione nativa 9 km (0.1°) invece di 31 km (0.28125°)
# Nota: ERA5-Land non ha msl (pressione), u10/v10/i10fg (vento) e ssrd (radiazione)
# Per queste variabili si usa ERA5 standard in una request separata (vedere sotto)

nc_filename_land    = "era5_land_adriatico.zip"
nc_filename_std     = "era5_std_adriatico.zip"
area_adriatico      = [46.5, 12.0, 39.0, 20.0]

# --- Request ERA5-Land (t2m, tp) a 9 km ---
request_land = {
    'product_type': 'reanalysis',
    'variable': [
        '2m_temperature',
        'total_precipitation',
    ],
    'year': '2025',
    'month': '04',
    'day': ['8', '9', '10'],
    'time': [
        '00:00', '01:00', '02:00', '03:00', '04:00', '05:00',
        '06:00', '07:00', '08:00', '09:00', '10:00', '11:00',
        '12:00', '13:00', '14:00', '15:00', '16:00', '17:00',
        '18:00', '19:00', '20:00', '21:00', '22:00', '23:00',
    ],
    'data_format': 'netcdf',
    'area': area_adriatico,
}

# --- Request ERA5 standard (msl, vento, gust, ssrd) a 31 km ---
# Queste variabili non esistono in ERA5-Land, si scaricano dal dataset standard
request_std = {
    'product_type': 'reanalysis',
    'variable': [
        'mean_sea_level_pressure',
        '10m_u_component_of_wind',
        '10m_v_component_of_wind',
        'instantaneous_10m_wind_gust',
        'surface_solar_radiation_downwards',
    ],
    'year': '2025',
    'month': '11',
    'day': ['25', '26', '27'],
    'time': [
        '00:00', '01:00', '02:00', '03:00', '04:00', '05:00',
        '06:00', '07:00', '08:00', '09:00', '10:00', '11:00',
        '12:00', '13:00', '14:00', '15:00', '16:00', '17:00',
        '18:00', '19:00', '20:00', '21:00', '22:00', '23:00',
    ],
    'data_format': 'netcdf',
    'area': area_adriatico,
}

# ==========================================
# 3. DOWNLOAD ERA5-LAND
# ==========================================
if not os.path.exists(nc_filename_land):
    print("Scaricamento ERA5-Land in corso (t2m, tp a 9 km)...")
    try:
        client.retrieve('reanalysis-era5-land', request_land, nc_filename_land)
        print(f"Download ERA5-Land completato: {nc_filename_land}")
    except Exception as e:
        print(f"Errore durante il download ERA5-Land: {e}")
        exit()
else:
    print(f"File {nc_filename_land} già presente. Salto il download.")

# ==========================================
# 4. DOWNLOAD ERA5 STANDARD
# ==========================================
if not os.path.exists(nc_filename_std):
    print("Scaricamento ERA5 standard in corso (msl, vento, ssrd a 31 km)...")
    try:
        client.retrieve('reanalysis-era5-single-levels', request_std, nc_filename_std)
        print(f"Download ERA5 standard completato: {nc_filename_std}")
    except Exception as e:
        print(f"Errore durante il download ERA5 standard: {e}")
        exit()
else:
    print(f"File {nc_filename_std} già presente. Salto il download.")


# ==========================================
# 5. FUNZIONE DI DECOMPRESSIONE ZIP
# ==========================================
def estrai_netcdf(zip_path, extract_dir):
    """
    Estrae il primo file .nc da un archivio ZIP.
    Se il file non è uno ZIP, lo restituisce direttamente.
    """
    if not zipfile.is_zipfile(zip_path):
        print(f"File già in formato NetCDF nativo: {zip_path}")
        return zip_path

    print(f"Estrazione ZIP: {zip_path} → {extract_dir}")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)

    file_estratti = glob.glob(os.path.join(extract_dir, "*.nc"))
    if not file_estratti:
        print(f"Errore: nessun file .nc trovato dentro {zip_path}")
        exit()

    # Se il CDS ha restituito due file (instant + accum), li unisce
    if len(file_estratti) > 1:
        print(f"Trovati {len(file_estratti)} file NetCDF, eseguo merge...")
        datasets = [xr.open_dataset(f) for f in sorted(file_estratti)]
        merged = xr.merge(datasets, compat="override")
        merged_path = os.path.join(extract_dir, "merged.nc")
        merged.to_netcdf(merged_path)
        print(f"Merge completato: {merged_path}")
        return merged_path

    return file_estratti[0]

# ==========================================
# 6. APERTURA DATASET
# ==========================================
file_land = estrai_netcdf(nc_filename_land, "era5_land_estracted")
file_std  = estrai_netcdf(nc_filename_std,  "era5_std_estracted")

print("\nApertura dataset ERA5-Land...")
try:
    ds_land = xr.open_dataset(file_land)
except Exception as e:
    print(f"Impossibile aprire ERA5-Land: {e}")
    exit()

print("Apertura dataset ERA5 standard...")
try:
    ds_std = xr.open_dataset(file_std)
except Exception as e:
    print(f"Impossibile aprire ERA5 standard: {e}")
    exit()

print(f"ERA5-Land  — variabili: {list(ds_land.data_vars)}, risoluzione: ~9 km")
print(f"ERA5 std   — variabili: {list(ds_std.data_vars)}, risoluzione: ~31 km")
