import os
import glob
import numpy as np
import pandas as pd
import xarray as xr
import cdsapi
import zipfile

# ==========================================
# 7. ESTRAZIONE DATI PER LE STAZIONI DPC
# ==========================================
dpc_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fvg_csv_latest_by_station")
dpc_files  = glob.glob(os.path.join(dpc_folder, "*.csv"))

risultati_finali = []

if not dpc_files:
    print(f"ATTENZIONE: Nessun file CSV trovato nella cartella '{dpc_folder}'.")
else:
    print(f"\nTrovate {len(dpc_files)} stazioni DPC. Inizio estrazione con interpolazione bilineare...")

    for file in dpc_files:
        try:
            df_stazione = pd.read_csv(file)

            if not df_stazione.empty and 'lat' in df_stazione.columns and 'lon' in df_stazione.columns:
                lat_stazione = float(df_stazione['lat'].iloc[0])
                lon_stazione = float(df_stazione['lon'].iloc[0])
                station_id   = df_stazione['station_id'].iloc[0]   if 'station_id'   in df_stazione.columns else 'Unknown'
                station_name = df_stazione['station_name'].iloc[0] if 'station_name' in df_stazione.columns else 'Unknown'

                # --------------------------------------------------
                # INTERPOLAZIONE BILINEARE
                # .interp() usa i 4 pixel circostanti e interpola
                # linearmente invece di snap al pixel più vicino.
                # Stazioni vicine ricevono valori distinti anche se
                # cadono nello stesso pixel ERA5 con nearest-neighbour.
                # --------------------------------------------------

                # ERA5-Land a 9 km — t2m e tp
                punto_land = ds_land.interp(
                    latitude=lat_stazione,
                    longitude=lon_stazione,
                    method='linear'
                )
                df_land = punto_land.to_dataframe().reset_index()

                # ERA5 standard a 31 km — msl, vento, ssrd
                punto_std = ds_std.interp(
                    latitude=lat_stazione,
                    longitude=lon_stazione,
                    method='linear'
                )
                df_std = punto_std.to_dataframe().reset_index()

                # Merge dei due DataFrame sul timestamp
                # I due dataset hanno risoluzioni diverse ma stesso asse temporale
                df_punto = pd.merge(df_land, df_std, on='valid_time', how='inner',
                                    suffixes=('_land', '_std'))

                # Metadati stazione
                df_punto['station_id']       = station_id
                df_punto['station_name']     = station_name
                df_punto['lat_stazione_dpc'] = lat_stazione
                df_punto['lon_stazione_dpc'] = lon_stazione

                # --------------------------------------------------
                # CONVERSIONI UNITÀ
                # --------------------------------------------------

                # Temperature: K → °C (da ERA5-Land a 9 km)
                if 't2m' in df_punto.columns:
                    df_punto['t2m_celsius'] = df_punto['t2m'] - 273.15

                # Pressure: Pa → hPa (da ERA5 standard a 31 km)
                if 'msl' in df_punto.columns:
                    df_punto['mslp_hpa'] = df_punto['msl'] / 100

                # Wind speed e direzione dai componenti U e V (ERA5 standard)
                if 'u10' in df_punto.columns and 'v10' in df_punto.columns:
                    df_punto['wind_speed_10m'] = (
                        (df_punto['u10'] ** 2 + df_punto['v10'] ** 2) ** 0.5
                    )
                    df_punto['wind_dir_10m'] = (
                        (270 - np.degrees(np.arctan2(df_punto['v10'], df_punto['u10']))) % 360
                    )

                # Wind gust: già in m/s (ERA5 standard)
                if 'i10fg' in df_punto.columns:
                    df_punto['wind_gust_10m'] = df_punto['i10fg']

                # Precipitazione: m → mm (da ERA5-Land a 9 km)
                if 'tp' in df_punto.columns:
                    df_punto['tp_mm'] = df_punto['tp'] * 1000

                # Radiazione solare: J/m² → W/m² (ERA5 standard)
                if 'ssrd' in df_punto.columns:
                    df_punto['ssrd_wm2'] = df_punto['ssrd'] / 3600

                # --------------------------------------------------
                # ACCUMULI PRECIPITAZIONE SU FINESTRE TEMPORALI
                # --------------------------------------------------
                if 'tp_mm' in df_punto.columns and 'valid_time' in df_punto.columns:
                    df_punto = df_punto.sort_values('valid_time').reset_index(drop=True)

                    for window in [3, 6, 12, 24]:
                        df_punto[f'tp_{window}h_mm'] = (
                            df_punto['tp_mm']
                            .rolling(window=window, min_periods=window)
                            .sum()
                        )

                risultati_finali.append(df_punto)

        except Exception as e:
            print(f"Errore processando il file {file}: {e}")


# ==========================================
# 8. SALVATAGGIO DEL DATASET UNIFICATO
# ==========================================
if risultati_finali:
    df_finale = pd.concat(risultati_finali, ignore_index=True)

    colonne_ordine = [
        'station_id', 'station_name', 'lat_stazione_dpc', 'lon_stazione_dpc',
        'valid_time',
        # Temperature — da ERA5-Land 9 km
        't2m_celsius',
        # Pressure — da ERA5 standard 31 km
        'mslp_hpa',
        # Wind — da ERA5 standard 31 km
        'u10', 'v10', 'wind_speed_10m', 'wind_dir_10m',
        # Gust — da ERA5 standard 31 km
        'wind_gust_10m',
        # Precipitation — da ERA5-Land 9 km + rolling windows
        'tp_mm', 'tp_3h_mm', 'tp_6h_mm', 'tp_12h_mm', 'tp_24h_mm',
        # Solar radiation — da ERA5 standard 31 km
        'ssrd_wm2',
    ]

    colonne_presenti = [c for c in colonne_ordine if c in df_finale.columns]
    df_finale = df_finale[colonne_presenti]

    output_folder = "StormEngine"
    os.makedirs(output_folder, exist_ok=True)

    output_csv = os.path.join(output_folder, "era5_estratto_per_stazioni.csv")
    df_finale.to_csv(output_csv, index=False)

    print(f"\nOperazione completata! Dataset salvato in: {output_csv}")
    print(f"   Righe totali : {len(df_finale)}")
    print(f"   Colonne      : {list(df_finale.columns)}")
    print("\nAnteprima:")
    print(df_finale.head())
else:
    print("\nNessun dato estratto. Verifica i file CSV di partenza.")