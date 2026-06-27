import calendar
import os
import zipfile
import glob
import shutil
import tempfile
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import cdsapi
import xarray as xr

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. CONFIGURAZIONE CREDENZIALI COPERNICUS
# ==========================================
CDS_URL = "https://cds.climate.copernicus.eu/api"

# For local testing only. For safety, prefer using an environment variable:
# export CDSAPI_KEY="your_token"
CDS_KEY = os.environ.get("CDSAPI_KEY", "6e902f49-5d17-4d5e-95d1-8beb80d113ae")
# Do not share one cdsapi.Client across parallel workers.
# Each worker creates its own client to avoid connection-state conflicts.

# ==========================================
# 2. CONFIGURAZIONE
# ==========================================
area_adriatico = [46.5, 12.0, 39.0, 20.0]  # [N, W, S, E]
anno = "2024"

# Parallel CDS requests. 2 or 3 is usually safe; higher values may trigger CDS queue/rate limits.
MAX_PARALLEL_DOWNLOADS = 3

# Google Drive target folder:
# https://drive.google.com/drive/folders/10m3UanSMsKWUEqPCfgRNqTih99-e_941?usp=share_link
DRIVE_FOLDER_ID = "10m3UanSMsKWUEqPCfgRNqTih99-e_941"
# Files will be uploaded into this subfolder under DRIVE_FOLDER_ID.
DRIVE_SUBFOLDER_NAME = f"era5_std_adriatico_{anno}"

SCRIPT_DIR = Path(__file__).resolve().parent
CREDENTIALS_PATH = SCRIPT_DIR / "credentials.json"
TOKEN_PATH = SCRIPT_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

# If True, final NetCDF files are uploaded to Drive and then deleted locally.
# A temporary raw file is still needed because cdsapi.retrieve() writes to a path.
UPLOAD_TO_DRIVE = True
DELETE_LOCAL_AFTER_UPLOAD = True
# CDS downloads run in parallel, but Google Drive upload should be serialized.
DRIVE_UPLOAD_LOCK = threading.Lock()

tutti_i_mesi = [str(i).zfill(2) for i in range(1, 13)]
tutte_le_ore = [f"{i:02d}:00" for i in range(24)]

 # Use a temporary working directory instead of keeping files inside the project.
# Files are uploaded to Google Drive and removed afterwards.
cartella_dati = tempfile.mkdtemp(prefix="era5_yearly_")
cartella_raw = os.path.join(cartella_dati, "raw")
cartella_nc = os.path.join(cartella_dati, "netcdf")

os.makedirs(cartella_raw, exist_ok=True)
os.makedirs(cartella_nc, exist_ok=True)

print(f"[INFO] Temporary working folder: {cartella_dati}")

variabili_std = [
    "mean_sea_level_pressure",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "instantaneous_10m_wind_gust",
]


# ==========================================
# 3. FUNZIONI UTILI
# ==========================================

def giorni_del_mese(year: str, month: str):
    """Return valid day list for a specific year-month."""
    n_days = calendar.monthrange(int(year), int(month))[1]
    return [str(i).zfill(2) for i in range(1, n_days + 1)]


