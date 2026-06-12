"""
StormEngine — HadISD × ERA5 Improved Data Quality and Interpolation Pipeline

Put this file in the same folder as:
    final_2024_11_msl.csv
    final_2024_12_msl.csv
    final_2024_1_msl.csv
    final_2024_2_msl.csv
    hadisd_adriatic_2024.csv

Then run:
    python hadisd_era5_quality_improved.py

Outputs:
    reports/figures/hadisd_era5/*.png
    reports/tables/*.csv
    reports/hadisd_era5_report_notes.md
"""

from __future__ import annotations

import calendar
import glob
import os
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# =============================================================================
# 0. CONFIGURATION
# =============================================================================

plt.rcParams.update({
    "figure.dpi": 110,
    "savefig.dpi": 250,
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "legend.frameon": False,
})

# --- Input files -------------------------------------------------------------
ERA5_FILES = {
    "November": {"path": "final_2024_11_msl.csv", "year": 2024, "month": 11},
    "December": {"path": "final_2024_12_msl.csv", "year": 2024, "month": 12},
    "January": {"path": "final_2024_1_msl.csv", "year": 2025, "month": 1},
    "February": {"path": "final_2024_2_msl.csv", "year": 2025, "month": 2},
}

HADISD_PATH = "hadisd_adriatic_2024.csv"   # file or folder containing HadISD CSVs
HADISD_VAR = "PRESS"                       # pressure variable in HadISD

# --- Domain -----------------------------------------------------------------
LAT_MIN, LAT_MAX = 39.0, 46.5
LON_MIN, LON_MAX = 12.0, 20.0
PA_TO_HPA = 1.0 / 100.0                    # ERA5 MSL is usually Pa; convert to hPa

# --- Quality thresholds ------------------------------------------------------
ALIGN_TOL_MIN = 30                         # max allowed temporal mismatch in minutes
PHYS_MIN = 950.0                           # plausible MSL pressure lower bound, hPa
PHYS_MAX = 1060.0                          # plausible MSL pressure upper bound, hPa
MISSING_MAX_PCT = 30.0                     # station missing-rate threshold
JUMP_THRESHOLD_HPA = 10.0                  # suspicious hourly pressure jump threshold
COVERAGE_THRESHOLD_KM = 150.0              # ERA5 grid considered covered if station <= threshold
MIN_OBS_FOR_STATION_METRICS = 10

SEASON_MAP = {11: "Autumn", 12: "Winter", 1: "Winter", 2: "Winter"}
MONTH_ORDER = ["November", "December", "January", "February"]
MONTH_COLORS = {
    "November": "#fb8d3d",
    "December": "#08519c",
    "January": "#2c7fb8",
    "February": "#41b6c4",
}

# --- Output folders ----------------------------------------------------------
REPORT_DIR = Path("reports")
FIG_DIR = REPORT_DIR / "figures" / "hadisd_era5"
TABLE_DIR = REPORT_DIR / "tables"
FIG_DIR.mkdir(parents=True, exist_ok=True)
TABLE_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 1. UTILITY FUNCTIONS
# =============================================================================

def check_input_files() -> None:
    """Print availability of expected input files."""
    print("Working directory:", os.getcwd())
    print("\nChecking input files:")

    all_ok = True
    for name, meta in ERA5_FILES.items():
        path = meta["path"]
        ok = os.path.isfile(path)
        print(f"  {'OK' if ok else 'MISSING':8s} {path}")
        all_ok = all_ok and ok

    hadisd_ok = os.path.isfile(HADISD_PATH) or os.path.isdir(HADISD_PATH)
    print(f"  {'OK' if hadisd_ok else 'MISSING':8s} {HADISD_PATH}")
    all_ok = all_ok and hadisd_ok

    if not all_ok:
        raise FileNotFoundError(
            "Some input files are missing. Put this script in the folder containing the CSV files, "
            "or update ERA5_FILES and HADISD_PATH at the top of the script."
        )

    print("\nAll required files found.\n")


def save_table(df: pd.DataFrame, filename: str) -> None:
    path = TABLE_DIR / filename
    df.to_csv(path, index=False)
    print(f"Saved table -> {path}")


def save_figure(filename: str) -> None:
    path = FIG_DIR / filename
    plt.savefig(path, bbox_inches="tight")
    print(f"Saved figure -> {path}")


def get_hadisd_files(path_or_folder: str) -> List[str]:
    if os.path.isfile(path_or_folder):
        return [path_or_folder]
    return sorted(glob.glob(os.path.join(path_or_folder, "*.csv")))


# =============================================================================
# 2. LOAD DATA
# =============================================================================

