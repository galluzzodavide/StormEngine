#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FVG – latest per sensore → un unico CSV aggregato (tutte le stazioni FVG)
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
import pandas as pd

# -------------------- Config --------------------
BASE = "https://monitor.protezionecivile.fvg.it"
API  = f"{BASE}/api"
OUT_DIR = Path("./DPC_friuli")

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

# 1) Stazioni — tutte, nessun filtro geografico
df_st = fetch_stations()
print(f"Stazioni totali (da /stations): {len(df_st)}")

saved, errors = 0, []

# Lista per accumulare tutti i dataframe di tutte le stazioni
tutte_le_misure_fvg = []

# 2) Per ciascuna stazione → sensori → latest → accumula in memoria
for _, s in df_st.iterrows():
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

            df_latest["sensor_code"] = row.get("code")
            df_latest["sensor_name"] = row.get("name")
            df_latest["quantity"] = row.get("quantity")
            df_latest["unit"] = row.get("unit")
            latest_rows.append(df_latest)
            time.sleep(PAUSE_BETWEEN_CALLS_SEC)
        except Exception as e:
            errors.append((f"{sid}:{sensor_id}", f"latest_error: {e}"))

    if not latest_rows:
        print(f"(i) Nessuna misura latest per stazione {sid} ({sname})")
        continue

    # Unisce le misurazioni di questa specifica stazione
    df_out = pd.concat(latest_rows, ignore_index=True)
    preferred = ["station_id","sensor_id","sensor_code","sensor_name","quantity","unit","dt","value","lat","lon"]
    cols = preferred + [c for c in df_out.columns if c not in preferred]
    df_out = df_out.reindex(columns=cols)

    saved += 1
    print(f"✔ Processed station {sid} ({sname}) rows={len(df_out)}")

    # Aggiunge il dataframe della stazione alla lista globale
    tutte_le_misure_fvg.append(df_out)

print(f"\nDone. Stazioni elaborate: {saved}. Errori: {len(errors)}")

# ==========================================
# SALVATAGGIO CSV AGGREGATO UNICO
# ==========================================
if tutte_le_misure_fvg:
    print("\nCreazione file aggregato unico in corso...")
    df_fvg_totale = pd.concat(tutte_le_misure_fvg, ignore_index=True)

    # Riordina per stazione e timestamp
    if "dt" in df_fvg_totale.columns:
        df_fvg_totale.sort_values(by=["station_id", "dt"], inplace=True)

    percorso_aggregato = OUT_DIR / "DPC_latest.csv"
    df_fvg_totale.to_csv(percorso_aggregato, index=False, encoding="utf-8")
    print(f"SUCCESSO: Salvato file aggregato globale -> {percorso_aggregato.name} (Totale righe: {len(df_fvg_totale)})")
else:
    print("\nNessun dato valido estratto, impossibile creare il file aggregato.")

if errors:
    print("\nAlcuni errori (primi 8):")
    for item, err in errors[:8]:
        print(" -", item, "→", err)