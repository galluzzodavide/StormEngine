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
CDS_KEY = "6e902f49-5d17-4d5e-95d1-8beb80d113ae" # La tua chiave

client = cdsapi.Client(url=CDS_URL, key=CDS_KEY)

# ==========================================
# 2. DEFINIZIONE VARIABILI E LOOP ANNUALE
# ==========================================
area_adriatico = [46.5, 12.0, 39.0, 20.0]
anno = '2022' # Usiamo un anno completo e concluso

# Creiamo le liste dinamiche per tutti i giorni, ore e mesi
tutti_i_giorni = [str(i).zfill(2) for i in range(1, 32)] # Da '01' a '31'
tutte_le_ore = [f"{i:02d}:00" for i in range(24)]        # Da '00:00' a '23:00'
tutti_i_mesi = [str(i).zfill(2) for i in range(1, 13)]   # Da '01' a '12'

# Creiamo una cartella principale per i dati
cartella_dati = "dati_storici"
os.makedirs(cartella_dati, exist_ok=True)

# ==========================================
# 3 & 4. DOWNLOAD ERA5-LAND E ERA5 STD (MESE PER MESE)
# ==========================================
for mese in tutti_i_mesi:
    nc_filename_land = os.path.join(cartella_dati, f"era5_land_adriatico_{anno}_{mese}.zip")
    nc_filename_std  = os.path.join(cartella_dati, f"era5_std_adriatico_{anno}_{mese}.zip")

    # --- Request ERA5-Land (t2m, tp) a 9 km ---
    request_land = {
        'product_type': 'reanalysis',
        'variable': ['2m_temperature', 'total_precipitation'],
        'year': anno,
        'month': mese,
        'day': tutti_i_giorni, # L'API ignora i giorni inesistenti (es. 31 Feb)
        'time': tutte_le_ore,
        'data_format': 'netcdf',
        'area': area_adriatico,
    }

    # --- Request ERA5 standard (msl, vento, gust, ssrd) a 31 km ---
    request_std = {
        'product_type': 'reanalysis',
        'variable': [
            'mean_sea_level_pressure',
            '10m_u_component_of_wind',
            '10m_v_component_of_wind',
            'instantaneous_10m_wind_gust',
            'surface_solar_radiation_downwards',
        ],
        'year': anno,
        'month': mese,
        'day': tutti_i_giorni,
        'time': tutte_le_ore,
        'data_format': 'netcdf',
        'area': area_adriatico,
    }

    print(f"\n=========================================")
    print(f"Scaricamento dati per: {mese}/{anno}")
    print(f"=========================================")

    # Scarica ERA5-Land
    if not os.path.exists(nc_filename_land):
        print(f"-> Scarico ERA5-Land Mese {mese}...")
        try:
            client.retrieve('reanalysis-era5-land', request_land, nc_filename_land)
        except Exception as e:
            print(f"Errore ERA5-Land mese {mese}: {e}")
    else:
        print(f"-> ERA5-Land Mese {mese} già presente. Salto il download.")

    # Scarica ERA5 Standard
    if not os.path.exists(nc_filename_std):
        print(f"-> Scarico ERA5 Std Mese {mese}...")
        try:
            client.retrieve('reanalysis-era5-single-levels', request_std, nc_filename_std)
        except Exception as e:
            print(f"Errore ERA5 Std mese {mese}: {e}")
    else:
        print(f"-> ERA5 Std Mese {mese} già presente. Salto il download.")


# ==========================================
# 5. ESTRAZIONE DI TUTTI I FILE ZIP MENSILI
# ==========================================
def estrai_tutti_zip(cartella_origine, prefisso, cartella_destinazione):
    """
    Cerca tutti gli ZIP con un certo prefisso (es. 'era5_land') e li estrae.
    Ritorna il pattern (wildcard) per leggere i file .nc estratti.
    """
    os.makedirs(cartella_destinazione, exist_ok=True)
    zip_files = glob.glob(os.path.join(cartella_origine, f"{prefisso}*.zip"))
    
    if not zip_files:
        print(f"Nessun file zip trovato con prefisso {prefisso}")
        return None

    print(f"\nEstrazione archivi {prefisso} in {cartella_destinazione}...")
    for zip_path in sorted(zip_files):
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Estrae sovrascrivendo i file omonimi (spesso Copernicus li chiama data.nc)
            # Per evitare sovrascritture, estraiamo rinominando se necessario, 
            # ma Copernicus di solito genera nomi unici se li scarichiamo separatamente.
            
            # Estrazione sicura: rinomina il file estratto con il nome dello zip
            for info in zip_ref.infolist():
                if info.filename.endswith('.nc'):
                    estratto = zip_ref.extract(info, cartella_destinazione)
                    nuovo_nome = os.path.join(cartella_destinazione, os.path.basename(zip_path).replace('.zip', '.nc'))
                    os.rename(estratto, nuovo_nome)
                    
    return os.path.join(cartella_destinazione, "*.nc")

# Estraiamo separatamente Land e Standard
pattern_nc_land = estrai_tutti_zip(cartella_dati, "era5_land", os.path.join(cartella_dati, "estratto_land"))
pattern_nc_std  = estrai_tutti_zip(cartella_dati, "era5_std", os.path.join(cartella_dati, "estratto_std"))


# ==========================================
# 6. APERTURA DATASET ANNUALE CON XARRAY
# ==========================================
print("\nApertura dataset ERA5-Land (Annuale)...")
try:
    # open_mfdataset carica più file .nc contemporaneamente e li concatena lungo la dimensione del tempo ('time')
    # chunks={'time': 100} previene il crash della RAM caricando i dati a blocchi (Lazy Loading)
    ds_land = xr.open_mfdataset(pattern_nc_land, combine='by_coords', chunks={'time': 100})
    print(f"ERA5-Land caricato! Totale istanti temporali: {len(ds_land.time)}")
    print(f"Variabili: {list(ds_land.data_vars)}")
except Exception as e:
    print(f"Impossibile aprire i file ERA5-Land: {e}")

print("\nApertura dataset ERA5 standard (Annuale)...")
try:
    ds_std = xr.open_mfdataset(pattern_nc_std, combine='by_coords', chunks={'time': 100})
    print(f"ERA5 standard caricato! Totale istanti temporali: {len(ds_std.time)}")
    print(f"Variabili: {list(ds_std.data_vars)}")
except Exception as e:
    print(f"Impossibile aprire i file ERA5 standard: {e}")

# Adesso ds_land e ds_std contengono un intero anno di dati (circa 8760 o 8784 ore) 
# pronti per alimentare il SetConv!