def load_era5_month(path: str, year: int, month: int) -> Dict[str, object]:
    """
    Load one monthly ERA5 CSV.

    Expected ERA5 format:
        lon, lat, SAMPLE_0, SAMPLE_1, ..., SAMPLE_N
    where SAMPLE_i are hourly MSL values in Pa.
    """
    df = pd.read_csv(path)

    if "lon" not in df.columns or "lat" not in df.columns:
        raise ValueError(f"ERA5 file {path} must contain 'lon' and 'lat' columns.")

    sample_cols = [c for c in df.columns if c.startswith("SAMPLE_")]
    if not sample_cols:
        raise ValueError(f"ERA5 file {path} has no SAMPLE_* columns.")

    base = pd.Timestamp(year=year, month=month, day=1, hour=0, tz="UTC")
    timestamps = [base + pd.Timedelta(hours=i) for i in range(len(sample_cols))]

    samples = df[sample_cols].values.astype(float) * PA_TO_HPA

    # Remove all-NaN time columns.
    valid_time = ~np.all(np.isnan(samples), axis=0)
    samples = samples[:, valid_time]
    timestamps = [t for t, valid in zip(timestamps, valid_time) if valid]

    return {
        "timestamps": timestamps,
        "samples": samples,
        "lon": df["lon"].values.astype(float),
        "lat": df["lat"].values.astype(float),
        "lons_uniq": np.sort(df["lon"].dropna().unique().astype(float)),
        "lats_uniq": np.sort(df["lat"].dropna().unique().astype(float)),
    }


def load_era5_all() -> Dict[str, Dict[str, object]]:
    era5 = {}
    print("Loading ERA5 monthly files...")
    for month_name, meta in ERA5_FILES.items():
        d = load_era5_month(meta["path"], meta["year"], meta["month"])
        era5[month_name] = d
        print(
            f"  {month_name:9s} | {d['timestamps'][0]} -> {d['timestamps'][-1]} "
            f"| {len(d['timestamps'])} hours | {d['samples'].shape[0]} grid points"
        )
    print()
    return era5


