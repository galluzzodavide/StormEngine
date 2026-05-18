import calendar
import glob
import os
import shutil
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cdsapi
import xarray as xr

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# =========================================================
# 1. CONFIG
# =========================================================

CDS_URL = "https://cds.climate.copernicus.eu/api"

# For local testing only. Safer method: export CDSAPI_KEY or use cds_token.txt.
CDS_KEY_INLINE = "6e902f49-5d17-4d5e-95d1-8beb80d113ae"

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR / ".env"
CDS_TOKEN_PATH = SCRIPT_DIR / "cds_token.txt"

END_YEAR = 2024
YEARS_BACK = 15
START_YEAR = END_YEAR - YEARS_BACK + 1

AREA_ADRIATIC = [46.5, 12.0, 39.0, 20.0]  # [North, West, South, East]

MONTHS = [f"{m:02d}" for m in range(1, 13)]
TIMES = [f"{h:02d}:00" for h in range(24)]

DOWNLOAD_ERA5_LAND = False
DOWNLOAD_ERA5_STANDARD = True

ERA5_LAND_VARIABLES = [
    "2m_temperature",
    "total_precipitation",
]

ERA5_STD_VARIABLES = [
    "mean_sea_level_pressure",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "instantaneous_10m_wind_gust",
    "surface_solar_radiation_downwards",
]

# Parallel CDS monthly requests.
# Standard-only mode can usually run safely with 3 parallel requests.
MAX_PARALLEL_DOWNLOADS = 3

# Google Drive target folder:
# https://drive.google.com/drive/folders/10m3UanSMsKWUEqPCfgRNqTih99-e_941?usp=share_link
DRIVE_PARENT_FOLDER_ID = "10m3UanSMsKWUEqPCfgRNqTih99-e_941"
DRIVE_ROOT_SUBFOLDER_NAME = f"era5_adriatic_{START_YEAR}_{END_YEAR}_monthly"

CREDENTIALS_PATH = SCRIPT_DIR / "credentials.json"
TOKEN_PATH = SCRIPT_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

MAX_CDS_RETRIES = 3

# Files are uploaded to Google Drive and deleted from the temporary local folder.
UPLOAD_TO_DRIVE = True
DELETE_LOCAL_AFTER_UPLOAD = True

DRIVE_UPLOAD_LOCK = threading.Lock()

# Temporary working directory. cdsapi.retrieve() needs a file path, so this is a short-lived cache only.
LOCAL_ROOT = Path(tempfile.mkdtemp(prefix="era5_15years_"))
DOWNLOAD_DIR = LOCAL_ROOT / "downloads"
EXTRACT_DIR = LOCAL_ROOT / "extracted"
OUTPUT_DIR = LOCAL_ROOT / "outputs"

