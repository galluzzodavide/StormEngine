

import io
import json
import os
import pickle
import time
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


# =====================================================
# OUTPUT / GOOGLE DRIVE CONFIGURATION
# =====================================================
CSV_FILENAME = "adriatic_balkan_virtual_latest.csv"

DRIVE_PARENT_FOLDER_ID = "10m3UanSMsKWUEqPCfgRNqTih99-e_941"
DRIVE_SENSOR_FOLDER_NAME = "open_meteo_virtual_sensors"
GOOGLE_CREDENTIALS_FILE = "credentials.json"
GOOGLE_TOKEN_FILE = "token.pickle"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


# =====================================================
# OPEN-METEO CONFIGURATION
# =====================================================
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

OPEN_METEO_CURRENT_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "rain",
    "precipitation",
    "shortwave_radiation",
]

SENSORS_MAP = {
    "temperature_2m": ("TARIA2M", "Air temperature at 2 m", "°C"),
    "relative_humidity_2m": ("UR", "Relative humidity", "%"),
    "surface_pressure": ("PRESS", "Atmospheric pressure", "hPa"),
    "wind_speed_10m": ("VV", "Wind speed", "m/s"),
    "wind_direction_10m": ("DV", "Wind direction", "degree"),
    "wind_gusts_10m": ("GUST", "Wind gust", "m/s"),
    "rain": ("RAIN", "Rain", "mm"),
    "precipitation": ("PREC", "Precipitation", "mm"),
    "shortwave_radiation": ("RAD", "Shortwave radiation", "W/m²"),
}


# =====================================================
# GOOGLE DRIVE HELPERS
# =====================================================
def get_drive_service():
    """
    Returns an authenticated Google Drive service.
    The first run opens the browser for OAuth authorization.
    """
    creds = None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        with open(GOOGLE_TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            raise FileNotFoundError(
                f"OAuth file not found: {GOOGLE_CREDENTIALS_FILE}. "
                "Download the JSON file from Google Cloud and rename it to credentials.json."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_FILE,
            DRIVE_SCOPES,
        )
        creds = flow.run_local_server(port=0)

    with open(GOOGLE_TOKEN_FILE, "wb") as token:
        pickle.dump(creds, token)

    return build("drive", "v3", credentials=creds)


def get_or_create_drive_folder(service, folder_name, parent_folder_id):
    """
    Finds a subfolder inside the parent folder, or creates it if missing.
    Returns the Google Drive folder ID.
    """
    query = (
        f"name = '{folder_name}' and "
        f"'{parent_folder_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    response = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()

    files = response.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    created = service.files().create(body=metadata, fields="id").execute()
    print(f"Drive folder created: {folder_name} ({created['id']})")
    return created["id"]


def find_existing_drive_file(service, filename, parent_folder_id):
    """
    Looks for an existing file with the same name in the target folder.
    Returns the file ID if it exists, otherwise None.
    """
    safe_name = filename.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' and "
        f"'{parent_folder_id}' in parents and trashed = false"
    )
    response = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()

    files = response.get("files", [])
    return files[0]["id"] if files else None


def upload_dataframe_to_drive_csv(service, df, filename, parent_folder_id, replace=True):
    """
    Uploads a pandas DataFrame to Google Drive as a CSV directly from memory.
    No local CSV file is created.
    """
    csv_text = df.to_csv(index=False)
    csv_bytes = csv_text.encode("utf-8")

    media = MediaIoBaseUpload(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        resumable=True,
    )

    existing_file_id = find_existing_drive_file(service, filename, parent_folder_id)

    if existing_file_id and replace:
        updated = service.files().update(
            fileId=existing_file_id,
            media_body=media,
            fields="id, name, size, modifiedTime",
        ).execute()
        print(f"Drive CSV updated: {updated['name']} ({updated['id']})")
        return updated

    if existing_file_id and not replace:
        print(f"Drive CSV already exists. Skipping upload: {filename} ({existing_file_id})")
        return {"id": existing_file_id, "name": filename}

    metadata = {
        "name": filename,
        "parents": [parent_folder_id],
        "mimeType": "text/csv",
    }
    created = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, size, modifiedTime",
    ).execute()
    print(f"Drive CSV uploaded: {created['name']} ({created['id']})")
    return created