def load_hadisd(path_or_folder: str, var_code: str = "PRESS") -> pd.DataFrame:
    """
    Load HadISD CSV observations.

    Expected columns:
        station_id, dt, value, lat, lon
    Optional:
        sensor_code
    """
    files = get_hadisd_files(path_or_folder)
    if not files:
        raise FileNotFoundError(f"No HadISD CSV files found at: {path_or_folder}")

    frames = []
    for file in files:
        try:
            frames.append(pd.read_csv(file))
        except Exception as exc:
            print(f"Warning: could not read {file}: {exc}")

    if not frames:
        raise RuntimeError("HadISD files were found but none could be read.")

    df = pd.concat(frames, ignore_index=True)

    required = ["station_id", "dt", "value", "lat", "lon"]
    missing_required = [c for c in required if c not in df.columns]
    if missing_required:
        raise ValueError(f"HadISD file is missing required columns: {missing_required}")

    if "sensor_code" in df.columns:
        df = df[df["sensor_code"] == var_code].copy()

    df["dt"] = pd.to_datetime(df["dt"], utc=True, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")

    df = df[["station_id", "dt", "value", "lat", "lon"]].dropna()
    df = df[df["lat"].between(LAT_MIN, LAT_MAX) & df["lon"].between(LON_MIN, LON_MAX)].copy()

    df["month_num"] = df["dt"].dt.month
    df["month_name"] = df["month_num"].map({11: "November", 12: "December", 1: "January", 2: "February"})
    df["season"] = df["month_num"].map(SEASON_MAP)

    # Keep only the four months used in this pipeline.
    df = df[df["month_name"].notna()].copy()

    return df.sort_values("dt").reset_index(drop=True)


def print_data_overview(hadisd: pd.DataFrame, era5: Dict[str, Dict[str, object]]) -> None:
    print("=" * 70)
    print("DATA OVERVIEW")
    print("=" * 70)
    print(f"HadISD observations: {len(hadisd)}")
    print(f"HadISD stations    : {hadisd['station_id'].nunique()}")
    print(f"HadISD time range  : {hadisd['dt'].min()} -> {hadisd['dt'].max()}")
    print(f"HadISD value range : {hadisd['value'].min():.2f} -> {hadisd['value'].max():.2f} hPa")
    print("\nHadISD observations by month:")
    print(hadisd.groupby("month_name").size().reindex(MONTH_ORDER).dropna().astype(int).to_string())

    print("\nERA5 monthly coverage:")
    for month_name, d in era5.items():
        print(
            f"  {month_name:9s}: {len(d['timestamps'])} hours, "
            f"{len(d['lats_uniq'])} lat x {len(d['lons_uniq'])} lon grid"
        )
    print("=" * 70)
    print()


# =============================================================================
# 3. ERA5-HadISD CO-LOCATION WITH BILINEAR INTERPOLATION
# =============================================================================

def reshape_grid(vals: np.ndarray, lon: np.ndarray, lat: np.ndarray, lats_u: np.ndarray, lons_u: np.ndarray) -> np.ndarray:
    """Convert a flat ERA5 vector into a 2-D [lat, lon] grid."""
    grid = np.full((len(lats_u), len(lons_u)), np.nan)
    lon_index = {v: i for i, v in enumerate(lons_u)}
    lat_index = {v: i for i, v in enumerate(lats_u)}
    for value, lo, la in zip(vals, lon, lat):
        if not (np.isnan(lo) or np.isnan(la)):
            grid[lat_index[la], lon_index[lo]] = value
    return grid


def bilinear_interp(grid: np.ndarray, lats: np.ndarray, lons: np.ndarray, qlat: float, qlon: float) -> float:
    """Bilinearly interpolate a 2-D ERA5 grid at a query latitude/longitude."""
    qlat = np.clip(qlat, lats[0], lats[-1])
    qlon = np.clip(qlon, lons[0], lons[-1])

    i1 = np.clip(np.searchsorted(lats, qlat) - 1, 0, len(lats) - 2)
    j1 = np.clip(np.searchsorted(lons, qlon) - 1, 0, len(lons) - 2)
    i2, j2 = i1 + 1, j1 + 1

    lat_frac = (qlat - lats[i1]) / (lats[i2] - lats[i1] + 1e-12)
    lon_frac = (qlon - lons[j1]) / (lons[j2] - lons[j1] + 1e-12)

    v11 = grid[i1, j1]
    v21 = grid[i2, j1]
    v12 = grid[i1, j2]
    v22 = grid[i2, j2]

    return float(
        v11 * (1 - lat_frac) * (1 - lon_frac)
        + v21 * lat_frac * (1 - lon_frac)
        + v12 * (1 - lat_frac) * lon_frac
        + v22 * lat_frac * lon_frac
    )


def build_colocation(hadisd: pd.DataFrame, era5: Dict[str, Dict[str, object]], tol_min: int) -> pd.DataFrame:
    """Match HadISD point observations to ERA5 grid values in time and space."""
    tolerance = pd.Timedelta(minutes=tol_min)
    rows = []
    n_unmatched = 0

    print("Building ERA5-HadISD co-location table...")
    for month_name, d in era5.items():
        era5_times = pd.DatetimeIndex(d["timestamps"])
        sub = hadisd[hadisd["month_name"] == month_name].copy()
        if len(sub) == 0:
            print(f"  {month_name:9s}: no HadISD observations")
            continue

        print(f"  {month_name:9s}: {len(sub)} HadISD observations -> matching")

        # Cache 2-D grids by timestamp.
        grids = {
            ts: reshape_grid(
                d["samples"][:, h],
                d["lon"],
                d["lat"],
                d["lats_uniq"],
                d["lons_uniq"],
            )
            for h, ts in enumerate(d["timestamps"])
        }

        for _, row in sub.iterrows():
            deltas = np.abs(era5_times - row["dt"])
            closest_index = int(deltas.argmin())
            closest_delta = deltas[closest_index]

            if closest_delta > tolerance:
                n_unmatched += 1
                continue

            era5_timestamp = d["timestamps"][closest_index]
            era5_grid = grids[era5_timestamp]
            era5_val = bilinear_interp(
                era5_grid,
                d["lats_uniq"],
                d["lons_uniq"],
                row["lat"],
                row["lon"],
            )

            rows.append({
                "station_id": row["station_id"],
                "dt": row["dt"],
                "era5_dt": era5_timestamp,
                "dt_diff_min": closest_delta.total_seconds() / 60.0,
                "lat": row["lat"],
                "lon": row["lon"],
                "month_name": month_name,
                "season": row["season"],
                "hadisd_msl": row["value"],
                "era5_msl": era5_val,
                "bias": row["value"] - era5_val,  # HadISD - ERA5
            })

    coloc = pd.DataFrame(rows)
    if coloc.empty:
        raise RuntimeError("No ERA5-HadISD matches were created. Check timestamps and input files.")

    print(f"Matched pairs: {len(coloc)}")
    print(f"Unmatched observations due to tolerance: {n_unmatched}\n")
    return coloc


# =============================================================================
# 4. PLOTS AND QUALITY DIAGNOSTICS
# =============================================================================

def plot_alignment_scatter(coloc: pd.DataFrame) -> None:
    months = [m for m in MONTH_ORDER if m in coloc["month_name"].unique()]
    n = len(months)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), sharex=True, sharey=True)
    if n == 1:
        axes = [axes]

    for ax, month in zip(axes, months):
        sub = coloc[coloc["month_name"] == month]
        ax.scatter(sub["era5_msl"], sub["hadisd_msl"], alpha=0.25, s=8)

        lim_min = min(sub["era5_msl"].min(), sub["hadisd_msl"].min()) - 1
        lim_max = max(sub["era5_msl"].max(), sub["hadisd_msl"].max()) + 1
        ax.plot([lim_min, lim_max], [lim_min, lim_max], "k--", linewidth=1.2, label="1:1")

        diff = sub["bias"]
        bias = diff.mean()
        rmse = np.sqrt((diff ** 2).mean())
        corr = sub[["era5_msl", "hadisd_msl"]].corr().iloc[0, 1]
        ax.set_title(f"{month}\nBias={bias:+.2f}, RMSE={rmse:.2f}, r={corr:.3f}")
        ax.set_xlabel("ERA5 MSL (hPa)")
        ax.legend(fontsize=9)

    axes[0].set_ylabel("HadISD MSL (hPa)")
    fig.suptitle("ERA5 vs HadISD MSL pressure by month")
    plt.tight_layout()
    save_figure("01_alignment_scatter_by_month.png")
    plt.close()


def plot_temporal_matching_quality(coloc: pd.DataFrame) -> pd.DataFrame:
    summary = coloc["dt_diff_min"].describe().reset_index()
    summary.columns = ["statistic", "dt_diff_min"]
    save_table(summary, "temporal_matching_quality.csv")

    plt.figure(figsize=(8, 4))
    plt.hist(coloc["dt_diff_min"], bins=30, edgecolor="white")
    plt.xlabel("Absolute time difference between HadISD and ERA5 (minutes)")
    plt.ylabel("Number of matched observations")
    plt.title("Temporal matching quality")
    plt.grid(True)
    save_figure("02_temporal_matching_quality.png")
    plt.close()

    return summary


