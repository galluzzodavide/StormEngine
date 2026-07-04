"""
Download REAL physical station sensor observations from MeteoHub
(Agenzia ItaliaMeteo + Cineca) for the Italian Adriatic coast.

ONLY real physical sensors — no radar, no model/forecast data.
Output: single CSV file, schema matching the rest of the project
(station_id, sensor_code, dt, value, lat, lon, ...).

══════════════════════════════════════════════════════════════
SETUP
══════════════════════════════════════════════════════════════
    $env:MH_USERNAME="your_email@example.com"
    $env:MH_PASSWORD="your_password"
    python -u meteohub.py

══════════════════════════════════════════════════════════════
DATA FORMAT NOTES
══════════════════════════════════════════════════════════════
The observation API returns JSON Lines using WMO BUFR Table B codes,
not descriptive names. Each line = one station at one timestamp, with
a list of nested "data" blocks. The first block always carries station
metadata (name, lat/lon, elevation); subsequent blocks carry measurements.

Relevant codes used here:
  B01019 = station name        B05001 = latitude (deg)
  B01194 = network              B06001 = longitude (deg)
  B07030 = station height (m)
  B12101 = temperature (K)      -> convert to °C (-273.15)
  B10004 = pressure (Pa)        -> convert to hPa (/100)
  B11002 = wind speed (m/s)     -> no conversion
  B13011 = precipitation (mm)   -> no conversion
"""

import os
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

print(">>> SCRIPT STARTED <<<")

# ══════════════════════════════════════════════════════════════
# 1. CONFIGURAZIONE
# ══════════════════════════════════════════════════════════════

BASE_URL = "https://meteohub.agenziaitaliameteo.it"
LOGIN_URL = f"{BASE_URL}/auth/login"
DATA_REQUEST_URL = f"{BASE_URL}/api/data"
REQUESTS_LIST_URL = f"{BASE_URL}/api/requests"
DATA_DOWNLOAD_URL = f"{BASE_URL}/api/data"

OUTPUT_DIR = "MeteoHub_Adriatic"
CSV_FILENAME = "adriatic_coast_stations.csv"

USERNAME = os.environ.get("MH_USERNAME")
PASSWORD = os.environ.get("MH_PASSWORD")

# ── Reti DPC Nazionale lungo la costa adriatica italiana ────────────────────
OBSERVATION_DATASET_IDS = [
    "dpcn-marche",
]

# ── Bounding box costa adriatica italiana ───────────────────────────────────
AREA = {
    "lat_min": 39.5,
    "lat_max": 46.5,
    "lon_min": 12.0,
    "lon_max": 19.0,
}

# ── Mappa codici WMO Table B -> schema variabili del progetto ──────────────
WMO_VAR_MAP = {
    "B12101": ("TARIA2M", "Temperatura aria a 2m", "°C", lambda v: v - 273.15),
    "B10004": ("PRESS",   "Pressione atmosferica", "hPa", lambda v: v / 100.0),
    "B11002": ("VV",      "Velocità vento",         "m/s", lambda v: v),
    "B13011": ("PREC",    "Precipitazione",         "mm",  lambda v: v),
}

DAYS_BACK = 3
TO_TIME = datetime.now(timezone.utc)
FROM_TIME = TO_TIME - timedelta(days=DAYS_BACK)

POLL_INTERVAL_SEC = 15
MAX_POLL_ATTEMPTS = 40


# ══════════════════════════════════════════════════════════════
# 2. Autenticazione
# ══════════════════════════════════════════════════════════════

def login(username, password):
    if not username or not password:
        raise ValueError("MH_USERNAME e MH_PASSWORD devono essere impostate.")

    print("Step 1: Authenticating with MeteoHub...")
    r = requests.post(LOGIN_URL, json={"username": username, "password": password},
                      timeout=30)
    r.raise_for_status()
    data = r.json()
    token = data if isinstance(data, str) else (
        data.get("token") or data.get("access_token") if isinstance(data, dict) else None
    )
    if not token:
        raise RuntimeError("Could not extract token from login response.")
    print("  Login successful.")
    return token


