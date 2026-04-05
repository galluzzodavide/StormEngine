#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StormEngine - Modulo Data Aggregation ARPAV (Veneto)
Scarica le misurazioni in tempo reale tramite le API JSON dirette per
Temperatura, Precipitazione, Umidità, Vento, Pressione e Radiazione.
Normalizza i dati e filtra solo le stazioni sulla costa Veneta, 
generando un unico CSV aggregato.
"""

import requests
import pandas as pd
from pathlib import Path

# Tentativo di importare Shapely per il filtro geografico preciso
try:
    from shapely.geometry import Point, Polygon
    from shapely.prepared import prep
    HAVE_SHAPELY = True
except ImportError:
    HAVE_SHAPELY = False
    print("Avviso: libreria 'shapely' non trovata. Verrà usato un filtro a rettangolo (BBOX).")

# ==========================================
# 1. CONFIGURAZIONE URL E PATH
# ==========================================
# Lista di tutti gli endpoint API scoperti
API_URLS = [
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=18&orario=0",  # Temperatura (orario=0)
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=23&orario=-1", # Precipitazione
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=19&orario=-1", # Umidità
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=12&orario=-1", # Vento (Vel/Dir)
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=22&orario=-1", # Radiazione
    "https://api.arpa.veneto.it/REST/v1/meteo_meteogrammi?rete=MGRAMMI&coordcd=20&orario=-1"  # Pressione
]

OUT_DIR = Path("./veneto_csv_latest")
OUT_FILE = OUT_DIR / "ARPAV_coastal_latest.csv"

# ==========================================
# 2. DEFINIZIONE AREA COSTIERA (VENETO)
# ==========================================
COASTAL_POLYGON = [
    [13.100, 45.650], # Lignano/Bibione
    [12.850, 45.580], # Caorle
    [12.650, 45.500], # Eraclea
    [12.450, 45.430], # Jesolo / Cavallino
    [12.320, 45.450], # VENEZIA (Nuovo punto per includere la laguna)
    [12.300, 45.300], # Lido / Pellestrina
    [12.250, 45.150], # Chioggia
    [12.300, 44.800], # Delta del Po
    [12.800, 44.800], # Mare (Est)
    [13.200, 45.500], # Mare (Nord-Est)
    [13.100, 45.650]  # Chiusura
]

# BBOX leggermente allargato a Ovest per sicurezza
BBOX = (12.20, 44.80, 13.10, 45.65)

def build_polygon(coords_wgs84):
    if not HAVE_SHAPELY: return None
    return prep(Polygon(coords_wgs84))

COASTAL_PREP = build_polygon(COASTAL_POLYGON)

def is_in_coastal_area(lon, lat) -> bool:
    if pd.isna(lon) or pd.isna(lat): return False
    try:
        lon, lat = float(lon), float(lat)
    except ValueError:
        return False
        
    if COASTAL_PREP is not None:
        return COASTAL_PREP.contains(Point(lon, lat))
    
    x1, y1, x2, y2 = BBOX
    return (x1 <= lon <= x2) and (y1 <= lat <= y2)

# ==========================================
# 3. MOTORE DI ESTRAZIONE E PULIZIA
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
                # Disabilitiamo i warning per i certificati SSL se i server ARPAV fanno i capricci,
                # ma usiamo verify=True di default.
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
        
        # C. Filtro Costiero
        print("Applicazione filtro geografico per la costa Veneta...")
        df_arpav["lon"] = pd.to_numeric(df_arpav["lon"], errors="coerce")
        df_arpav["lat"] = pd.to_numeric(df_arpav["lat"], errors="coerce")
        df_arpav["value"] = pd.to_numeric(df_arpav["value"], errors="coerce")
        
        # Eliminiamo righe con valori invalidi di base
        df_arpav.dropna(subset=["lat", "lon", "value"], inplace=True)
        
        # Applichiamo il filtro del poligono (o del BBOX)
        df_costa = df_arpav[df_arpav.apply(lambda r: is_in_coastal_area(r["lon"], r["lat"]), axis=1)].copy()
        print(f" -> Misurazioni costiere valide trovate: {len(df_costa)}")
        
        # Stampa di controllo (opzionale): Mostra quali stazioni ha mantenuto
        stazioni_filtrate = df_costa["sensor_name"].dropna().unique()
        print(" -> Stazioni mantenute dal filtro:", stazioni_filtrate)
        
        # D. Salvataggio su disco
        if not df_costa.empty:
            # Ordiniamo per stazione e poi per orario/variabile per avere un CSV leggibile
            df_costa.sort_values(by=["station_id", "dt", "sensor_code"], inplace=True)
            
            colonne_preferite = ["station_id", "sensor_name", "sensor_code", "quantity", "unit", "dt", "value", "lat", "lon"]
            # Tiene le colonne preferite e aggiunge le rimanenti in fondo
            colonne_finali = [c for c in colonne_preferite if c in df_costa.columns] + \
                             [c for c in df_costa.columns if c not in colonne_preferite]
            
            df_costa = df_costa[colonne_finali]
            df_costa.to_csv(OUT_FILE, index=False, encoding="utf-8")
            print(f"\n✔ Salvataggio completato con successo: {OUT_FILE}")
        else:
            print("\nNessun dato ricade nell'area costiera specificata.")

    except Exception as e:
        print(f"ERRORE CRITICO generale durante il processing: {e}")

if __name__ == "__main__":
    run_arpav_harvester()