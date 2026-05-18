import calendar
import glob
import os
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cdsapi
import xarray as xr


# =========================================================
# 1. CONFIG
# =========================================================

CDS_URL = "https://cds.climate.copernicus.eu/api"

# 推荐方式：
# 1) 在终端 export CDSAPI_KEY="你的token"
# 或者
# 2) 在项目目录创建 cds_token.txt，里面只放 token
# 不建议长期把 token 写死在代码里
CDS_KEY_INLINE = ""

SCRIPT_DIR = Path(__file__).resolve().parent
CDS_TOKEN_PATH = SCRIPT_DIR / "cds_token.txt"

START_YEAR = 2010
END_YEAR = 2024

AREA_ADRIATIC = [46.5, 12.0, 39.0, 20.0]  # [North, West, South, East]

MONTHS = [f"{m:02d}" for m in range(1, 13)]
TIMES = [f"{h:02d}:00" for h in range(24)]

ERA5_STD_VARIABLES = [
    "mean_sea_level_pressure",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "instantaneous_10m_wind_gust",
    "surface_solar_radiation_downwards",
]

# 速度核心参数：
# 3 比较稳，4 更快但可能偶尔 retry。
# 如果你电脑/网络稳定，可以用 4。
MAX_PARALLEL_DOWNLOADS = 4

MAX_CDS_RETRIES = 3

LOCAL_ROOT = SCRIPT_DIR / "data" / "era5_standard_2010_2024"
RAW_DIR = LOCAL_ROOT / "raw"
EXTRACT_DIR = LOCAL_ROOT / "extracted"
OUTPUT_DIR = LOCAL_ROOT / "netcdf"

