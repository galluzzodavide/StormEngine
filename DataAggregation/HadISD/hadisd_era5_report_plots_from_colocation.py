"""
StormEngine — Report plots from existing ERA5-HadISD co-location table

Use this script when the raw HadISD CSV is not available, but the notebook has already
generated:
    colocation_era5_hadisd_msl.csv
    hadisd_station_qc.csv   optional

Put this file in:
    StormEngine/DataAggregation/HadISD/

Then run:
    py hadisd_era5_report_plots_from_colocation.py

Outputs:
    reports/figures/hadisd_era5/*.png
    reports/tables/*.csv
    reports/hadisd_era5_report_notes.md
"""

from __future__ import annotations

import calendar
import os
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# =============================================================================
# CONFIGURATION
# =============================================================================

COLOCATION_PATH = "colocation_era5_hadisd_msl.csv"
QC_PATH = "hadisd_station_qc.csv"

ERA5_FILES = {
    "November": {"path": "final_2024_11_msl.csv", "year": 2024, "month": 11},
    "December": {"path": "final_2024_12_msl.csv", "year": 2024, "month": 12},
    "January": {"path": "final_2024_1_msl.csv", "year": 2025, "month": 1},
    "February": {"path": "final_2024_2_msl.csv", "year": 2025, "month": 2},
}

PA_TO_HPA = 1.0 / 100.0
SEASON_MAP = {11: "Autumn", 12: "Winter", 1: "Winter", 2: "Winter"}
MONTH_ORDER = ["November", "December", "January", "February"]

REPORT_DIR = Path("reports")
FIG_DIR = REPORT_DIR / "figures" / "hadisd_era5"
TABLE_DIR = REPORT_DIR / "tables"
FIG_DIR.mkdir(parents=True, exist_ok=True)
TABLE_DIR.mkdir(parents=True, exist_ok=True)

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


# =============================================================================
# HELPERS
# =============================================================================

def save_fig(name: str) -> None:
    path = FIG_DIR / name
    plt.savefig(path, bbox_inches="tight")
    print(f"Saved figure -> {path}")


def save_table(df: pd.DataFrame, name: str) -> None:
    path = TABLE_DIR / name
    df.to_csv(path, index=False)
    print(f"Saved table  -> {path}")


def first_existing_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"Could not find {label}. Tried: {candidates}. Existing columns: {list(df.columns)}")


def month_name_from_number(m: int) -> str:
    return calendar.month_name[int(m)]