# =====================================================
# VIRTUAL COASTAL STATION NETWORK
# =====================================================
def generate_adriatic_balkan_stations():
    """
    Returns virtual coastal nodes along the Adriatic and nearby Balkan coastal corridor.
    These are not real ARPA/ARTA stations; they are Open-Meteo virtual sampling points.
    """
    return {
        # Veneto
        "veneto_chioggia": (45.2196, 12.2787),
        "veneto_venezia_lido": (45.4100, 12.3700),
        "veneto_jesolo": (45.5330, 12.6440),
        "veneto_caorle": (45.5960, 12.8870),
        "veneto_bibione": (45.6350, 13.0530),

        # Emilia-Romagna
        "emilia_goro": (44.8510, 12.3040),
        "emilia_comacchio": (44.6940, 12.1820),
        "emilia_ravenna": (44.4170, 12.2010),
        "emilia_cervia": (44.2630, 12.3480),
        "emilia_cesenatico": (44.2000, 12.3990),
        "emilia_rimini": (44.0678, 12.5695),
        "emilia_cattolica": (43.9630, 12.7380),

        # Marche
        "marche_pesaro": (43.9120, 12.9150),
        "marche_fano": (43.8430, 13.0190),
        "marche_senigallia": (43.7140, 13.2180),
        "marche_ancona": (43.6158, 13.5189),
        "marche_numana": (43.5110, 13.6210),
        "marche_civitanova": (43.3060, 13.7280),
        "marche_san_benedetto": (42.9550, 13.8840),

        # Abruzzo
        "abruzzo_martinsicuro": (42.8830, 13.9160),
        "abruzzo_giulianova": (42.7530, 13.9660),
        "abruzzo_roseto": (42.6760, 14.0170),
        "abruzzo_pescara": (42.4618, 14.2161),
        "abruzzo_ortona": (42.3500, 14.4030),
        "abruzzo_vasto": (42.1120, 14.7080),

        # Molise
        "molise_termoli": (42.0000, 14.9940),

        # Puglia
        "puglia_lesina": (41.8610, 15.3530),
        "puglia_vieste": (41.8820, 16.1760),
        "puglia_manfredonia": (41.6300, 15.9180),
        "puglia_barletta": (41.3190, 16.2840),
        "puglia_bari": (41.1253, 16.8667),
        "puglia_monopoli": (40.9550, 17.2900),
        "puglia_brindisi": (40.6320, 17.9360),
        "puglia_otranto": (40.1460, 18.4910),
        "puglia_leuca": (39.7990, 18.3550),
        "puglia_gallipoli": (40.0560, 17.9900),
        "puglia_taranto": (40.4640, 17.2470),

        # Slovenia / Croatia / Montenegro / Albania for wider Adriatic-Balkan context
        "slovenia_koper": (45.5480, 13.7300),
        "croatia_pula": (44.8666, 13.8496),
        "croatia_rijeka": (45.3271, 14.4422),
        "croatia_zadar": (44.1194, 15.2314),
        "croatia_split": (43.5081, 16.4402),
        "croatia_dubrovnik": (42.6507, 18.0944),
        "montenegro_kotor": (42.4247, 18.7712),
        "montenegro_bar": (42.1000, 19.1000),
        "albania_shkoder_coast": (41.8700, 19.4300),
        "albania_durres": (41.3231, 19.4414),
        "albania_vlore": (40.4661, 19.4914),
        "albania_sarande": (39.8750, 20.0050),
    }


def determine_region(station_name):
    """
    Extracts a simple region/country tag from the virtual station name.
    """
    return station_name.split("_")[0]


