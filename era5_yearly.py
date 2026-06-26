import os
import numpy as np
import cdsapi

# ==========================================
# 1. CONFIGURAZIONE CREDENZIALI COPERNICUS
# ==========================================
CDS_URL = "https://cds.climate.copernicus.eu/api"
CDS_KEY = "6e902f49-5d17-4d5e-95d1-8beb80d113ae"

client = cdsapi.Client(url=CDS_URL, key=CDS_KEY)

# ==========================================
# 2. CONFIGURAZIONE
# ==========================================
area_adriatico = [46.5, 12.0, 39.0, 20.0]  # [N, W, S, E]
anno = '2024'

tutti_i_mesi = [str(i).zfill(2) for i in range(1, 13)]
tutti_i_giorni = [str(i).zfill(2) for i in range(1, 32)]
tutte_le_ore = [f"{i:02d}:00" for i in range(24)]

cartella_dati = "dati_storici"
os.makedirs(cartella_dati, exist_ok=True)

# ==========================================
# 3. DOWNLOAD ERA5 STANDARD - INTERO ANNO
#    Un singolo file NetCDF con tutti i 12 mesi
# ==========================================

nc_filename = os.path.join(cartella_dati, f"era5_std_adriatico_{anno}_yearly.nc")

request_std = {
    'product_type': 'reanalysis',
    'variable': [
        'mean_sea_level_pressure',
        '10m_u_component_of_wind',
        '10m_v_component_of_wind',
        'instantaneous_10m_wind_gust',
    ],
    'year': anno,
    'month': tutti_i_mesi,
    'day': tutti_i_giorni,
    'time': tutte_le_ore,
    'data_format': 'netcdf',
    'area': area_adriatico,
}

print(f"=========================================")
print(f"ERA5 Standard - Download annuale {anno}")
print(f"=========================================")
print(f"Variabili: msl, u10, v10, i10fg")
print(f"Area: {area_adriatico}")
print(f"Mesi: tutti (01-12)")
print(f"Ore: tutte (00-23)")
print(f"Output: {nc_filename}")
print(f"=========================================")

if not os.path.exists(nc_filename):
    print(f"\n-> Scarico ERA5 Standard anno {anno}...")
    print(f"   (potrebbe richiedere 30-60 minuti)")
    try:
        client.retrieve('reanalysis-era5-single-levels', request_std, nc_filename)
        print(f"\nDOWNLOAD COMPLETATO: {nc_filename}")
        print(f"Dimensione file: {os.path.getsize(nc_filename) / 1e9:.2f} GB")
    except Exception as e:
        print(f"Errore download: {e}")
else:
    print(f"\n-> File già presente: {nc_filename}")
    print(f"   Dimensione: {os.path.getsize(nc_filename) / 1e9:.2f} GB")

# ==========================================
# 4. VERIFICA
# ==========================================
import xarray as xr

print(f"\nVerifica dataset...")
try:
    ds = xr.open_dataset(nc_filename)
    t_coord = 'valid_time' if 'valid_time' in ds.coords else 'time'
    print(f"  Timesteps:  {len(ds[t_coord])}")
    print(f"  Variabili:  {list(ds.data_vars)}")
    print(f"  Periodo:    {str(ds[t_coord].values[0])[:19]} → {str(ds[t_coord].values[-1])[:19]}")
    print(f"  Griglia:    lat={len(ds.latitude)} x lon={len(ds.longitude)}")
    for v in ds.data_vars:
        print(f"  {v}: shape={ds[v].shape}")
    ds.close()
    print(f"\nFile OK!")
except Exception as e:
    print(f"Errore apertura: {e}")
