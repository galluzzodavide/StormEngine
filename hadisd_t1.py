import os
import re
import gzip
import shutil
from pathlib import Path
from urllib.parse import urljoin

import requests
import pandas as pd
import xarray as xr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# =========================================================
# CONFIG
# =========================================================

VERSION = "v343_2025f"

# Example station from HadISD page
# You can replace this with another station ID.
STATION_ID = "010010-99999"

YEAR = 2024

LOCAL_DIR = Path("data/hadisd")
LOCAL_DIR.mkdir(parents=True, exist_ok=True)

DRIVE_FOLDER_NAME = "hadisd_2024"

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


# =========================================================
# HADISD URL DISCOVERY
# =========================================================

def find_hadisd_file_url(station_id: str, version: str = VERSION) -> str:
    """
    Find the actual .nc.gz download URL from HadISD station download page.
    HadISD pages are split by first digit of station ID:
    station_download_0.html, station_download_1.html, etc.
    """

    first_digit = station_id[0]

    page_url = (
        f"https://www.metoffice.gov.uk/hadobs/hadisd/"
        f"{version}/station_download_{first_digit}.html"
    )

    print(f"[INFO] Searching station page: {page_url}")

    response = requests.get(page_url, timeout=60)
    response.raise_for_status()

    html = response.text

    # Find href containing the station ID and .nc.gz
    pattern = rf'href="([^"]*{re.escape(station_id)}\.nc\.gz)"'
    match = re.search(pattern, html)

    if not match:
        raise RuntimeError(
            f"Could not find station {station_id} on page {page_url}. "
            "Please check whether the station ID exists in HadISD."
        )

    relative_url = match.group(1)
    file_url = urljoin(page_url, relative_url)

    print(f"[INFO] Found HadISD file URL: {file_url}")

    return file_url


# =========================================================
# DOWNLOAD AND EXTRACT
# =========================================================

def download_file(url: str, output_path: Path) -> None:
    if output_path.exists():
        print(f"[INFO] Already downloaded: {output_path}")
        return

    print(f"[INFO] Downloading: {url}")

    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    print(f"[INFO] Download completed: {output_path}")