def estrai_o_copia_netcdf(raw_path: str, extract_dir: str, final_nc_path: str) -> str:
    """
    CDS may return either a native NetCDF file or a ZIP containing one or more
    NetCDF files. This function produces one final .nc file.
    """
    if os.path.exists(final_nc_path) and os.path.getsize(final_nc_path) > 0:
        print(f"  -> NetCDF finale già presente: {final_nc_path}")
        return final_nc_path

    if not zipfile.is_zipfile(raw_path):
        print(f"  -> File già in formato NetCDF nativo: {raw_path}")
        shutil.copy2(raw_path, final_nc_path)
        return final_nc_path

    print(f"  -> Estrazione ZIP: {raw_path} → {extract_dir}")

    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(raw_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    file_estratti = sorted(glob.glob(os.path.join(extract_dir, "*.nc")))
    file_estratti = [
        f for f in file_estratti
        if os.path.basename(f) != "merged.nc"
    ]

    if not file_estratti:
        raise RuntimeError(f"Nessun file .nc trovato dentro {raw_path}")

    if len(file_estratti) == 1:
        shutil.copy2(file_estratti[0], final_nc_path)
        print(f"  -> NetCDF estratto: {final_nc_path}")
        return final_nc_path

    print(f"  -> Trovati {len(file_estratti)} file NetCDF, eseguo merge...")
    datasets = [xr.open_dataset(f) for f in file_estratti]
    try:
        merged = xr.merge(datasets, compat="override")
        merged.to_netcdf(final_nc_path)
    finally:
        for ds in datasets:
            ds.close()

    print(f"  -> Merge completato: {final_nc_path}")
    return final_nc_path


def verifica_dataset(nc_path: str):
    """Open and print a compact summary of one monthly NetCDF file."""
    print(f"\nVerifica dataset: {nc_path}")
    try:
        ds = xr.open_dataset(nc_path)
        t_coord = "valid_time" if "valid_time" in ds.coords else "time"

        print(f"  Timesteps:  {len(ds[t_coord])}")
        print(f"  Variabili:  {list(ds.data_vars)}")
        print(f"  Periodo:    {str(ds[t_coord].values[0])[:19]} → {str(ds[t_coord].values[-1])[:19]}")

        if "latitude" in ds.coords and "longitude" in ds.coords:
            print(f"  Griglia:    lat={len(ds.latitude)} x lon={len(ds.longitude)}")

        for v in ds.data_vars:
            print(f"  {v}: shape={ds[v].shape}")

        ds.close()
        print("  File OK!")
    except Exception as e:
        print(f"  Errore apertura: {e}")


def get_drive_service():
    """Authenticate and create a Google Drive service."""
    creds = None

    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

            token_scopes = set(creds.scopes or [])
            required_scopes = set(SCOPES)
            if not required_scopes.issubset(token_scopes):
                print("[WARN] Existing token.json does not have the required Google Drive scope.")
                print("[INFO] Removing token.json and re-authorizing.")
                TOKEN_PATH.unlink(missing_ok=True)
                creds = None
        except Exception as e:
            print(f"[WARN] Could not read token.json: {e}")
            TOKEN_PATH.unlink(missing_ok=True)
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            print("[INFO] Refreshing Google Drive token...")
            creds.refresh(Request())
        except RefreshError as e:
            print(f"[WARN] Google token refresh failed: {e}")
            TOKEN_PATH.unlink(missing_ok=True)
            creds = None

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"credentials.json not found here: {CREDENTIALS_PATH}"
            )

        print("[INFO] Starting Google Drive OAuth flow...")
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)

def get_or_create_drive_subfolder(service, parent_folder_id: str, subfolder_name: str) -> str:
    """Create or reuse a subfolder inside the target Google Drive folder."""
    safe_name = subfolder_name.replace("'", "\\'")

    query = (
        f"name='{safe_name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_folder_id}' in parents "
        f"and trashed=false"
    )

    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
    ).execute()

    folders = result.get("files", [])

    if folders:
        folder_id = folders[0]["id"]
        print(f"[INFO] Drive subfolder exists: {subfolder_name} ({folder_id})")
        return folder_id

    metadata = {
        "name": subfolder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }

    folder = service.files().create(
        body=metadata,
        fields="id",
    ).execute()

    folder_id = folder["id"]
    print(f"[INFO] Created Drive subfolder: {subfolder_name} ({folder_id})")

    return folder_id

def upload_file_to_drive(service, local_file: str, folder_id: str) -> str:
    """Upload one NetCDF file to a Google Drive folder."""
    local_path = Path(local_file)
    file_size_mb = local_path.stat().st_size / (1024 * 1024)
    print(f"[INFO] Uploading to Google Drive: {local_path.name} ({file_size_mb:.2f} MB)")

    file_metadata = {
        "name": local_path.name,
        "parents": [folder_id],
    }

    media = MediaFileUpload(
        str(local_path),
        mimetype="application/x-netcdf",
        chunksize=10 * 1024 * 1024,
        resumable=True,
    )

    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    )

    response = None
    while response is None:
        status, response = request.next_chunk(num_retries=5)
        if status:
            print(f"[INFO] Upload progress: {int(status.progress() * 100)}%")

    file_id = response.get("id")
    web_link = response.get("webViewLink")
    print(f"[INFO] Uploaded: {local_path.name}")
    print(f"[INFO] File ID: {file_id}")
    print(f"[INFO] Link: {web_link}")
    return file_id


# ==========================================
# 4. DOWNLOAD ERA5 STANDARD - ANNO DIVISO PER MESE
# ==========================================

print("=========================================")
print(f"ERA5 Standard - Download mensile anno {anno}")
print("=========================================")
print("Variabili: msl, u10, v10, i10fg")
print(f"Area: {area_adriatico}")
print("Mesi: 01-12, un request per mese")
print("Ore: tutte (00-23)")
print(f"Output folder: {cartella_nc}")
print("=========================================")

