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

```
StormEngine/
├── README.md
├── era5_data.py                    ← downloads ERA5 / ERA5-Land reanalysis (Copernicus CDS)
├── stations_map.ipynb              ← plots all collected stations on one map
│
├── ARPAE_emilia/                   ← ARPAE (Emilia-Romagna) real-time scraper
│   ├── ARPAE_emilia.py
│   └── ARPAE_coastal_latest.csv
│
├── ARPAM_marche/                   ← MeteoHub (Marche) real-time scraper
│   ├── meteohub.py
│   └── ARPAM_coastal_latest.csv
│
├── ARPAV_veneto/                   ← ARPAV (Veneto) real-time scraper
│   ├── ARPAV-veneto.py
│   └── ARPAV_latest.csv
│
├── DPC_friuli/                     ← Protezione Civile FVG real-time scraper
│   ├── DPC-friuli.py
│   └── DPC_latest.csv
│
├── HadISD_Adriatic/                ← HadISD (Met Office) station archive downloader
│   ├── hadisd_adriatic.py
│   └── adriatic_stations.csv
│
├── MeteoHub_Adriatic/              ← MeteoHub bulk station data + aggregation
│   ├── adriatic_coast_stations.csv
│   ├── adriatic_coast_stations_aggregated.csv
│   └── aggregate_meteohub_stations.ipynb
│
├── DataAggregation/                ← merge, co-locate & quality-control all sources
│   ├── DPC/                        ← merges regional network CSVs into one dataset
│   ├── ERA5/                       ← ERA5 grid data-quality checks
│   ├── HadISD/                     ← ERA5 x HadISD co-location & bias analysis
│   ├── Colocation/                 ← ERA5 x DPC station co-location
│   └── Seasonality_ERA5/           ← seasonal analysis of ERA5 variables
│
├── modelML/                        ← forecasting model: Encoder → Processor → Decoder
│   ├── 01_encoder_setconv.ipynb    ← Stage 1: SetConv encoder (sparse → gridded)
│   ├── Processor.ipynb             ← Stage 2: spatio-temporal processor
│   └── Decoder.ipynb               ← Stage 3: U-Net decoder (high-res forecast)
│
└── demo/                           ← live demo: ships + forecast on a map
    ├── app.py                      ← Flask server + Open-Meteo forecast proxy
    ├── ais_worker.py               ← live AIS ship-tracking listener
    ├── templates/                  ← HTML page
    └── static/                     ← front-end JS (map, UI)
```

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
