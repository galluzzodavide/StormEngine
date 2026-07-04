# StormEngine

StormEngine is a research pipeline for **short-term, high-resolution weather forecasting over the Adriatic Sea**, with an initial focus on the northern Adriatic coast (Veneto, Friuli Venezia Giulia, Emilia-Romagna, Marche).

The project collects real-time observations from multiple regional weather networks, aggregates and quality-controls them against ERA5 reanalysis and HadISD station data, and uses the result to train a deep-learning downscaling model that turns sparse ground observations into dense, high-resolution forecast maps. A lightweight web demo visualizes live ship traffic and short-range weather forecasts on an interactive map of the upper Adriatic.

## How it fits together

```
Regional networks (ARPAE, ARPAM, ARPAV, DPC) ─┐
HadISD, MeteoHub, ERA5 reanalysis ────────────┼──▶ DataAggregation ──▶ modelML ──▶ demo
                                               ┘   (clean, co-locate,   (Encoder →   (live map:
                                                    QC, aggregate)      Processor →   ships + forecast)
                                                                        Decoder)
```

1. **Collectors** (`ARPAE_emilia/`, `ARPAM_marche/`, `ARPAV_veneto/`, `DPC_friuli/`, `HadISD_Adriatic/`, `MeteoHub_Adriatic/`, `era5_data.py`) pull raw observation/reanalysis data from public sources and normalize it into a common CSV schema (`station_id, sensor_code, dt, value, lat, lon, ...`).
2. **`DataAggregation/`** merges, cleans, and cross-validates those sources: co-locating station data with the nearest ERA5 grid points, running data-quality checks, and producing the aggregated datasets used for model training.
3. **`modelML/`** implements the forecasting model itself, a three-stage pipeline that turns irregular point observations into a gridded, high-resolution forecast.
4. **`demo/`** is a small Flask web application showing the practical use case: live AIS ship positions over the northern Adriatic with an overlaid short-range weather forecast.

## Repository structure

| Folder / File | Purpose |
|---|---|
| `ARPAE_emilia/` | Scraper (`ARPAE_emilia.py`) for real-time weather observations from **ARPAE** (Emilia-Romagna), filtered to the coastal area. Outputs `ARPAE_coastal_latest.csv`. |
| `ARPAM_marche/` | Scraper (`meteohub.py`) for real physical station sensors from **MeteoHub** (Agenzia ItaliaMeteo + Cineca) along the Marche coast. Outputs `ARPAM_coastal_latest.csv`. |
| `ARPAV_veneto/` | Scraper (`ARPAV-veneto.py`) for real-time station data (temperature, precipitation, humidity, wind, pressure, radiation) from **ARPAV** (Veneto), via its public JSON APIs. Outputs `ARPAV_latest.csv`. |
| `DPC_friuli/` | Scraper (`DPC-friuli.py`) for real-time station data from the **Protezione Civile FVG** (Friuli Venezia Giulia) monitoring network. Outputs `DPC_latest.csv`. |
| `HadISD_Adriatic/` | Downloads and processes **HadISD** (Met Office) integrated surface station data for the Adriatic region (sea-level pressure, wind, temperature) for the full year 2024, reformatted to match the ARPA station schema. |
| `MeteoHub_Adriatic/` | Raw and aggregated station observations pulled from **MeteoHub** for the whole Adriatic coast, plus a notebook that collapses the long-format readings into one row per station with the latest value per variable. |
| `era5_data.py` | Downloads **ERA5** and **ERA5-Land** reanalysis data (temperature, precipitation, mean sea-level pressure, wind, gusts) over the Adriatic domain from the Copernicus Climate Data Store, month by month for a full year. |
| `DataAggregation/` | Notebooks that merge and quality-control all data sources before model training. See breakdown below. |
| `DataAggregation/DPC/` | Merges the regional network CSVs (DPC, ARPAE, ARPAV, ...) into a single, per-station aggregated and flagged dataset, with an accompanying data dictionary and QC plots. |
| `DataAggregation/ERA5/` | Data-quality assessment of the monthly ERA5 grid files before they are fed to the model. |
| `DataAggregation/HadISD/` | Full pipeline co-locating ERA5 with HadISD stations, analyzing seasonal bias, and running HadISD data-quality checks. |
| `DataAggregation/Colocation/` | Co-locates ERA5 grid values with DPC station coordinates via bilinear interpolation, for direct model/observation comparison. |
| `DataAggregation/Seasonality_ERA5/` | Seasonal analysis of ERA5 reanalysis variables over the full year. |
| `modelML/` | The forecasting model, split into three stages: **Encoder** (SetConv — converts sparse station data into a gridded representation), **Processor** (spatio-temporal model consuming the gridded representation), and **Decoder** (U-Net — upsamples coarse predictions into 1 km-resolution forecast maps). |
| `demo/` | Flask web app (`app.py`) serving an interactive map (`templates/`, `static/`) with live AIS ship tracking (`ais_worker.py`) and a cached Open-Meteo forecast overlay for the upper Adriatic. |
| `stations_map.ipynb` | Notebook that plots all collected weather stations from every network on an interactive map for a quick visual sanity check of spatial coverage. |

## Data sources

- [ARPAE Emilia-Romagna](https://dati-simc.arpae.it/) — real-time meteo observations
- [ARPAV Veneto](https://api.arpa.veneto.it/) — real-time meteo observations
- [Protezione Civile FVG](https://monitor.protezionecivile.fvg.it/) — real-time meteo observations
- [MeteoHub (ItaliaMeteo / Cineca)](https://meteohub.agenziaitaliameteo.it/) — real physical station sensors
- [HadISD](https://www.metoffice.gov.uk/hadobs/hadisd/) (Met Office) — integrated surface station archive
- [ERA5 / ERA5-Land](https://cds.climate.copernicus.eu/) (Copernicus Climate Data Store) — atmospheric reanalysis
- [Open-Meteo](https://open-meteo.com/) — forecast overlay used in the demo
- AIS ship-tracking feed — used in the demo for live vessel positions

## Getting started

The scrapers and notebooks depend on standard scientific Python packages: `pandas`, `numpy`, `xarray`, `requests`, `cdsapi`, `folium`, `torch`, and `flask`. Install what you need for the part of the pipeline you're running, e.g.:

```bash
pip install pandas numpy xarray requests cdsapi folium torch flask websockets
```

Each collector script can be run standalone, e.g.:

```bash
python ARPAV_veneto/ARPAV-veneto.py
```

To run the live demo:

```bash
cd demo
python app.py
```

> **Note:** `era5_data.py` requires valid Copernicus CDS credentials, and `ARPAM_marche/meteohub.py` requires MeteoHub credentials set as environment variables (`MH_USERNAME`, `MH_PASSWORD`) — see the script header for details.