def extract_gz(gz_path: Path, nc_path: Path) -> None:
    if nc_path.exists():
        print(f"[INFO] Already extracted: {nc_path}")
        return

    print(f"[INFO] Extracting: {gz_path}")

    with gzip.open(gz_path, "rb") as f_in:
        with open(nc_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    print(f"[INFO] Extraction completed: {nc_path}")


# =========================================================
# READ HADISD NETCDF AND FILTER 2024
# =========================================================

def read_hadisd_year_to_dataframe(nc_path: Path, year: int) -> pd.DataFrame:
    print(f"[INFO] Opening NetCDF: {nc_path}")

    ds = xr.open_dataset(nc_path)

    if "time" not in ds.coords and "time" not in ds.dims:
        raise RuntimeError("No time coordinate found in this HadISD file.")

    start = f"{year}-01-01"
    end = f"{year}-12-31T23:59:59"

    print(f"[INFO] Filtering year: {year}")

    ds_year = ds.sel(time=slice(start, end))

    if ds_year.sizes.get("time", 0) == 0:
        raise RuntimeError(f"No data found for year {year} in {nc_path.name}")

    # Keep only simple one-dimensional variables indexed exactly by time.
    # HadISD contains multi-dimensional QC/flag variables, for example
    # quality_control_flags and flagged_obs. Converting those directly with
    # to_dataframe() creates a Cartesian expansion and turns one year of hourly
    # station data into millions of rows.
    time_vars = [
        var_name
        for var_name, da in ds_year.data_vars.items()
        if da.dims == ("time",)
    ]

    if not time_vars:
        raise RuntimeError("No one-dimensional time variables found in this HadISD file.")

    print(f"[INFO] Keeping 1D time variables only: {time_vars}")

    ds_time = ds_year[time_vars]

    df = ds_time.to_dataframe().reset_index()

    # Add useful metadata if available.
    for meta_var in ["latitude", "longitude", "elevation"]:
        if meta_var in ds.variables:
            try:
                df[meta_var] = float(ds[meta_var].values)
            except Exception:
                pass

    df["station_id"] = STATION_ID
    df["source"] = "HadISD"
    df["hadisd_version"] = VERSION
    df["year"] = year

    print(f"[INFO] Rows extracted: {len(df)}")
    print(f"[INFO] Columns: {list(df.columns)}")

    return df


# =========================================================
# GOOGLE DRIVE AUTH AND UPLOAD
# =========================================================

def get_drive_service():
    creds = None

    token_path = Path("token.json")
    credentials_path = Path("credentials.json")

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[INFO] Refreshing Google Drive token...")
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    "credentials.json not found. "
                    "Download OAuth client credentials from Google Cloud Console "
                    "and place it beside this script."
                )

            print("[INFO] Starting Google Drive OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as token:
            token.write(creds.to_json())

    service = build("drive", "v3", credentials=creds)
    return service


def get_or_create_drive_folder(service, folder_name: str) -> str:
    query = (
        f"name='{folder_name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )

    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    folders = result.get("files", [])

    if folders:
        folder_id = folders[0]["id"]
        print(f"[INFO] Drive folder exists: {folder_name} ({folder_id})")
        return folder_id

    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }

    folder = service.files().create(
        body=file_metadata,
        fields="id"
    ).execute()

    folder_id = folder.get("id")

    print(f"[INFO] Created Drive folder: {folder_name} ({folder_id})")

    return folder_id


def upload_file_to_drive(service, local_file: Path, folder_id: str) -> str:
    file_metadata = {
        "name": local_file.name,
        "parents": [folder_id]
    }

    file_size_mb = local_file.stat().st_size / (1024 * 1024)
    print(f"[INFO] Uploading file size: {file_size_mb:.2f} MB")

    media = MediaFileUpload(
        str(local_file),
        mimetype="text/csv",
        chunksize=5 * 1024 * 1024,
        resumable=True
    )

    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    )

    response = None
    while response is None:
        status, response = request.next_chunk(num_retries=5)
        if status:
            print(f"[INFO] Upload progress: {int(status.progress() * 100)}%")

    uploaded_file = response

    file_id = uploaded_file.get("id")
    web_link = uploaded_file.get("webViewLink")

    print(f"[INFO] Uploaded to Google Drive: {local_file.name}")
    print(f"[INFO] File ID: {file_id}")
    print(f"[INFO] Link: {web_link}")

    return file_id


# =========================================================
# MAIN PIPELINE
# =========================================================

def main():
    print("=" * 70)
    print("HadISD 2024 Downloader + Google Drive Uploader")
    print("=" * 70)

    file_url = find_hadisd_file_url(STATION_ID, VERSION)

    gz_path = LOCAL_DIR / f"{STATION_ID}.nc.gz"
    nc_path = LOCAL_DIR / f"{STATION_ID}.nc"
    csv_path = LOCAL_DIR / f"hadisd_{STATION_ID}_{YEAR}.csv"

    download_file(file_url, gz_path)
    extract_gz(gz_path, nc_path)

    df = read_hadisd_year_to_dataframe(nc_path, YEAR)

    if csv_path.exists():
        print(f"[INFO] Removing old CSV before saving: {csv_path}")
        csv_path.unlink()

    print(f"[INFO] Saving CSV: {csv_path}")
    df.to_csv(csv_path, index=False)

    csv_size_mb = csv_path.stat().st_size / (1024 * 1024)
    print(f"[INFO] CSV saved: {csv_path}")
    print(f"[INFO] CSV size: {csv_size_mb:.2f} MB")

    print("[INFO] Connecting to Google Drive...")
    drive_service = get_drive_service()

    folder_id = get_or_create_drive_folder(
        drive_service,
        DRIVE_FOLDER_NAME
    )

    upload_file_to_drive(
        drive_service,
        csv_path,
        folder_id
    )

    print("=" * 70)
    print("[DONE] HadISD 2024 data processed and uploaded.")
    print("=" * 70)


if __name__ == "__main__":
    main()