for folder in [DOWNLOAD_DIR, EXTRACT_DIR, OUTPUT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


# =========================================================
# 2. CDS CLIENT
# =========================================================

def read_cds_key_from_env_file(env_path: Path) -> str:
    if not env_path.exists():
        return ""

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("CDSAPI_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")

    return ""


def resolve_cds_key() -> str:
    key = os.environ.get("CDSAPI_KEY", "").strip()
    if key:
        print("[INFO] CDS key found in environment variable CDSAPI_KEY.")
        return key

    key = read_cds_key_from_env_file(ENV_PATH).strip()
    if key:
        print(f"[INFO] CDS key found in local .env file: {ENV_PATH}")
        return key

    if CDS_TOKEN_PATH.exists() and CDS_TOKEN_PATH.stat().st_size > 0:
        key = CDS_TOKEN_PATH.read_text().strip()
        if key:
            print(f"[INFO] CDS key found in local token file: {CDS_TOKEN_PATH}")
            return key

    if CDS_KEY_INLINE.strip():
        print("[INFO] CDS key found in CDS_KEY_INLINE variable.")
        return CDS_KEY_INLINE.strip()

    return ""


def get_cds_key_or_raise() -> str:
    cds_key = resolve_cds_key()
    if cds_key:
        return cds_key

    cdsapirc_path = Path.home() / ".cdsapirc"
    if cdsapirc_path.exists() and cdsapirc_path.stat().st_size > 0:
        print(f"[INFO] CDS credentials will be read from {cdsapirc_path}")
        return ""

    raise RuntimeError(
        "Missing CDS credentials.\n\n"
        f"Create this file:\n{CDS_TOKEN_PATH}\n\n"
        "Put only your Copernicus CDS personal access token inside it.\n"
    )


def create_cds_client(cds_key: str) -> cdsapi.Client:
    if cds_key:
        return cdsapi.Client(url=CDS_URL, key=cds_key)
    return cdsapi.Client()


# =========================================================
# 3. GOOGLE DRIVE
# =========================================================

def get_drive_service():
    creds = None

    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

            token_scopes = set(creds.scopes or [])
            required_scopes = set(SCOPES)
            if not required_scopes.issubset(token_scopes):
                print("[WARN] Existing token.json has wrong Drive scope.")
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
            raise FileNotFoundError(f"credentials.json not found here: {CREDENTIALS_PATH}")

        print("[INFO] Starting Google Drive OAuth flow...")
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def get_or_create_drive_subfolder(service, parent_folder_id: str, subfolder_name: str) -> str:
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

    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder["id"]
    print(f"[INFO] Created Drive subfolder: {subfolder_name} ({folder_id})")
    return folder_id


def upload_file_to_drive(service, local_file: Path, folder_id: str) -> str:
    file_size_mb = local_file.stat().st_size / (1024 * 1024)
    print(f"[INFO] Uploading to Google Drive: {local_file.name} ({file_size_mb:.2f} MB)")

    file_metadata = {
        "name": local_file.name,
        "parents": [folder_id],
    }

    media = MediaFileUpload(
        str(local_file),
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

    print(f"[INFO] Uploaded: {local_file.name}")
    print(f"[INFO] File ID: {file_id}")
    print(f"[INFO] Link: {web_link}")

    return file_id


# =========================================================
# 4. ERA5 REQUESTS
# =========================================================

def month_days(year: int, month: str) -> list[str]:
    days_in_month = calendar.monthrange(year, int(month))[1]
    return [f"{d:02d}" for d in range(1, days_in_month + 1)]


def build_request_land(year: int, month: str) -> dict:
    return {
        "product_type": "reanalysis",
        "variable": ERA5_LAND_VARIABLES,
        "year": str(year),
        "month": month,
        "day": month_days(year, month),
        "time": TIMES,
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA_ADRIATIC,
    }


def build_request_std(year: int, month: str) -> dict:
    return {
        "product_type": "reanalysis",
        "variable": ERA5_STD_VARIABLES,
        "year": str(year),
        "month": month,
        "day": month_days(year, month),
        "time": TIMES,
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA_ADRIATIC,
    }


# =========================================================
# 5. ZIP / NETCDF HANDLING
# =========================================================

def extract_or_return_netcdf(raw_path: Path, extract_dir: Path, final_nc_path: Path) -> Path:
    if final_nc_path.exists() and final_nc_path.stat().st_size > 0:
        print(f"[INFO] Final NetCDF already exists: {final_nc_path}")
        return final_nc_path

    if not zipfile.is_zipfile(raw_path):
        print(f"[INFO] Native NetCDF returned: {raw_path}")
        shutil.copy2(raw_path, final_nc_path)
        return final_nc_path

    print(f"[INFO] Extracting ZIP: {raw_path} -> {extract_dir}")

    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(raw_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    nc_files = sorted(glob.glob(str(extract_dir / "*.nc")))
    nc_files = [f for f in nc_files if Path(f).name != "merged.nc"]

    if not nc_files:
        raise RuntimeError(f"No .nc file found inside {raw_path}")

    if len(nc_files) == 1:
        shutil.copy2(nc_files[0], final_nc_path)
        print(f"[INFO] Single NetCDF extracted: {final_nc_path}")
        return final_nc_path

    print(f"[INFO] Found {len(nc_files)} NetCDF files. Merging into {final_nc_path}")
    datasets = [xr.open_dataset(nc_file) for nc_file in nc_files]

    try:
        merged = xr.merge(datasets, compat="override")
        merged.to_netcdf(final_nc_path)
    finally:
        for ds in datasets:
            ds.close()

    print(f"[INFO] Merge completed: {final_nc_path}")
    return final_nc_path


def verify_netcdf(nc_path: Path) -> None:
    if not nc_path.exists() or nc_path.stat().st_size == 0:
        raise RuntimeError(f"NetCDF file missing or empty: {nc_path}")

    print(f"[INFO] Verifying NetCDF: {nc_path.name}")
    ds = xr.open_dataset(nc_path)

    try:
        time_coord = "valid_time" if "valid_time" in ds.coords else "time"

        if time_coord in ds.coords:
            start_time = str(ds[time_coord].values[0])[:19]
            end_time = str(ds[time_coord].values[-1])[:19]
            n_steps = len(ds[time_coord])
            print(f"[INFO] Time: {start_time} -> {end_time} ({n_steps} steps)")

        print(f"[INFO] Variables: {list(ds.data_vars)}")

        if "latitude" in ds.coords and "longitude" in ds.coords:
            print(f"[INFO] Grid: lat={len(ds.latitude)} x lon={len(ds.longitude)}")
    finally:
        ds.close()


# =========================================================
# 6. DOWNLOAD / UPLOAD LOGIC
# =========================================================

def download_raw_with_retry(
    cds_key: str,
    dataset_name: str,
    request: dict,
    raw_path: Path,
) -> None:
    if raw_path.exists() and raw_path.stat().st_size > 0:
        print(f"[INFO] Raw file already exists: {raw_path}")
        return

    last_error = None

    for attempt in range(1, MAX_CDS_RETRIES + 1):
        try:
            local_client = create_cds_client(cds_key)
            print(f"[INFO] CDS request: {dataset_name} -> {raw_path.name}")
            local_client.retrieve(dataset_name, request, str(raw_path))
            print(f"[INFO] Download completed: {raw_path}")
            return
        except Exception as e:
            last_error = e
            print(f"[WARN] Download failed attempt {attempt}/{MAX_CDS_RETRIES}: {e}")

            if raw_path.exists():
                raw_path.unlink(missing_ok=True)

            time.sleep(10 * attempt)

    raise RuntimeError(f"Failed to download {raw_path.name}") from last_error


def process_one_month(
    cds_key: str,
    drive_service,
    drive_target_folder_id: str,
    dataset_label: str,
    dataset_name: str,
    request: dict,
    year: int,
    month: str,
) -> str:
    raw_path = DOWNLOAD_DIR / f"{dataset_label}_{year}_{month}.download"
    extract_dir = EXTRACT_DIR / f"{dataset_label}_{year}_{month}"
    final_nc_path = OUTPUT_DIR / f"{dataset_label}_{year}_{month}.nc"

    print("-" * 70)
    print(f"[INFO] Processing {dataset_label}: {year}-{month}")

    download_raw_with_retry(cds_key, dataset_name, request, raw_path)
    extract_or_return_netcdf(raw_path, extract_dir, final_nc_path)
    verify_netcdf(final_nc_path)

    if UPLOAD_TO_DRIVE and drive_service is not None and drive_target_folder_id is not None:
        with DRIVE_UPLOAD_LOCK:
            upload_file_to_drive(drive_service, final_nc_path, drive_target_folder_id)

    if DELETE_LOCAL_AFTER_UPLOAD:
        print(f"[INFO] Deleting local temporary files for {dataset_label} {year}-{month}")
        raw_path.unlink(missing_ok=True)
        final_nc_path.unlink(missing_ok=True)

        if extract_dir.exists():
            shutil.rmtree(extract_dir)

    return final_nc_path.name


# =========================================================
# 7. MAIN
# =========================================================

def main():
    print("=" * 70)
    print(f"ERA5 15-year monthly downloader: {START_YEAR}-{END_YEAR}")
    print(f"Area: {AREA_ADRIATIC}")
    print(f"Temporary working folder: {LOCAL_ROOT}")
    print(f"Drive parent folder ID: {DRIVE_PARENT_FOLDER_ID}")
    print(f"Drive root subfolder: {DRIVE_ROOT_SUBFOLDER_NAME}")
    print(f"Max parallel downloads: {MAX_PARALLEL_DOWNLOADS}")
    print("=" * 70)

    cds_key = get_cds_key_or_raise()

    if UPLOAD_TO_DRIVE:
        drive_service = get_drive_service()
        drive_root_folder_id = get_or_create_drive_subfolder(
            drive_service,
            DRIVE_PARENT_FOLDER_ID,
            DRIVE_ROOT_SUBFOLDER_NAME,
        )

        folder_ids = {
            "era5_land_adriatic": get_or_create_drive_subfolder(
                drive_service,
                drive_root_folder_id,
                "era5_land_monthly",
            ),
            "era5_std_adriatic": get_or_create_drive_subfolder(
                drive_service,
                drive_root_folder_id,
                "era5_standard_monthly",
            ),
        }
    else:
        drive_service = None
        folder_ids = {
            "era5_land_adriatic": None,
            "era5_std_adriatic": None,
        }

    jobs = []
    for year in range(START_YEAR, END_YEAR + 1):
        for month in MONTHS:
            if DOWNLOAD_ERA5_LAND:
                jobs.append(
                    (
                        "era5_land_adriatic",
                        "reanalysis-era5-land",
                        build_request_land(year, month),
                        year,
                        month,
                    )
                )

            if DOWNLOAD_ERA5_STANDARD:
                jobs.append(
                    (
                        "era5_std_adriatic",
                        "reanalysis-era5-single-levels",
                        build_request_std(year, month),
                        year,
                        month,
                    )
                )

    successful_jobs = 0
    failed_jobs = []

    print(f"[INFO] Total monthly jobs: {len(jobs)}")
    print("[INFO] Starting parallel monthly download/upload pipeline...")

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
        future_to_job = {}

        for dataset_label, dataset_name, request, year, month in jobs:
            future = executor.submit(
                process_one_month,
                cds_key,
                drive_service,
                folder_ids[dataset_label],
                dataset_label,
                dataset_name,
                request,
                year,
                month,
            )
            future_to_job[future] = (dataset_label, year, month)

        for future in as_completed(future_to_job):
            dataset_label, year, month = future_to_job[future]
            try:
                uploaded_name = future.result()
                successful_jobs += 1
                print(f"[OK] Completed: {uploaded_name}")
            except Exception as e:
                error_message = f"{dataset_label} {year}-{month}: {e}"
                print(f"[ERROR] {error_message}")
                failed_jobs.append(error_message)

    print("=" * 70)
    print("[DONE] ERA5 15-year monthly pipeline finished.")
    print(f"[INFO] Successful jobs: {successful_jobs}")
    print(f"[INFO] Failed jobs: {len(failed_jobs)}")

    if failed_jobs:
        print("[WARN] Failed items:")
        for item in failed_jobs:
            print(f"  - {item}")
    else:
        print("[INFO] No errors.")

    if DELETE_LOCAL_AFTER_UPLOAD:
        try:
            shutil.rmtree(LOCAL_ROOT)
            print(f"[INFO] Removed temporary working folder: {LOCAL_ROOT}")
        except Exception as e:
            print(f"[WARN] Could not remove temporary working folder {LOCAL_ROOT}: {e}")

    print("=" * 70)


if __name__ == "__main__":
    main()