def plot_interpolation_diagnostic(coloc: pd.DataFrame, era5: Dict[str, Dict[str, object]]) -> pd.DataFrame:
    """Show one HadISD station and the four surrounding ERA5 grid points used for interpolation."""
    example = coloc.iloc[0]
    month_name = example["month_name"]
    example_time = example["era5_dt"]
    example_lat = float(example["lat"])
    example_lon = float(example["lon"])

    d = era5[month_name]
    time_index = d["timestamps"].index(example_time)
    grid = reshape_grid(
        d["samples"][:, time_index],
        d["lon"],
        d["lat"],
        d["lats_uniq"],
        d["lons_uniq"],
    )

    lats = d["lats_uniq"]
    lons = d["lons_uniq"]

    i1 = np.clip(np.searchsorted(lats, example_lat) - 1, 0, len(lats) - 2)
    j1 = np.clip(np.searchsorted(lons, example_lon) - 1, 0, len(lons) - 2)
    i2, j2 = i1 + 1, j1 + 1

    surrounding = pd.DataFrame({
        "lat": [lats[i1], lats[i2], lats[i1], lats[i2]],
        "lon": [lons[j1], lons[j1], lons[j2], lons[j2]],
        "era5_msl_hpa": [grid[i1, j1], grid[i2, j1], grid[i1, j2], grid[i2, j2]],
    })
    save_table(surrounding, "interpolation_example_surrounding_points.csv")

    plt.figure(figsize=(7, 6))
    plt.scatter(d["lon"], d["lat"], s=8, alpha=0.35, label="ERA5 grid points")
    plt.scatter(
        surrounding["lon"],
        surrounding["lat"],
        s=120,
        edgecolor="black",
        label="4 surrounding ERA5 points",
    )
    plt.scatter(
        example_lon,
        example_lat,
        s=180,
        marker="*",
        edgecolor="black",
        label="HadISD station",
    )
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Bilinear interpolation diagnostic")
    plt.legend()
    plt.grid(True)
    save_figure("03_interpolation_diagnostic.png")
    plt.close()

    return surrounding