for folder in [RAW_DIR, EXTRACT_DIR, OUTPUT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


# =========================================================
# 2. CDS TOKEN
# =========================================================

def resolve_cds_key() -> str:
    key = os.environ.get("CDSAPI_KEY", "").strip()
    if key:
        print("[INFO] CDS key found in environment variable CDSAPI_KEY.")
        return key

    if CDS_TOKEN_PATH.exists() and CDS_TOKEN_PATH.stat().st_size > 0:
        key = CDS_TOKEN_PATH.read_text().strip()
        if key:
            print(f"[INFO] CDS key found in local token file: {CDS_TOKEN_PATH}")
            return key

    if CDS_KEY_INLINE.strip():
        print("[INFO] CDS key found in CDS_KEY_INLINE.")
        return CDS_KEY_INLINE.strip()

    return ""


def create_cds_client(cds_key: str) -> cdsapi.Client:
    if cds_key:
        return cdsapi.Client(url=CDS_URL, key=cds_key)
    return cdsapi.Client()


# =========================================================
# 3. REQUEST
# =========================================================

def month_days(year: int, month: str) -> list[str]:
    n_days = calendar.monthrange(year, int(month))[1]
    return [f"{d:02d}" for d in range(1, n_days + 1)]


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
# 4. NETCDF HANDLING
# =========================================================

def extract_or_copy_netcdf(raw_path: Path, extract_dir: Path, final_nc_path: Path) -> Path:
    if final_nc_path.exists() and final_nc_path.stat().st_size > 0:
        print(f"[SKIP] Final NetCDF already exists: {final_nc_path.name}")
        return final_nc_path

    if not zipfile.is_zipfile(raw_path):
        shutil.copy2(raw_path, final_nc_path)
        return final_nc_path

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
        return final_nc_path

    datasets = [xr.open_dataset(nc_file) for nc_file in nc_files]
    try:
        merged = xr.merge(datasets, compat="override")
        merged.to_netcdf(final_nc_path)
    finally:
        for ds in datasets:
            ds.close()

    return final_nc_path


def quick_verify(nc_path: Path) -> None:
    ds = xr.open_dataset(nc_path)
    try:
        time_coord = "valid_time" if "valid_time" in ds.coords else "time"
        if time_coord in ds.coords:
            print(
                f"[OK] {nc_path.name} | "
                f"{str(ds[time_coord].values[0])[:10]} -> {str(ds[time_coord].values[-1])[:10]} | "
                f"vars={list(ds.data_vars)}"
            )
        else:
            print(f"[OK] {nc_path.name} | vars={list(ds.data_vars)}")
    finally:
        ds.close()


# =========================================================
# 5. DOWNLOAD ONE MONTH
# =========================================================

def download_one_month(cds_key: str, year: int, month: str) -> str:
    label = f"era5_std_adriatic_{year}_{month}"

    raw_path = RAW_DIR / f"{label}.download"
    extract_dir = EXTRACT_DIR / label
    final_nc_path = OUTPUT_DIR / f"{label}.nc"

    if final_nc_path.exists() and final_nc_path.stat().st_size > 0:
        return f"[SKIP] {final_nc_path.name}"

    request = build_request_std(year, month)

    last_error = None

    for attempt in range(1, MAX_CDS_RETRIES + 1):
        try:
            client = create_cds_client(cds_key)

            if not raw_path.exists() or raw_path.stat().st_size == 0:
                print(f"[DOWNLOAD] {label}")
                client.retrieve(
                    "reanalysis-era5-single-levels",
                    request,
                    str(raw_path),
                )
            else:
                print(f"[RAW EXISTS] {raw_path.name}")

            extract_or_copy_netcdf(raw_path, extract_dir, final_nc_path)
            quick_verify(final_nc_path)

            return f"[DONE] {final_nc_path.name}"

        except Exception as e:
            last_error = e
            print(f"[WARN] {label} failed attempt {attempt}/{MAX_CDS_RETRIES}: {e}")

            if raw_path.exists() and raw_path.stat().st_size == 0:
                raw_path.unlink(missing_ok=True)

            time.sleep(10 * attempt)

    raise RuntimeError(f"{label} failed after {MAX_CDS_RETRIES} retries") from last_error


# =========================================================
# 6. MAIN
# =========================================================

def main():
    print("=" * 70)
    print("FAST LOCAL ERA5 STANDARD DOWNLOADER")
    print(f"Years: {START_YEAR}-{END_YEAR}")
    print(f"Area: {AREA_ADRIATIC}")
    print(f"Variables: {ERA5_STD_VARIABLES}")
    print(f"Output folder: {OUTPUT_DIR}")
    print(f"Max parallel downloads: {MAX_PARALLEL_DOWNLOADS}")
    print("=" * 70)

    cds_key = resolve_cds_key()

    if not cds_key:
        cdsapirc_path = Path.home() / ".cdsapirc"
        if cdsapirc_path.exists():
            print(f"[INFO] No explicit token found. Using {cdsapirc_path}")
        else:
            raise RuntimeError(
                "Missing CDS credentials.\n\n"
                f"Create this file:\n{CDS_TOKEN_PATH}\n\n"
                "Put only your Copernicus CDS token inside it.\n"
            )

    jobs = [
        (year, month)
        for year in range(START_YEAR, END_YEAR + 1)
        for month in MONTHS
    ]

    print(f"[INFO] Total jobs: {len(jobs)}")

    successful = 0
    failed = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
        future_to_job = {
            executor.submit(download_one_month, cds_key, year, month): (year, month)
            for year, month in jobs
        }

        for future in as_completed(future_to_job):
            year, month = future_to_job[future]
            try:
                msg = future.result()
                successful += 1
                print(msg)
            except Exception as e:
                err = f"{year}-{month}: {e}"
                failed.append(err)
                print(f"[ERROR] {err}")

    print("=" * 70)
    print("[FINISHED]")
    print(f"Successful: {successful}")
    print(f"Failed: {len(failed)}")
    print(f"Output folder: {OUTPUT_DIR}")

    if failed:
        print("\nFailed jobs:")
        for item in failed:
            print(f"  - {item}")

    print("=" * 70)


if __name__ == "__main__":
    main()