def haversine_km(lon1, lat1, lon2, lat2):
    """Vectorized haversine distance in km."""
    R = 6371.0
    lon1 = np.radians(lon1)
    lat1 = np.radians(lat1)
    lon2 = np.radians(lon2)
    lat2 = np.radians(lat2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# =============================================================================
# LOAD AND STANDARDIZE COLOCATION TABLE
# =============================================================================

def load_colocation() -> pd.DataFrame:
    if not os.path.isfile(COLOCATION_PATH):
        raise FileNotFoundError(
            f"Missing {COLOCATION_PATH}. Put this script in the same folder as the existing co-location CSV."
        )

    df = pd.read_csv(COLOCATION_PATH)
    print("Loaded co-location table:", COLOCATION_PATH)
    print("Shape:", df.shape)
    print("Columns:", list(df.columns))

    station_col = first_existing_column(df, ["station_id", "station", "id"], "station id")
    lat_col = first_existing_column(df, ["lat", "latitude"], "latitude")
    lon_col = first_existing_column(df, ["lon", "longitude"], "longitude")
    dt_col = first_existing_column(df, ["dt", "time", "datetime", "hadisd_dt"], "datetime")
    hadisd_col = first_existing_column(df, ["hadisd_msl", "hadisd", "value", "PRESS", "pressure_hadisd"], "HadISD MSL")
    era5_col = first_existing_column(df, ["era5_msl", "era5", "msl", "pressure_era5"], "ERA5 MSL")

    rename_map = {
        station_col: "station_id",
        lat_col: "lat",
        lon_col: "lon",
        dt_col: "dt",
        hadisd_col: "hadisd_msl",
        era5_col: "era5_msl",
    }

    if "era5_dt" not in df.columns:
        # If there is no separate ERA5 timestamp, use HadISD timestamp as fallback.
        df["era5_dt"] = df[dt_col]

    df = df.rename(columns=rename_map)

    df["dt"] = pd.to_datetime(df["dt"], utc=True, errors="coerce")
    df["era5_dt"] = pd.to_datetime(df["era5_dt"], utc=True, errors="coerce")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["hadisd_msl"] = pd.to_numeric(df["hadisd_msl"], errors="coerce")
    df["era5_msl"] = pd.to_numeric(df["era5_msl"], errors="coerce")

    df = df.dropna(subset=["station_id", "dt", "lat", "lon", "hadisd_msl", "era5_msl"]).copy()

    # Convert ERA5 from Pa to hPa only if values look like Pa.
    if df["era5_msl"].median() > 2000:
        df["era5_msl"] = df["era5_msl"] * PA_TO_HPA

    if df["hadisd_msl"].median() > 2000:
        df["hadisd_msl"] = df["hadisd_msl"] * PA_TO_HPA

    if "bias" not in df.columns:
        df["bias"] = df["hadisd_msl"] - df["era5_msl"]
    else:
        df["bias"] = pd.to_numeric(df["bias"], errors="coerce")
        # Recompute if bias seems empty.
        if df["bias"].isna().all():
            df["bias"] = df["hadisd_msl"] - df["era5_msl"]

    if "dt_diff_min" not in df.columns:
        df["dt_diff_min"] = (df["dt"] - df["era5_dt"]).abs().dt.total_seconds() / 60.0
    else:
        df["dt_diff_min"] = pd.to_numeric(df["dt_diff_min"], errors="coerce")

    if "month_name" not in df.columns:
        df["month_num"] = df["dt"].dt.month
        df["month_name"] = df["month_num"].map(month_name_from_number)
    else:
        # Ensure consistent capitalization
        df["month_name"] = df["month_name"].astype(str).str.strip()

    if "season" not in df.columns:
        df["season"] = df["dt"].dt.month.map(SEASON_MAP)

    df = df.sort_values("dt").reset_index(drop=True)

    print("\nStandardized co-location table:")
    print("Rows:", len(df))
    print("Stations:", df["station_id"].nunique())
    print("Time range:", df["dt"].min(), "->", df["dt"].max())
    print("Pressure range HadISD:", df["hadisd_msl"].min(), "->", df["hadisd_msl"].max())
    print("Pressure range ERA5  :", df["era5_msl"].min(), "->", df["era5_msl"].max())
    print()

    save_table(df.head(50), "preview_colocation_standardized.csv")
    return df


# =============================================================================
# LOAD ERA5 GRID ONLY FOR INTERPOLATION DIAGNOSTIC
# =============================================================================

def load_era5_month(path: str, year: int, month: int) -> Optional[Dict[str, object]]:
    if not os.path.isfile(path):
        return None

    df = pd.read_csv(path)

    if "lon" not in df.columns or "lat" not in df.columns:
        return None

    sample_cols = [c for c in df.columns if c.startswith("SAMPLE_")]
    if not sample_cols:
        return None

    base = pd.Timestamp(year=year, month=month, day=1, hour=0, tz="UTC")
    timestamps = [base + pd.Timedelta(hours=i) for i in range(len(sample_cols))]
    samples = df[sample_cols].values.astype(float)

    if np.nanmedian(samples) > 2000:
        samples = samples * PA_TO_HPA

    return {
        "timestamps": timestamps,
        "samples": samples,
        "lon": df["lon"].values.astype(float),
        "lat": df["lat"].values.astype(float),
        "lons_uniq": np.sort(df["lon"].dropna().unique().astype(float)),
        "lats_uniq": np.sort(df["lat"].dropna().unique().astype(float)),
    }


def load_era5_available() -> Dict[str, Dict[str, object]]:
    out = {}
    for month_name, meta in ERA5_FILES.items():
        d = load_era5_month(meta["path"], meta["year"], meta["month"])
        if d is not None:
            out[month_name] = d
            print(f"Loaded ERA5 grid for diagnostic: {month_name}")
    return out


def reshape_grid(vals: np.ndarray, lon: np.ndarray, lat: np.ndarray, lats_u: np.ndarray, lons_u: np.ndarray) -> np.ndarray:
    grid = np.full((len(lats_u), len(lons_u)), np.nan)
    lon_index = {v: i for i, v in enumerate(lons_u)}
    lat_index = {v: i for i, v in enumerate(lats_u)}
    for value, lo, la in zip(vals, lon, lat):
        if not (np.isnan(lo) or np.isnan(la)):
            grid[lat_index[la], lon_index[lo]] = value
    return grid


# =============================================================================
# PLOTS
# =============================================================================

def plot_alignment_scatter(coloc: pd.DataFrame) -> None:
    months = [m for m in MONTH_ORDER if m in set(coloc["month_name"])]
    if not months:
        months = list(coloc["month_name"].dropna().unique())[:4]

    n = len(months)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), sharex=False, sharey=False)
    if n == 1:
        axes = [axes]

    for ax, month in zip(axes, months):
        sub = coloc[coloc["month_name"] == month]
        ax.scatter(sub["era5_msl"], sub["hadisd_msl"], alpha=0.25, s=8)

        lim_min = min(sub["era5_msl"].min(), sub["hadisd_msl"].min()) - 1
        lim_max = max(sub["era5_msl"].max(), sub["hadisd_msl"].max()) + 1
        ax.plot([lim_min, lim_max], [lim_min, lim_max], "k--", linewidth=1.2)

        diff = sub["bias"]
        bias = diff.mean()
        rmse = np.sqrt((diff ** 2).mean())
        corr = sub[["era5_msl", "hadisd_msl"]].corr().iloc[0, 1]
        ax.set_title(f"{month}\nBias={bias:+.2f}, RMSE={rmse:.2f}, r={corr:.3f}")
        ax.set_xlabel("ERA5 MSL (hPa)")
        ax.set_ylabel("HadISD MSL (hPa)")

    fig.suptitle("ERA5 vs HadISD MSL pressure by month")
    plt.tight_layout()
    save_fig("01_alignment_scatter_by_month.png")
    plt.close()