def compute_bias_statistics(coloc: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    monthly = coloc.groupby("month_name")["bias"].agg(
        mean="mean",
        std="std",
        median="median",
        q25=lambda x: x.quantile(0.25),
        q75=lambda x: x.quantile(0.75),
        n="count",
    ).reindex([m for m in MONTH_ORDER if m in coloc["month_name"].unique()]).round(3).reset_index()

    seasonal = coloc.groupby("season")["bias"].agg(
        mean="mean",
        std="std",
        median="median",
        n="count",
    ).round(3).reset_index()

    save_table(monthly, "monthly_bias_statistics.csv")
    save_table(seasonal, "seasonal_bias_statistics.csv")
    return monthly, seasonal


def plot_bias_boxplots(coloc: pd.DataFrame) -> None:
    months = [m for m in MONTH_ORDER if m in coloc["month_name"].unique()]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    data_month = [coloc[coloc["month_name"] == m]["bias"] for m in months]
    ax1.boxplot(data_month, labels=months, showfliers=False)
    ax1.axhline(0, linestyle="--", linewidth=1)
    ax1.set_ylabel("Bias: HadISD - ERA5 (hPa)")
    ax1.set_title("Monthly bias distribution")
    ax1.tick_params(axis="x", rotation=30)

    seasons = sorted(coloc["season"].dropna().unique())
    data_season = [coloc[coloc["season"] == s]["bias"] for s in seasons]
    ax2.boxplot(data_season, labels=seasons, showfliers=False)
    ax2.axhline(0, linestyle="--", linewidth=1)
    ax2.set_ylabel("Bias: HadISD - ERA5 (hPa)")
    ax2.set_title("Seasonal bias distribution")

    plt.tight_layout()
    save_figure("04_bias_boxplots.png")
    plt.close()


def compute_station_metrics(coloc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for station_id, group in coloc.groupby("station_id"):
        if len(group) < MIN_OBS_FOR_STATION_METRICS:
            continue
        diff = group["bias"]
        corr = group[["hadisd_msl", "era5_msl"]].corr().iloc[0, 1]
        rows.append({
            "station_id": station_id,
            "n_obs": len(group),
            "mean_bias_hadisd_minus_era5": diff.mean(),
            "mae": diff.abs().mean(),
            "rmse": np.sqrt((diff ** 2).mean()),
            "correlation": corr,
            "lat": group["lat"].iloc[0],
            "lon": group["lon"].iloc[0],
        })

    metrics = pd.DataFrame(rows).sort_values("rmse", ascending=False).reset_index(drop=True)
    save_table(metrics, "station_wise_era5_hadisd_metrics.csv")
    return metrics


def plot_station_metric_maps(metrics: pd.DataFrame) -> None:
    if metrics.empty:
        print("No station metrics available for spatial maps.")
        return

    plt.figure(figsize=(8, 6))
    sc = plt.scatter(metrics["lon"], metrics["lat"], c=metrics["rmse"], s=80, edgecolor="black")
    plt.colorbar(sc, label="RMSE (hPa)")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Station-wise ERA5-HadISD RMSE")
    plt.grid(True)
    save_figure("05_station_wise_rmse_map.png")
    plt.close()

    plt.figure(figsize=(8, 6))
    sc = plt.scatter(metrics["lon"], metrics["lat"], c=metrics["mean_bias_hadisd_minus_era5"], s=80, edgecolor="black")
    plt.colorbar(sc, label="Mean bias: HadISD - ERA5 (hPa)")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Station-wise ERA5-HadISD bias")
    plt.grid(True)
    save_figure("06_station_wise_bias_map.png")
    plt.close()


def plot_representative_time_series(coloc: pd.DataFrame, metrics: pd.DataFrame) -> None:
    if metrics.empty:
        return

    selected = {
        "most_observations": metrics.sort_values("n_obs", ascending=False).iloc[0]["station_id"],
        "highest_rmse": metrics.sort_values("rmse", ascending=False).iloc[0]["station_id"],
        "lowest_rmse": metrics.sort_values("rmse", ascending=True).iloc[0]["station_id"],
    }

    for label, station_id in selected.items():
        sub = coloc[coloc["station_id"] == station_id].sort_values("dt")
        plt.figure(figsize=(13, 4))
        plt.plot(sub["dt"], sub["hadisd_msl"], linewidth=1, label="HadISD MSL")
        plt.plot(sub["dt"], sub["era5_msl"], linewidth=1, label="ERA5 interpolated MSL")
        plt.xlabel("Time")
        plt.ylabel("MSL pressure (hPa)")
        plt.title(f"ERA5 vs HadISD time series — {label} — station {station_id}")
        plt.legend()
        plt.grid(True)
        save_figure(f"07_timeseries_{label}.png")
        plt.close()


def basic_hadisd_quality_checks(hadisd: pd.DataFrame) -> pd.DataFrame:
    # Expected hourly observations over each month in the HadISD period.
    expected_total = 0
    for month in [11, 12, 1, 2]:
        year = 2024 if month in [11, 12] else 2025
        expected_total += calendar.monthrange(year, month)[1] * 24

    obs_by_station = hadisd.groupby("station_id").size().rename("n_obs").reset_index()
    obs_by_station["expected_obs"] = expected_total
    obs_by_station["missing_count"] = obs_by_station["expected_obs"] - obs_by_station["n_obs"]
    obs_by_station["missing_rate_pct"] = 100.0 * obs_by_station["missing_count"] / obs_by_station["expected_obs"]
    obs_by_station["flagged_missing"] = obs_by_station["missing_rate_pct"] > MISSING_MAX_PCT

    coords = hadisd.groupby("station_id")[["lat", "lon"]].first().reset_index()
    station_qc = obs_by_station.merge(coords, on="station_id", how="left")

    # Physical plausibility.
    phys_bad = hadisd[(hadisd["value"] < PHYS_MIN) | (hadisd["value"] > PHYS_MAX)].copy()
    phys_count = phys_bad.groupby("station_id").size().rename("n_phys_bad").reset_index()
    station_qc = station_qc.merge(phys_count, on="station_id", how="left")
    station_qc["n_phys_bad"] = station_qc["n_phys_bad"].fillna(0).astype(int)
    station_qc["flagged_physical"] = station_qc["n_phys_bad"] > 0

    # Duplicated station-time records.
    dup_count = (
        hadisd[hadisd.duplicated(subset=["station_id", "dt"], keep=False)]
        .groupby("station_id")
        .size()
        .rename("n_duplicate_station_time")
        .reset_index()
    )
    station_qc = station_qc.merge(dup_count, on="station_id", how="left")
    station_qc["n_duplicate_station_time"] = station_qc["n_duplicate_station_time"].fillna(0).astype(int)
    station_qc["flagged_duplicates"] = station_qc["n_duplicate_station_time"] > 0

    # Temporal jumps.
    jump_rows = []
    for station_id, group in hadisd.groupby("station_id"):
        group = group.sort_values("dt")
        pressure_diff = group["value"].diff().abs()
        hour_diff = group["dt"].diff().dt.total_seconds() / 3600.0
        consecutive = hour_diff <= 1.5
        n_jumps = int(((pressure_diff > JUMP_THRESHOLD_HPA) & consecutive).sum())
        max_jump = float(pressure_diff[consecutive].max()) if consecutive.any() else 0.0
        jump_rows.append({"station_id": station_id, "n_jumps": n_jumps, "max_jump_hpa": max_jump})
    jump_df = pd.DataFrame(jump_rows)
    station_qc = station_qc.merge(jump_df, on="station_id", how="left")
    station_qc["flagged_jumps"] = station_qc["n_jumps"] > 0

    station_qc["flagged_any"] = (
        station_qc["flagged_missing"]
        | station_qc["flagged_physical"]
        | station_qc["flagged_duplicates"]
        | station_qc["flagged_jumps"]
    )

    save_table(station_qc, "hadisd_station_qc.csv")
    save_table(phys_bad, "physically_implausible_hadisd_records.csv")

    return station_qc


def plot_missing_rate(station_qc: pd.DataFrame) -> None:
    ordered = station_qc.sort_values("missing_rate_pct", ascending=False)
    plt.figure(figsize=(11, max(4, 0.35 * len(ordered))))
    plt.barh(ordered["station_id"].astype(str), ordered["missing_rate_pct"])
    plt.axvline(MISSING_MAX_PCT, linestyle="--", label=f"Threshold = {MISSING_MAX_PCT}%")
    plt.xlabel("Missing observations (%)")
    plt.ylabel("Station")
    plt.title("HadISD missing rate by station")
    plt.legend()
    plt.gca().invert_yaxis()
    plt.tight_layout()
    save_figure("08_missing_rate_by_station.png")
    plt.close()


def plot_hadisd_distribution(hadisd: pd.DataFrame) -> None:
    plt.figure(figsize=(9, 4))
    plt.hist(hadisd["value"], bins=60, edgecolor="white")
    plt.axvline(PHYS_MIN, linestyle="--", label=f"Physical lower bound = {PHYS_MIN}")
    plt.axvline(PHYS_MAX, linestyle="--", label=f"Physical upper bound = {PHYS_MAX}")
    plt.xlabel("MSL pressure (hPa)")
    plt.ylabel("Count")
    plt.title("HadISD pressure distribution")
    plt.legend()
    plt.grid(True)
    save_figure("09_hadisd_pressure_distribution.png")
    plt.close()


def plot_qc_filtering_effect(coloc: pd.DataFrame, station_qc: pd.DataFrame) -> pd.DataFrame:
    flagged_ids = station_qc.loc[station_qc["flagged_any"], "station_id"].tolist()
    clean_coloc = coloc[~coloc["station_id"].isin(flagged_ids)].copy()

    def summary(df: pd.DataFrame, label: str) -> Dict[str, object]:
        diff = df["bias"]
        return {
            "dataset": label,
            "n_pairs": len(df),
            "n_stations": df["station_id"].nunique(),
            "mean_bias": diff.mean(),
            "mae": diff.abs().mean(),
            "rmse": np.sqrt((diff ** 2).mean()),
            "correlation": df[["hadisd_msl", "era5_msl"]].corr().iloc[0, 1] if len(df) > 1 else np.nan,
        }

    qc_effect = pd.DataFrame([
        summary(coloc, "All stations"),
        summary(clean_coloc, "Clean stations only"),
    ])
    save_table(qc_effect, "qc_filtering_effect.csv")

    plt.figure(figsize=(7, 4))
    plt.bar(qc_effect["dataset"], qc_effect["rmse"])
    plt.ylabel("RMSE (hPa)")
    plt.title("Effect of QC filtering on ERA5-HadISD RMSE")
    plt.grid(axis="y")
    save_figure("10_qc_filtering_effect_rmse.png")
    plt.close()

    return qc_effect


def residual_outlier_detection(coloc: pd.DataFrame) -> pd.DataFrame:
    q1 = coloc["bias"].quantile(0.25)
    q3 = coloc["bias"].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    outliers = coloc[(coloc["bias"] < lower) | (coloc["bias"] > upper)].copy()
    save_table(outliers, "residual_outliers_era5_hadisd.csv")

    plt.figure(figsize=(10, 4))
    plt.hist(coloc["bias"], bins=60, edgecolor="white")
    plt.axvline(lower, linestyle="--", label="IQR outlier bounds")
    plt.axvline(upper, linestyle="--")
    plt.xlabel("Bias: HadISD - ERA5 (hPa)")
    plt.ylabel("Count")
    plt.title("Residual-based outlier detection")
    plt.legend()
    plt.grid(True)
    save_figure("11_residual_outlier_distribution.png")
    plt.close()

    return outliers


def plot_station_map(hadisd: pd.DataFrame, era5: Dict[str, Dict[str, object]], station_qc: pd.DataFrame) -> None:
    era5_sample = list(era5.values())[0]

    sta_info = hadisd.groupby(["station_id", "lat", "lon"]).size().reset_index(name="n_obs")
    sta_info = sta_info.merge(station_qc[["station_id", "flagged_any"]], on="station_id", how="left")

    clean = sta_info[~sta_info["flagged_any"].fillna(False)]
    flagged = sta_info[sta_info["flagged_any"].fillna(False)]

    plt.figure(figsize=(10, 8))
    plt.scatter(era5_sample["lon"], era5_sample["lat"], s=4, alpha=0.45, label="ERA5 grid")

    if len(clean) > 0:
        sizes = clean["n_obs"] / clean["n_obs"].max() * 200 + 40
        plt.scatter(clean["lon"], clean["lat"], s=sizes, edgecolor="black", label=f"HadISD clean ({len(clean)})")

    if len(flagged) > 0:
        plt.scatter(flagged["lon"], flagged["lat"], s=90, marker="x", linewidths=1.5, label=f"HadISD flagged ({len(flagged)})")

    for _, row in sta_info.iterrows():
        plt.annotate(str(row["station_id"]).split("-")[0], (row["lon"], row["lat"]), fontsize=6, xytext=(3, 3), textcoords="offset points")

    plt.xlim(LON_MIN - 0.5, LON_MAX + 0.5)
    plt.ylim(LAT_MIN - 0.5, LAT_MAX + 0.5)
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("HadISD stations vs ERA5 grid")
    plt.legend(loc="lower right")
    plt.grid(True)
    save_figure("12_station_map_hadisd_vs_era5_grid.png")
    plt.close()


def load_hadisd_all_vars(path_or_folder: str) -> pd.DataFrame:
    files = get_hadisd_files(path_or_folder)
    frames = []
    for file in files:
        try:
            frames.append(pd.read_csv(file))
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    if "lat" in df.columns and "lon" in df.columns:
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df = df[df["lat"].between(LAT_MIN, LAT_MAX) & df["lon"].between(LON_MIN, LON_MAX)]
    return df


def plot_variable_availability(path_or_folder: str) -> None:
    df_all = load_hadisd_all_vars(path_or_folder)
    if df_all.empty or "sensor_code" not in df_all.columns:
        print("Skipping variable availability: sensor_code column not available.")
        return

    avail = df_all.groupby(["station_id", "sensor_code"]).size().unstack(fill_value=0)
    avail_bool = (avail > 0).astype(int)
    save_table(avail_bool.reset_index(), "variable_availability_by_station.csv")

    fig, ax = plt.subplots(figsize=(max(7, len(avail_bool.columns) + 2), max(4, len(avail_bool) * 0.4 + 2)))
    ax.imshow(avail_bool.values, aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(avail_bool.columns)))
    ax.set_xticklabels(avail_bool.columns, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(avail_bool.index)))
    ax.set_yticklabels([str(s)[:18] for s in avail_bool.index], fontsize=8)

    for i in range(len(avail_bool.index)):
        for j in range(len(avail_bool.columns)):
            ax.text(j, i, "✓" if avail_bool.values[i, j] else "✗", ha="center", va="center", fontsize=9)

    ax.set_title("Variable availability per HadISD station")
    plt.tight_layout()
    save_figure("13_variable_availability_by_station.png")
    plt.close()


