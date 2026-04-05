#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FVG – latest per sensore → CSV per stazione (coastal only)
Aggiornato per salvare anche un unico CSV aggregato con tutte le stazioni.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import pandas as pd

# shapely 
try:
    from shapely.geometry import Point, Polygon
    from shapely.prepared import prep
    HAVE_SHAPELY = True
except Exception:
    HAVE_SHAPELY = False

# -------------------- Config --------------------
BASE = "https://monitor.protezionecivile.fvg.it"
API  = f"{BASE}/api"
OUT_DIR = Path("./fvg_csv_latest_by_station")

COASTAL_POLYGON = [
    # --- LATO TERRAFERMA (Passa a filo delle spiagge) ---
    [13.050, 45.650], # Ovest di Lignano (Mare)
    [13.130, 45.705], # Nord di Lignano Sabbiadoro (Esclude Aprilia Marittima)
    [13.300, 45.710], # Nord delle isole lagunari (Marano)
    [13.450, 45.710], # Nord di Grado (Taglia fuori Cervignano e Aquileia)
    [13.550, 45.795], # Nord della costa di Monfalcone
    [13.680, 45.780], # Nord di Duino/Aurisina (Taglia fuori il Carso)
    [13.780, 45.680], # Est di Trieste Centro (Tiene il porto, esclude la collina)
    [13.820, 45.580], # Est di Muggia (Confine Sloveno)
    
    # --- LATO MARE (Chiusura a Sud) ---
    [13.600, 45.500], # In mezzo al Golfo di Trieste
    [13.050, 45.500], # In mare aperto a sud di Lignano
    
    # Chiusura del poligono
    [13.050, 45.650]
]

# Fallback bbox focalizzato SOLO sulla striscia costiera
BBOX = (13.05, 45.55, 13.85, 45.80)

REQ_TIMEOUT = (15, 60)          # (connect, read)
PAUSE_BETWEEN_CALLS_SEC = 0.12  # rate limit gentile

session = requests.Session()

