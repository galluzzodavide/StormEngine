#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StormEngine - Modulo Data Aggregation ARPAV (Veneto)
Scarica le misurazioni in tempo reale tramite le API JSON dirette per
Temperatura, Precipitazione, Umidità, Vento, Pressione e Radiazione.
Normalizza i dati e genera un unico CSV aggregato (tutte le stazioni Veneto).
"""

import requests
import pandas as pd
from pathlib import Path

# ==========================================
# 1. CONFIGURAZIONE URL E PATH
# ==========================================
# Lista di tutti gli endpoint API scoperti
API_URLS = [
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=18&orario=0",  # Temperatura (orario=0)
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=23&orario=-1", # Precipitazione
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=19&orario=-1", # Umidità
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=12&orario=-1", # Vento (Vel/Dir)
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=20&orario=-1"  # Pressione
]

OUT_DIR = Path("./ARPAV_veneto")
OUT_FILE = OUT_DIR / "ARPAV_latest.csv"

# ==========================================
# 2. MOTORE DI ESTRAZIONE E PULIZIA
# ==========================================
def run_arpav_harvester():
    print(">>> Avvio harvester Multi-Variabile ARPAV (Veneto)...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tutti_i_dati = []

    try:
        # A. Chiamata HTTP ciclica per ogni URL (Temperatura, Vento, Pioggia...)
        for url in API_URLS:
            # Per log, estraiamo l'id variabile dall'URL (es. coordcd=23)
            var_id = url.split("coordcd=")[1].split("&")[0] if "coordcd=" in url else "unknown"
            print(f" -> Scaricamento dati variabile [{var_id}]...")

            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                json_data = response.json()

                if "data" in json_data and isinstance(json_data["data"], list):
                    tutti_i_dati.extend(json_data["data"])
                    print(f"    ✔ Ricevuti {len(json_data['data'])} record.")
                else:
                    print(f"    ⚠ Attenzione: chiave 'data' mancante per l'URL {url}")

            except Exception as e:
                print(f"    ✖ Errore scaricamento URL {url}: {e}")

        if not tutti_i_dati:
            print("ERRORE CRITICO: Nessun dato scaricato da nessun URL. Impossibile procedere.")
            return

        # Creiamo un unico DataFrame con TUTTE le variabili aggregate
        df_arpav = pd.DataFrame(tutti_i_dati)
        print(f"\n -> Trovate {len(df_arpav)} misurazioni totali aggregate in Veneto.")

        # B. Uniformazione Nomi Colonne (Standard StormEngine)
        mappa_colonne = {
            "codice_stazione": "station_id",
            "tipo": "sensor_code",        # es. TARIA2M, VVENTO
            "nome_sensore": "quantity",   # es. Temperatura aria a 2m
            "misura": "unit",             # es. °C, m/s
            "dataora": "dt",              # timestamp
            "valore": "value",
            "latitudine": "lat",
            "longitudine": "lon",
            "nome_stazione": "sensor_name"
        }
        df_arpav.rename(columns=mappa_colonne, inplace=True)

        # C. Pulizia tipi numerici
        df_arpav["lon"] = pd.to_numeric(df_arpav["lon"], errors="coerce")
        df_arpav["lat"] = pd.to_numeric(df_arpav["lat"], errors="coerce")
        df_arpav["value"] = pd.to_numeric(df_arpav["value"], errors="coerce")

        # Eliminiamo righe con valori invalidi di base
        df_arpav.dropna(subset=["lat", "lon", "value"], inplace=True)
        print(f" -> Misurazioni valide trovate: {len(df_arpav)}")

        stazioni = df_arpav["sensor_name"].dropna().unique()
        print(" -> Stazioni trovate:", stazioni)

        # D. Salvataggio su disco
        if not df_arpav.empty:
            # Ordiniamo per stazione e poi per orario/variabile per avere un CSV leggibile
            df_arpav.sort_values(by=["station_id", "dt", "sensor_code"], inplace=True)

            colonne_preferite = ["station_id", "sensor_name", "sensor_code", "quantity", "unit", "dt", "value", "lat", "lon"]
            colonne_finali = [c for c in colonne_preferite if c in df_arpav.columns] + \
                             [c for c in df_arpav.columns if c not in colonne_preferite]

            df_arpav = df_arpav[colonne_finali]
            df_arpav.to_csv(OUT_FILE, index=False, encoding="utf-8")
            print(f"\n✔ Salvataggio completato con successo: {OUT_FILE}")
        else:
            print("\nNessun dato valido da salvare.")

    except Exception as e:
        print(f"ERRORE CRITICO generale durante il processing: {e}")

if __name__ == "__main__":
    run_arpav_harvester()