def approximate_distance_km(points_a: np.ndarray, points_b: np.ndarray) -> np.ndarray:
    """Approximate minimum distance from each point in A to any point in B."""
    min_distances = []
    for lat_a, lon_a in points_a:
        distances = np.sqrt(
            ((points_b[:, 0] - lat_a) * 111.0) ** 2
            + ((points_b[:, 1] - lon_a) * 111.0 * np.cos(np.radians(lat_a))) ** 2
        )
        min_distances.append(distances.min())
    return np.array(min_distances)


def plot_grid_coverage(hadisd: pd.DataFrame, era5: Dict[str, Dict[str, object]]) -> pd.DataFrame:
    era5_sample = list(era5.values())[0]
    sta_coords = hadisd[["lat", "lon"]].drop_duplicates().values
    era5_points = np.column_stack([era5_sample["lat"], era5_sample["lon"]])

    min_dist = approximate_distance_km(era5_points, sta_coords)
    coverage_df = pd.DataFrame({
        "lat": era5_sample["lat"],
        "lon": era5_sample["lon"],
        "distance_to_nearest_station_km": min_dist,
        "covered": min_dist <= COVERAGE_THRESHOLD_KM,
    })
    save_table(coverage_df, "era5_grid_coverage_by_hadisd.csv")

    grid = reshape_grid(
        min_dist,
        era5_sample["lon"],
        era5_sample["lat"],
        era5_sample["lats_uniq"],
        era5_sample["lons_uniq"],
    )

    plt.figure(figsize=(10, 7))
    im = plt.imshow(
        grid,
        extent=[
            era5_sample["lons_uniq"].min(),
            era5_sample["lons_uniq"].max(),
            era5_sample["lats_uniq"].min(),
            era5_sample["lats_uniq"].max(),
        ],
        origin="lower",
        aspect="auto",
    )
    plt.colorbar(im, label="Distance to nearest HadISD station (km)")
    plt.scatter(hadisd["lon"], hadisd["lat"], s=55, edgecolor="black", label="HadISD stations")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("ERA5 grid coverage by HadISD stations")
    plt.legend()
    plt.grid(True)
    save_figure("14_era5_grid_coverage_by_hadisd.png")
    plt.close()

    return coverage_df