# ══════════════════════════════════════════════════════════════
# 3. Estrazione + polling + download
# ══════════════════════════════════════════════════════════════

def create_data_request(token, dataset_ids, request_name, from_time, to_time):
    print(f"  Requesting extraction for {dataset_ids} "
          f"[{from_time.isoformat()} -> {to_time.isoformat()}]...")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "request_name": request_name,
        "reftime": {"from": from_time.isoformat(), "to": to_time.isoformat()},
        "dataset_names": dataset_ids,
        "filters": {},
        "output_format": "json",
        "only_reliable": True,
    }

    r = requests.post(DATA_REQUEST_URL, json=payload, headers=headers, timeout=60)
    if not r.ok:
        print("  Failed. Status:", r.status_code, "Body:", r.text[:1000])
    r.raise_for_status()

    data = r.json()
    request_id = data.get("id") or data.get("request_id")
    if not request_id:
        raise RuntimeError("Could not extract request_id.")
    print(f"  Request ID: {request_id}")
    return request_id


def wait_for_completion(token, request_id, quiet=False):
    if not quiet:
        print("  Waiting for extraction...")
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        r = requests.get(REQUESTS_LIST_URL, headers=headers, timeout=30)
        r.raise_for_status()
        items = r.json()
        items = items if isinstance(items, list) else items.get("items", [])
        match = next((i for i in items if str(i.get("id")) == str(request_id)), None)

        if match:
            status = match.get("status", "unknown")
            fileoutput = match.get("fileoutput")
            if not quiet:
                print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Status: {status}")
            if fileoutput:
                return fileoutput
            if status in ("FAILED", "ERROR"):
                raise RuntimeError(f"Extraction failed: {status}")
        time.sleep(POLL_INTERVAL_SEC if not quiet else 5)

    raise TimeoutError("Extraction timed out.")


def download_output(token, filename, output_path, quiet=False):
    if not quiet:
        print(f"  Downloading '{filename}'...")
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{DATA_DOWNLOAD_URL}/{filename}", headers=headers,
                     timeout=120, stream=True)
    r.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    if not quiet:
        print(f"  Saved: {output_path}")
    return output_path


# ══════════════════════════════════════════════════════════════
# 4. Conteggio stazioni per rete (probe sulle ultime 6 ore)
# ══════════════════════════════════════════════════════════════