# =====================================================
# OPEN-METEO FETCHING
# =====================================================
def fetch_open_meteo_data(lat, lon, timeout=30):
    """
    Fetches current weather values from Open-Meteo for one virtual station.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join(OPEN_METEO_CURRENT_VARIABLES),
        "timezone": "UTC",
    }

    response = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload.get("current", {})


def build_observation_rows(stations):
    """
    Fetches Open-Meteo data for all stations and returns rows for a unified long-format table.
    """
    rows = []
    run_timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"\nFetching Open-Meteo data for {len(stations)} virtual stations...")

    for idx, (station_name, (lat, lon)) in enumerate(stations.items(), start=1):
        if idx == 1 or idx % 10 == 0 or idx == len(stations):
            print(f"  Progress: {idx}/{len(stations)}")

        try:
            data = fetch_open_meteo_data(lat, lon)
        except Exception as e:
            print(f"  Warning: failed to fetch {station_name}: {e}")
            continue

        region = determine_region(station_name)
        observation_time = data.get("time", run_timestamp)

        for api_key, (sensor_code, quantity, unit) in SENSORS_MAP.items():
            value = data.get(api_key)
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue

            # Open-Meteo returns wind speed and gusts in km/h by default. Convert them to m/s.
            if api_key in {"wind_speed_10m", "wind_gusts_10m"}:
                value = round(float(value) / 3.6, 2)

            rows.append({
                "station_id": f"VIRT_{station_name}",
                "sensor_name": f"Virtual - {station_name.replace('_', ' ')}",
                "sensor_code": sensor_code,
                "quantity": quantity,
                "unit": unit,
                "dt": observation_time,
                "value": value,
                "lat": lat,
                "lon": lon,
                "codseqst": f"99{str(lat).replace('.', '')[:4]}{str(lon).replace('.', '')[:4]}",
                "point": json.dumps({"type": "Point", "coordinates": [lon, lat]}),
                "quota": 10.0,
                "aggiornamento": run_timestamp,
                "gestore": f"VIRTUAL_{region.upper()}",
                "provincia": region,
                "provider": "Open-Meteo",
                "source_type": "virtual_sensor_nwp_interpolated",
            })

        # Gentle throttling to keep the API calls polite and stable.
        if idx % 50 == 0:
            time.sleep(1)

    return rows


# =====================================================
# MAIN PIPELINE
# =====================================================
def run_pipeline():
    stations = generate_adriatic_balkan_stations()

    print("Connecting to Google Drive...")
    try:
        drive_service = get_drive_service()
        drive_sensor_folder_id = get_or_create_drive_folder(
            drive_service,
            DRIVE_SENSOR_FOLDER_NAME,
            DRIVE_PARENT_FOLDER_ID,
        )
    except Exception as e:
        print(f"Error initializing Google Drive: {e}")
        return

    rows = build_observation_rows(stations)
    if not rows:
        print("Error: no Open-Meteo observations were retrieved.")
        return

    output_df = pd.DataFrame(rows)

    print("\nUploading CSV directly to Google Drive from memory...")
    try:
        upload_result = upload_dataframe_to_drive_csv(
            drive_service,
            output_df,
            CSV_FILENAME,
            drive_sensor_folder_id,
            replace=True,
        )
    except Exception as e:
        print(f"Error uploading CSV to Google Drive: {e}")
        return

    n_stations = output_df["station_id"].nunique()
    summary = output_df.drop_duplicates("station_id").groupby("provincia").size()

    print("-" * 60)
    print("SUCCESS! Open-Meteo virtual sensor network uploaded to Drive.")
    print(f"  Unique stations:     {n_stations}")
    print(f"  Total observations:  {len(output_df)}")
    print(f"  Drive file:          {upload_result.get('name')} ({upload_result.get('id')})")
    print("-" * 60)
    print("\nStations per region:")
    print(summary.to_string())


if __name__ == "__main__":
    run_pipeline()