# -------------------- Utils --------------------
def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = session.get(url, params=params or {}, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.json()

def sanitize_filename(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(s))

def build_polygon(coords_wgs84: List[List[float]]):
    if not HAVE_SHAPELY: return None
    return prep(Polygon(coords_wgs84))

COASTAL_PREP = build_polygon(COASTAL_POLYGON)

def is_in_coastal_area(lon: Optional[float], lat: Optional[float]) -> bool:
    if lon is None or lat is None:
        return False
    try:
        lon = float(lon); lat = float(lat)
    except Exception:
        return False
    if COASTAL_PREP is not None:
        return COASTAL_PREP.contains(Point(lon, lat))
    x1, y1, x2, y2 = BBOX
    return (x1 <= lon <= x2) and (y1 <= lat <= y2)

# -------------------- API wrapper --------------------
def fetch_stations() -> pd.DataFrame:
    j = get_json(f"{API}/stations")
    stations = j.get("stations") if isinstance(j, dict) else None
    if not isinstance(stations, list):
        return pd.DataFrame(columns=["id","code","name","lat","lon","alt","status"])
    df = pd.DataFrame(stations)
    for c in ("lat","lon","alt"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def fetch_station_sensors(station_id: int) -> pd.DataFrame:
    j = get_json(f"{API}/stations/{station_id}/sensors")
    sensors = j.get("sensors") if isinstance(j, dict) else None
    if not isinstance(sensors, list):
        return pd.DataFrame(columns=["id","station_id","code","name","quantity","unit","status"])
    df = pd.DataFrame(sensors)
    if "station_id" not in df.columns:
        df["station_id"] = station_id
    return df

def fetch_latest_station_sensor(station_id: int, sensor_id: int) -> pd.DataFrame:
    j = get_json(f"{API}/stations/{station_id}/sensors/{sensor_id}/measures/latest")
    measures = j.get("measures") if isinstance(j, dict) else None
    if not isinstance(measures, list):
        return pd.DataFrame(columns=["station_id","sensor_id","lat","lon","dt","value"])
    df = pd.DataFrame(measures)
    for col, val in (("station_id", station_id), ("sensor_id", sensor_id)):
        if col not in df.columns:
            df[col] = val
    return df

# -------------------- MAIN --------------------
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1) Stazioni
df_st = fetch_stations()
print(f"Stazioni totali (da /stations): {len(df_st)}")

# 2) Filtro costiero sulle stazioni
if {"lat","lon"}.issubset(df_st.columns):
    df_cost = df_st[df_st.apply(lambda r: is_in_coastal_area(r["lon"], r["lat"]), axis=1)].copy()
else:
    df_cost = pd.DataFrame(columns=df_st.columns)
print(f"Stazioni costiere selezionate: {len(df_cost)}")

saved, errors = 0, []

# >>> NUOVO: Lista per accumulare tutti i dataframe di tutte le stazioni <<<
tutte_le_misure_fvg = []

# 3) Per ciascuna stazione costiera → sensori → latest → CSV
for _, s in df_cost.iterrows():
    sid = int(s["id"])
    sname = s.get("name") or f"station_{sid}"
    scode = s.get("code") or ""

    try:
        df_sensors = fetch_station_sensors(sid)
    except Exception as e:
        errors.append((f"{sid}", f"sensors_error: {e}"))
        continue

    if df_sensors.empty:
        print(f"(i) Nessun sensore per stazione {sid} ({sname})")
        continue

    latest_rows: List[pd.DataFrame] = []
    for _, row in df_sensors.iterrows():
        sensor_id = int(row["id"])
        try:
            df_latest = fetch_latest_station_sensor(sid, sensor_id)
            if df_latest.empty:
                continue
            
            if {"lat","lon"}.issubset(df_latest.columns):
                df_latest = df_latest[df_latest.apply(lambda r: is_in_coastal_area(r["lon"], r["lat"]), axis=1)]
                if df_latest.empty:
                    continue
            
            df_latest["sensor_code"] = row.get("code")
            df_latest["sensor_name"] = row.get("name")
            df_latest["quantity"] = row.get("quantity")
            df_latest["unit"] = row.get("unit")
            latest_rows.append(df_latest)
            time.sleep(PAUSE_BETWEEN_CALLS_SEC)
        except Exception as e:
            errors.append((f"{sid}:{sensor_id}", f"latest_error: {e}"))

    if not latest_rows:
        print(f"(i) Nessuna misura latest costiera per stazione {sid} ({sname})")
        continue

    # Unisce le misurazioni di questa specifica stazione
    df_out = pd.concat(latest_rows, ignore_index=True)
    preferred = ["station_id","sensor_id","sensor_code","sensor_name","quantity","unit","dt","value","lat","lon"]
    cols = preferred + [c for c in df_out.columns if c not in preferred]
    df_out = df_out.reindex(columns=cols)

    # Salva il CSV singolo
    base = f"FVG_station_{sanitize_filename(str(sid))}"
    if scode: base += f"_{sanitize_filename(str(scode))}"
    base += f"_{sanitize_filename(str(sname))}"
    fpath = OUT_DIR / f"{base}.csv"
    df_out.to_csv(fpath, index=False, encoding="utf-8")
    saved += 1
    print(f"✔ Saved {fpath.name} rows={len(df_out)}")
    
    # >>> NUOVO: Aggiunge il dataframe della stazione alla lista globale <<<
    tutte_le_misure_fvg.append(df_out)

print(f"\nDone. CSV singoli salvati: {saved}. Errori: {len(errors)}")

# ==========================================
# >>> NUOVO: SALVATAGGIO CSV AGGREGATO FVG <<<
# ==========================================
if tutte_le_misure_fvg:
    print("\nCreazione file aggregato unico in corso...")
    df_fvg_totale = pd.concat(tutte_le_misure_fvg, ignore_index=True)
    
    # Riordina per stazione e timestamp
    if "dt" in df_fvg_totale.columns:
        df_fvg_totale.sort_values(by=["station_id", "dt"], inplace=True)
        
    percorso_aggregato = OUT_DIR / "FVG_coastal_latest_AGGREGATED.csv"
    df_fvg_totale.to_csv(percorso_aggregato, index=False, encoding="utf-8")
    print(f"SUCCESSO: Salvato file aggregato globale -> {percorso_aggregato.name} (Totale righe: {len(df_fvg_totale)})")
else:
    print("\nNessun dato valido estratto, impossibile creare il file aggregato.")

if errors:
    print("\nAlcuni errori (primi 8):")
    for item, err in errors[:8]:
        print(" -", item, "→", err)