def plot_temporal_matching_quality(coloc: pd.DataFrame) -> None:
    summary = coloc["dt_diff_min"].describe().reset_index()
    summary.columns = ["statistic", "dt_diff_min"]
    save_table(summary, "temporal_matching_quality.csv")

    plt.figure(figsize=(8, 4))
    plt.hist(coloc["dt_diff_min"].dropna(), bins=30, edgecolor="white")
    plt.xlabel("Absolute time difference between HadISD and ERA5 (minutes)")
    plt.ylabel("Number of matched observations")
    plt.title("Temporal matching quality")
    save_fig("02_temporal_matching_quality.png")
    plt.close()


def plot_interpolation_diagnostic(coloc: pd.DataFrame, era5: Dict[str, Dict[str, object]]) -> None:
    if not era5:
        print("Skipping interpolation diagnostic: no ERA5 grid files available.")
        return

    # Pick the first row with an available month.
    candidates = coloc[coloc["month_name"].isin(era5.keys())].copy()
    if candidates.empty:
        print("Skipping interpolation diagnostic: no matching month between co-location and ERA5 files.")
        return

    example = candidates.iloc[0]
    month_name = example["month_name"]
    d = era5[month_name]
    example_lat = float(example["lat"])
    example_lon = float(example["lon"])

    # Choose closest ERA5 diagnostic time.
    era5_times = pd.DatetimeIndex(d["timestamps"])
    era5_dt = pd.Timestamp(example["era5_dt"])
    idx = int(np.abs(era5_times - era5_dt).argmin())

    grid = reshape_grid(
        d["samples"][:, idx],
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
    plt.scatter(surrounding["lon"], surrounding["lat"], s=120, edgecolor="black", label="4 surrounding ERA5 points")
    plt.scatter(example_lon, example_lat, s=180, marker="*", edgecolor="black", label="HadISD station")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Bilinear interpolation diagnostic")
    plt.legend()
    save_fig("03_interpolation_diagnostic.png")
    plt.close()


def plot_bias_boxplots(coloc: pd.DataFrame) -> None:
    months = [m for m in MONTH_ORDER if m in set(coloc["month_name"])]
    if not months:
        months = list(coloc["month_name"].dropna().unique())[:12]

    plt.figure(figsize=(10, 5))
    data = [coloc[coloc["month_name"] == m]["bias"].dropna() for m in months]
    plt.boxplot(data, labels=months, showfliers=False)
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.ylabel("Bias: HadISD - ERA5 (hPa)")
    plt.title("Monthly bias distribution")
    save_fig("04_bias_boxplots.png")
    plt.close()


def compute_station_metrics(coloc: pd.DataFrame) -> pd.DataFrame:
    def metrics(g):
        diff = g["bias"]
        return pd.Series({
            "n_obs": len(g),
            "mean_bias_hadisd_minus_era5": diff.mean(),
            "mae": diff.abs().mean(),
            "rmse": np.sqrt((diff ** 2).mean()),
            "correlation": g[["hadisd_msl", "era5_msl"]].corr().iloc[0, 1],
            "lat": g["lat"].iloc[0],
            "lon": g["lon"].iloc[0],
        })

    out = coloc.groupby("station_id").apply(metrics).reset_index()
    save_table(out, "station_wise_era5_hadisd_metrics.csv")
    return out


def plot_station_metric_maps(metrics: pd.DataFrame) -> None:
    plt.figure(figsize=(8, 6))
    sc = plt.scatter(metrics["lon"], metrics["lat"], c=metrics["rmse"], s=80, edgecolor="black")
    plt.colorbar(sc, label="RMSE (hPa)")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Station-wise ERA5-HadISD RMSE")
    save_fig("05_station_wise_rmse_map.png")
    plt.close()

    plt.figure(figsize=(8, 6))
    sc = plt.scatter(metrics["lon"], metrics["lat"], c=metrics["mean_bias_hadisd_minus_era5"], s=80, edgecolor="black")
    plt.colorbar(sc, label="Bias HadISD - ERA5 (hPa)")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Station-wise ERA5-HadISD bias")
    save_fig("06_station_wise_bias_map.png")
    plt.close()


def plot_representative_timeseries(coloc: pd.DataFrame, metrics: pd.DataFrame) -> None:
    selected = {
        "most_observations": metrics.sort_values("n_obs", ascending=False).iloc[0]["station_id"],
        "highest_rmse": metrics.sort_values("rmse", ascending=False).iloc[0]["station_id"],
        "lowest_rmse": metrics.sort_values("rmse", ascending=True).iloc[0]["station_id"],
    }

    for label, sid in selected.items():
        sub = coloc[coloc["station_id"] == sid].sort_values("dt")
        plt.figure(figsize=(13, 4))
        plt.plot(sub["dt"], sub["hadisd_msl"], label="HadISD MSL", linewidth=1)
        plt.plot(sub["dt"], sub["era5_msl"], label="ERA5 interpolated MSL", linewidth=1)
        plt.xlabel("Time")
        plt.ylabel("MSL pressure (hPa)")
        plt.title(f"ERA5 vs HadISD time series — {label} — station {sid}")
        plt.legend()
        save_fig(f"07_timeseries_{label}.png")
        plt.close()


def plot_qc_or_missing(coloc: pd.DataFrame) -> Optional[pd.DataFrame]:
    if os.path.isfile(QC_PATH):
        qc = pd.read_csv(QC_PATH)
        save_table(qc, "hadisd_station_qc_copy.csv")

        # Try to identify useful numeric columns.
        numeric_cols = qc.select_dtypes(include=[np.number]).columns.tolist()
        station_col = "station_id" if "station_id" in qc.columns else qc.columns[0]

        if numeric_cols:
            col = numeric_cols[0]
            # Prefer missing-related column if exists.
            for c in numeric_cols:
                if "missing" in c.lower():
                    col = c
                    break

            top = qc.sort_values(col, ascending=False).head(25)
            plt.figure(figsize=(12, 5))
            plt.bar(top[station_col].astype(str), top[col])
            plt.xticks(rotation=90)
            plt.ylabel(col)
            plt.title(f"Station QC diagnostic: {col}")
            save_fig("08_station_qc_diagnostic.png")
            plt.close()

        return qc

    # Fallback: count observations per station.
    counts = coloc.groupby("station_id").size().sort_values(ascending=False).reset_index(name="n_observations")
    save_table(counts, "station_observation_counts.csv")
    top = counts.head(25)
    plt.figure(figsize=(12, 5))
    plt.bar(top["station_id"].astype(str), top["n_observations"])
    plt.xticks(rotation=90)
    plt.ylabel("Number of matched observations")
    plt.title("Matched observations by station")
    save_fig("08_station_observation_counts.png")
    plt.close()
    return None


def plot_pressure_distribution(coloc: pd.DataFrame) -> None:
    plt.figure(figsize=(9, 5))
    plt.hist(coloc["hadisd_msl"], bins=60, alpha=0.65, label="HadISD")
    plt.hist(coloc["era5_msl"], bins=60, alpha=0.65, label="ERA5")
    plt.xlabel("MSL pressure (hPa)")
    plt.ylabel("Count")
    plt.title("Pressure value distribution")
    plt.legend()
    save_fig("09_pressure_distribution.png")
    plt.close()


def plot_qc_filtering_effect(coloc: pd.DataFrame, qc: Optional[pd.DataFrame]) -> None:
    if qc is None or "station_id" not in qc.columns:
        print("Skipping QC filtering effect: no station_id column in QC table.")
        return

    # Identify likely flag columns.
    flag_cols = [c for c in qc.columns if "flag" in c.lower()]
    if not flag_cols:
        print("Skipping QC filtering effect: no flag columns found in QC table.")
        return

    flag_col = flag_cols[0]
    flagged = qc[qc[flag_col].astype(str).str.lower().isin(["true", "1", "yes", "y"])].copy()
    flagged_ids = set(flagged["station_id"])

    clean = coloc[~coloc["station_id"].isin(flagged_ids)].copy()
    if clean.empty:
        print("Skipping QC filtering effect: all stations were filtered out.")
        return

    def summary(df, label):
        diff = df["bias"]
        return {
            "dataset": label,
            "n_pairs": len(df),
            "n_stations": df["station_id"].nunique(),
            "mean_bias": diff.mean(),
            "mae": diff.abs().mean(),
            "rmse": np.sqrt((diff ** 2).mean()),
            "correlation": df[["hadisd_msl", "era5_msl"]].corr().iloc[0, 1],
        }

    out = pd.DataFrame([
        summary(coloc, "All stations"),
        summary(clean, "Clean stations only"),
    ])

    save_table(out, "qc_filtering_effect.csv")

    plt.figure(figsize=(7, 4))
    plt.bar(out["dataset"], out["rmse"])
    plt.ylabel("RMSE (hPa)")
    plt.title("Effect of QC filtering on RMSE")
    save_fig("10_qc_filtering_effect_rmse.png")
    plt.close()


def plot_residual_outliers(coloc: pd.DataFrame) -> None:
    q1 = coloc["bias"].quantile(0.25)
    q3 = coloc["bias"].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    outliers = coloc[(coloc["bias"] < lower) | (coloc["bias"] > upper)].copy()
    save_table(outliers, "residual_outliers_era5_hadisd.csv")

    plt.figure(figsize=(10, 4))
    plt.hist(coloc["bias"], bins=60, edgecolor="white")
    plt.axvline(lower, linestyle="--", label="IQR bounds")
    plt.axvline(upper, linestyle="--")
    plt.xlabel("Bias: HadISD - ERA5 (hPa)")
    plt.ylabel("Count")
    plt.title("Residual-based outlier detection")
    plt.legend()
    save_fig("11_residual_outlier_distribution.png")
    plt.close()


def plot_station_map(coloc: pd.DataFrame, era5: Dict[str, Dict[str, object]]) -> None:
    stations = coloc[["station_id", "lat", "lon"]].drop_duplicates()

    plt.figure(figsize=(8, 6))

    if era5:
        first = next(iter(era5.values()))
        plt.scatter(first["lon"], first["lat"], s=6, alpha=0.25, label="ERA5 grid points")

    plt.scatter(stations["lon"], stations["lat"], s=35, edgecolor="black", label="HadISD stations")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("HadISD station locations and ERA5 grid")
    plt.legend()
    save_fig("12_station_map_hadisd_vs_era5_grid.png")
    plt.close()


def plot_coverage(coloc: pd.DataFrame, era5: Dict[str, Dict[str, object]]) -> None:
    if not era5:
        print("Skipping coverage map: no ERA5 grid files available.")
        return

    stations = coloc[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    first = next(iter(era5.values()))
    grid = pd.DataFrame({"lat": first["lat"], "lon": first["lon"]})

    min_dist = []
    for _, g in grid.iterrows():
        d = haversine_km(g["lon"], g["lat"], stations["lon"].values, stations["lat"].values)
        min_dist.append(float(np.nanmin(d)))

    grid["nearest_station_km"] = min_dist
    save_table(grid, "era5_grid_nearest_hadisd_station.csv")

    plt.figure(figsize=(8, 6))
    sc = plt.scatter(grid["lon"], grid["lat"], c=grid["nearest_station_km"], s=20)
    plt.scatter(stations["lon"], stations["lat"], s=25, edgecolor="black", label="HadISD stations")
    plt.colorbar(sc, label="Distance to nearest HadISD station (km)")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("ERA5 grid coverage by HadISD stations")
    plt.legend()
    save_fig("13_era5_grid_coverage_by_hadisd.png")
    plt.close()


def write_report_notes(coloc: pd.DataFrame, metrics: pd.DataFrame) -> None:
    notes = f"""# HadISD–ERA5 Data Quality and Interpolation Diagnostics

## Objective
This workflow evaluates the quality of the existing ERA5-HadISD co-location table for mean sea-level pressure.

## Data Type
HadISD provides point-based station observations, while ERA5 provides gridded reanalysis data. Therefore, spatial and temporal co-location is required before comparison.

## Main Diagnostics Generated
- ERA5 vs HadISD monthly scatter plots.
- Temporal matching quality histogram.
- Bilinear interpolation diagnostic figure.
- Monthly bias boxplots.
- Station-wise RMSE and bias maps.
- Representative station time-series comparisons.
- QC/missing-data diagnostics.
- Residual-based outlier detection.
- Station coverage map against the ERA5 grid.

## Summary
Number of matched pairs: {len(coloc)}
Number of stations: {coloc['station_id'].nunique()}
Mean bias HadISD - ERA5: {coloc['bias'].mean():.3f} hPa
Overall RMSE: {np.sqrt((coloc['bias'] ** 2).mean()):.3f} hPa
Median station RMSE: {metrics['rmse'].median():.3f} hPa

## Suggested Report Text
The HadISD station observations were compared against ERA5 mean sea-level pressure values using the existing co-location table. Since HadISD observations are point-based and ERA5 is gridded, interpolation diagnostics were generated to illustrate how ERA5 grid values relate to station locations. Data quality was evaluated using temporal matching checks, station-wise RMSE and bias, residual outlier detection, and QC-based filtering where available.
"""
    path = REPORT_DIR / "hadisd_era5_report_notes.md"
    path.write_text(notes, encoding="utf-8")
    print(f"Saved report notes -> {path}")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    print("=" * 80)
    print("StormEngine — HadISD × ERA5 report plots from existing co-location table")
    print("=" * 80)
    print("Working directory:", os.getcwd())
    print()

    coloc = load_colocation()
    era5 = load_era5_available()

    plot_alignment_scatter(coloc)
    plot_temporal_matching_quality(coloc)
    plot_interpolation_diagnostic(coloc, era5)
    plot_bias_boxplots(coloc)

    metrics = compute_station_metrics(coloc)
    plot_station_metric_maps(metrics)
    plot_representative_timeseries(coloc, metrics)

    qc = plot_qc_or_missing(coloc)
    plot_pressure_distribution(coloc)
    plot_qc_filtering_effect(coloc, qc)
    plot_residual_outliers(coloc)
    plot_station_map(coloc, era5)
    plot_coverage(coloc, era5)

    write_report_notes(coloc, metrics)

    print()
    print("=" * 80)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("Figures:", FIG_DIR.resolve())
    print("Tables :", TABLE_DIR.resolve())
    print("Notes  :", (REPORT_DIR / "hadisd_era5_report_notes.md").resolve())
    print("=" * 80)


if __name__ == "__main__":
    main()