# =============================================================================
# 5. REPORT NOTES
# =============================================================================

def write_report_notes(
    coloc: pd.DataFrame,
    station_qc: pd.DataFrame,
    metrics: pd.DataFrame,
    qc_effect: pd.DataFrame,
    coverage_df: pd.DataFrame,
) -> None:
    overall_bias = coloc["bias"].mean()
    overall_mae = coloc["bias"].abs().mean()
    overall_rmse = np.sqrt((coloc["bias"] ** 2).mean())
    overall_corr = coloc[["hadisd_msl", "era5_msl"]].corr().iloc[0, 1]

    notes = f"""# HadISD–ERA5 Data Quality and Interpolation Report Notes

## Objective
The objective of this task is to improve the HadISD–ERA5 data aggregation pipeline by adding interpolation diagnostics, temporal matching checks, station-wise quality metrics, residual-based outlier detection, and report-ready figures.

## Dataset interpretation
HadISD provides point-based station observations, while ERA5 provides gridded reanalysis fields. Therefore, ERA5 values must be spatially interpolated to the HadISD station coordinates and temporally matched to the HadISD timestamps before the two datasets can be compared.

## Methodology
1. ERA5 monthly mean sea-level pressure grids were loaded from CSV files.
2. HadISD pressure observations were filtered to the Adriatic domain and the target period.
3. Each HadISD observation was matched to the nearest ERA5 hourly timestamp using a ±{ALIGN_TOL_MIN} minute tolerance.
4. ERA5 pressure was extracted at station coordinates using bilinear interpolation from the four surrounding ERA5 grid points.
5. Bias was computed as HadISD minus ERA5.
6. Data quality was evaluated using missing-rate checks, physical plausibility limits, duplicate station-time records, temporal jump detection, residual outlier analysis, and station-wise RMSE/MAE/correlation.

## Main numerical results
- Co-location pairs: {len(coloc)}
- Matched stations: {coloc['station_id'].nunique()}
- Overall bias, HadISD - ERA5: {overall_bias:+.3f} hPa
- Overall MAE: {overall_mae:.3f} hPa
- Overall RMSE: {overall_rmse:.3f} hPa
- Overall correlation: {overall_corr:.3f}
- QC flagged stations: {int(station_qc['flagged_any'].sum())} / {len(station_qc)}
- ERA5 grid points farther than {COVERAGE_THRESHOLD_KM:.0f} km from a HadISD station: {int((~coverage_df['covered']).sum())} / {len(coverage_df)}

## Figures generated
1. `01_alignment_scatter_by_month.png` — ERA5 vs HadISD monthly scatter plots.
2. `02_temporal_matching_quality.png` — temporal matching difference histogram.
3. `03_interpolation_diagnostic.png` — example of bilinear interpolation around a station.
4. `04_bias_boxplots.png` — monthly and seasonal bias distributions.
5. `05_station_wise_rmse_map.png` — spatial distribution of station-wise RMSE.
6. `06_station_wise_bias_map.png` — spatial distribution of station-wise bias.
7. `07_timeseries_*.png` — representative time-series comparisons.
8. `08_missing_rate_by_station.png` — HadISD missing-rate quality check.
9. `09_hadisd_pressure_distribution.png` — physical plausibility check.
10. `10_qc_filtering_effect_rmse.png` — effect of removing QC-flagged stations.
11. `11_residual_outlier_distribution.png` — residual-based outlier detection.
12. `12_station_map_hadisd_vs_era5_grid.png` — station locations against the ERA5 grid.
13. `13_variable_availability_by_station.png` — HadISD variable availability by station.
14. `14_era5_grid_coverage_by_hadisd.png` — ERA5 grid coverage by HadISD stations.

## Conclusion
The improved pipeline converts the original ERA5–HadISD matching workflow into a reproducible data-quality and interpolation analysis. The generated plots and tables can be directly used in the project report to explain how the two datasets were aligned, how interpolation was performed, and which stations or observations are reliable for further model development.
"""

    path = REPORT_DIR / "hadisd_era5_report_notes.md"
    path.write_text(notes, encoding="utf-8")
    print(f"Saved report notes -> {path}")