def count_stations_per_network(token, dataset_ids):
    """
    Per ogni rete, fa una richiesta di estrazione su una finestra breve
    (6 ore, più sicura di 1 ora vista la latenza di pubblicazione) e
    conta le stazioni univoche (per nome B01019) trovate.
    """
    print("Step 2: Counting available stations per network (probe request)...")

    probe_to = datetime.now(timezone.utc)
    probe_from = probe_to - timedelta(hours=6)

    counts = {}
    for ds_id in dataset_ids:
        request_id = create_data_request(
            token, [ds_id], f"probe_{ds_id}", probe_from, probe_to
        )
        try:
            fileoutput = wait_for_completion(token, request_id, quiet=True)
            raw_path = os.path.join(OUTPUT_DIR, f"probe_{ds_id}.json")
            download_output(token, fileoutput, raw_path, quiet=True)

            station_names = set()
            with open(raw_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    for block in rec.get("data", []):
                        v = block.get("vars", {})
                        if "B01019" in v:
                            station_names.add(v["B01019"]["v"])

            counts[ds_id] = len(station_names)
            print(f"    {ds_id}: {len(station_names)} stazioni attive (ultime 6h)")
            os.remove(raw_path)
        except Exception as e:
            print(f"    {ds_id}: probe failed ({e})")
            counts[ds_id] = None

    return counts


# ══════════════════════════════════════════════════════════════
# 5. Parsing BUFR + filtro + CSV finale
# ══════════════════════════════════════════════════════════════

def build_final_csv(raw_json_path, output_csv_path):
    print("Step 6: Parsing BUFR-style records and filtering...")

    records = []
    with open(raw_json_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"  Total raw records (timestamps): {len(records)}")

    rows = []
    for rec in records:
        network = rec.get("network", "unknown")
        date = rec.get("date", "")
        data_blocks = rec.get("data", [])

        # Il primo blocco contiene sempre i metadati stazione
        station_name, lat, lon, elevation = None, None, None, None
        for block in data_blocks:
            v = block.get("vars", {})
            if "B01019" in v:
                station_name = v["B01019"]["v"]
            if "B05001" in v:
                lat = v["B05001"]["v"]
            if "B06001" in v:
                lon = v["B06001"]["v"]
            if "B07030" in v:
                elevation = v["B07030"]["v"]

        if lat is None or lon is None:
            continue
        if not (AREA["lat_min"] <= lat <= AREA["lat_max"] and
                AREA["lon_min"] <= lon <= AREA["lon_max"]):
            continue

        # Estrai le variabili meteo di interesse da TUTTI i blocchi
        for block in data_blocks:
            v = block.get("vars", {})
            for wmo_code, (s_code, q_name, unit, conv) in WMO_VAR_MAP.items():
                if wmo_code in v:
                    raw_val = v[wmo_code]["v"]
                    if raw_val is None:
                        continue
                    value = conv(raw_val)
                    rows.append({
                        "station_id": f"METEOHUB_{station_name}".replace(" ", "_"),
                        "sensor_name": station_name,
                        "sensor_code": s_code,
                        "quantity": q_name,
                        "unit": unit,
                        "dt": date,
                        "value": round(value, 3),
                        "lat": lat,
                        "lon": lon,
                        "codseqst": station_name,
                        "point": json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                        "quota": elevation if elevation is not None else 0.0,
                        "aggiornamento": datetime.now(timezone.utc).isoformat(),
                        "gestore": f"MeteoHub_{network}",
                        "provincia": "",
                    })

    df = pd.DataFrame(rows)
    df.to_csv(output_csv_path, index=False)
    print(f"  Kept {len(rows)} variable readings from {len(records)} timestamps.")
    print(f"  Unique stations: {df['station_id'].nunique() if len(df) else 0}")
    print(f"  Saved: {output_csv_path}")
    return df


# ══════════════════════════════════════════════════════════════
# 6. Pipeline principale
# ══════════════════════════════════════════════════════════════

def run_pipeline():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    token = login(USERNAME, PASSWORD)

    counts = count_stations_per_network(token, OBSERVATION_DATASET_IDS)
    total = sum(c for c in counts.values() if c is not None)
    print(f"\n  TOTALE stazioni attive stimate: {total}")
    for ds_id, c in counts.items():
        print(f"    {ds_id}: {c if c is not None else 'N/A'}")

    proceed = input("\nProcedere con l'estrazione completa (3 giorni)? [y/N] ")
    if proceed.lower() != "y":
        print("Annullato dall'utente.")
        return

    request_name = f"adriatic_coast_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    request_id = create_data_request(
        token, OBSERVATION_DATASET_IDS, request_name, FROM_TIME, TO_TIME
    )
    fileoutput = wait_for_completion(token, request_id)

    raw_path = os.path.join(OUTPUT_DIR, fileoutput)
    download_output(token, fileoutput, raw_path)

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    df = build_final_csv(raw_path, csv_path)

    print("-" * 55)
    print("SUCCESS!")
    print(f"Final CSV : {csv_path}")
    print(f"Rows      : {len(df)}")
    print(f"Stations  : {df['station_id'].nunique() if len(df) else 0}")
    print("-" * 55)


if __name__ == "__main__":
    run_pipeline()