if UPLOAD_TO_DRIVE:
    print(f"[INFO] Google Drive parent folder ID: {DRIVE_FOLDER_ID}")
    print(f"[INFO] Google Drive subfolder name: {DRIVE_SUBFOLDER_NAME}")

    drive_service = get_drive_service()

    drive_target_folder_id = get_or_create_drive_subfolder(
        drive_service,
        DRIVE_FOLDER_ID,
        DRIVE_SUBFOLDER_NAME,
    )
else:
    drive_service = None
    drive_target_folder_id = None

file_finali = []
errori = []


def processa_mese(mese: str):
    """Download, extract/copy, and return the final monthly NetCDF path."""
    local_client = cdsapi.Client(url=CDS_URL, key=CDS_KEY)

    raw_filename = os.path.join(cartella_raw, f"era5_std_adriatico_{anno}_{mese}.download")
    final_nc_filename = os.path.join(cartella_nc, f"era5_std_adriatico_{anno}_{mese}.nc")
    extract_dir = os.path.join(cartella_raw, f"era5_std_adriatico_{anno}_{mese}_extracted")

    request_std = {
        "product_type": "reanalysis",
        "variable": variabili_std,
        "year": anno,
        "month": mese,
        "day": giorni_del_mese(anno, mese),
        "time": tutte_le_ore,
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": area_adriatico,
    }

    print("\n-----------------------------------------")
    print(f"ERA5 Standard - {anno}-{mese}")
    print(f"Output: {final_nc_filename}")
    print("-----------------------------------------")

    if os.path.exists(final_nc_filename) and os.path.getsize(final_nc_filename) > 0:
        print(f"-> File finale già presente. Salto download: {final_nc_filename}")
        return final_nc_filename

    if not os.path.exists(raw_filename):
        print(f"-> Scarico ERA5 Standard {anno}-{mese}...")
        local_client.retrieve("reanalysis-era5-single-levels", request_std, raw_filename)
        print(f"-> Download completato: {raw_filename}")
        print(f"-> Dimensione raw: {os.path.getsize(raw_filename) / 1e6:.2f} MB")
    else:
        print(f"-> Raw già presente. Salto download: {raw_filename}")

    estrai_o_copia_netcdf(raw_filename, extract_dir, final_nc_filename)
    verifica_dataset(final_nc_filename)

    if UPLOAD_TO_DRIVE and drive_service is not None and drive_target_folder_id is not None:
        with DRIVE_UPLOAD_LOCK:
            upload_file_to_drive(
                drive_service,
                final_nc_filename,
                drive_target_folder_id,
            )

        if DELETE_LOCAL_AFTER_UPLOAD:
            print(f"[INFO] Deleting local final NetCDF after upload: {final_nc_filename}")
            if os.path.exists(final_nc_filename):
                os.remove(final_nc_filename)

            print(f"[INFO] Deleting local raw file after upload: {raw_filename}")
            if os.path.exists(raw_filename):
                os.remove(raw_filename)

            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)

    return final_nc_filename


print(f"\nAvvio download parallelo con MAX_PARALLEL_DOWNLOADS={MAX_PARALLEL_DOWNLOADS}")
print("Nota: CDS può comunque mettere i job in coda; non usare valori troppo alti.")

with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
    future_to_month = {
        executor.submit(processa_mese, mese): mese
        for mese in tutti_i_mesi
    }

    for future in as_completed(future_to_month):
        mese = future_to_month[future]
        try:
            final_nc = future.result()
            file_finali.append(final_nc)
            print(f"[OK] Mese completato: {anno}-{mese}")
        except Exception as e:
            msg = f"{anno}-{mese}: errore download/estrazione: {e}"
            print(f"[ERROR] {msg}")
            errori.append(msg)

file_finali = sorted(file_finali)

# ==========================================
# 5. VERIFICA FILE SCARICATI
# ==========================================

print("\n=========================================")
print("VERIFICA / UPLOAD COMPLETATI")
print("=========================================")

if DELETE_LOCAL_AFTER_UPLOAD:
    print("I file NetCDF sono stati caricati su Google Drive e rimossi dalla cartella temporanea locale.")
else:
    for nc_file in file_finali:
        verifica_dataset(nc_file)

print("\n=========================================")
print("RIEPILOGO")
print("=========================================")
print(f"File NetCDF generati: {len(file_finali)} / 12")

if errori:
    print("Errori:")
    for e in errori:
        print(f"  - {e}")
else:
    print("Nessun errore.")


# Clean temporary working directory when all jobs are finished.
if DELETE_LOCAL_AFTER_UPLOAD:
    try:
        shutil.rmtree(cartella_dati)
        print(f"[INFO] Removed temporary working folder: {cartella_dati}")
    except Exception as e:
        print(f"[WARN] Could not remove temporary working folder {cartella_dati}: {e}")