# =============================================================================
# 6. MAIN PIPELINE
# =============================================================================

def main() -> None:
    check_input_files()

    era5 = load_era5_all()
    hadisd = load_hadisd(HADISD_PATH, var_code=HADISD_VAR)
    print_data_overview(hadisd, era5)

    # Basic overview table.
    hadisd_overview = pd.DataFrame({
        "metric": [
            "n_observations",
            "n_stations",
            "start_time",
            "end_time",
            "min_pressure_hpa",
            "max_pressure_hpa",
        ],
        "value": [
            len(hadisd),
            hadisd["station_id"].nunique(),
            str(hadisd["dt"].min()),
            str(hadisd["dt"].max()),
            hadisd["value"].min(),
            hadisd["value"].max(),
        ],
    })
    save_table(hadisd_overview, "hadisd_overview.csv")

    coloc = build_colocation(hadisd, era5, tol_min=ALIGN_TOL_MIN)
    save_table(coloc, "colocation_era5_hadisd_msl.csv")

    # Alignment and interpolation diagnostics.
    plot_alignment_scatter(coloc)
    plot_temporal_matching_quality(coloc)
    plot_interpolation_diagnostic(coloc, era5)

    # Bias and station performance.
    compute_bias_statistics(coloc)
    plot_bias_boxplots(coloc)
    station_metrics = compute_station_metrics(coloc)
    plot_station_metric_maps(station_metrics)
    plot_representative_time_series(coloc, station_metrics)

    # HadISD quality checks.
    station_qc = basic_hadisd_quality_checks(hadisd)
    plot_missing_rate(station_qc)
    plot_hadisd_distribution(hadisd)
    qc_effect = plot_qc_filtering_effect(coloc, station_qc)
    residual_outlier_detection(coloc)

    # Coverage diagnostics.
    plot_station_map(hadisd, era5, station_qc)
    plot_variable_availability(HADISD_PATH)
    coverage_df = plot_grid_coverage(hadisd, era5)

    write_report_notes(coloc, station_qc, station_metrics, qc_effect, coverage_df)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"Figures saved in: {FIG_DIR.resolve()}")
    print(f"Tables saved in : {TABLE_DIR.resolve()}")
    print(f"Report notes    : {(REPORT_DIR / 'hadisd_era5_report_notes.md').resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
