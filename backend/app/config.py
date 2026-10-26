"""Application configuration and the forecast-model registry."""
from dataclasses import dataclass, field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WLAB_", env_file=".env", extra="ignore")

    home_name: str = "Frisco, TX"
    home_lat: float = 33.1507
    home_lon: float = -96.8236
    home_tz: str = "America/Chicago"

    # SQLite by default; point at PostgreSQL via WLAB_DB_URL when ready.
    db_url: str = "sqlite:///./data/weatherlab.db"

    # NWS API requires a descriptive User-Agent.
    user_agent: str = "PersonalWeatherLab/0.1 (personal research project)"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # How far ahead (hours) point forecasts are archived for verification.
    archive_max_lead_hours: int = 192

    # Native NOAA GRIB2 ingestion (HRRR/GFS via NOMADS with regional subsetting).
    native_ingest: bool = True
    grid_dir: str = "./data/grids"
    grid_retention_days: int = 14
    # Regional subset box (North Texas) requested from the NOMADS GRIB filter.
    region_west: float = -99.5
    region_east: float = -94.0
    region_north: float = 35.0
    region_south: float = 30.5

    # Local GPU AI model (Phase 4): Pangu-Weather 24 h via ONNX Runtime.
    pangu_enabled: bool = True
    pangu_steps: int = 7          # autoregressive 24 h steps (7 days)
    poll_pangu: int = 3600        # new-cycle check interval (runs ~4x/day)

    # Polling intervals (seconds)
    poll_observations: int = 300
    poll_alerts: int = 300
    poll_models: int = 3600
    poll_native: int = 600  # new-cycle checks are cheap S3 HEAD probes
    poll_nws_forecast: int = 1800
    poll_ensemble: int = 7200
    poll_tropical: int = 1800
    # Storm environment sampling (shear/SST/steering) per active system. Each
    # pass costs a few hundred billed Open-Meteo locations per storm, and NHC
    # only issues advisories every 3-6 h, so polling faster buys nothing and
    # can exhaust the hourly quota the dashboard models also draw on. A new
    # advisory still invalidates the cache immediately when it appears.
    poll_tropical_detail: int = 10800


settings = Settings()


# Canonical hourly variables used across the whole system.
# Open-Meteo hourly field name -> internal key
OM_VARIABLE_MAP: dict[str, str] = {
    "temperature_2m": "temp_f",
    "dew_point_2m": "dewpoint_f",
    "relative_humidity_2m": "rh",
    "precipitation": "precip_in",
    "precipitation_probability": "precip_prob",
    "wind_speed_10m": "wind_mph",
    "wind_direction_10m": "wind_dir",
    "wind_gusts_10m": "gust_mph",
    "cloud_cover": "cloud_pct",
    "pressure_msl": "pressure_mb",
    "cape": "cape",
    "lifted_index": "lifted_index",
    "convective_inhibition": "cin",
}

# Variables included in API payloads / consensus / archive.
FORECAST_VARS = [
    "temp_f", "dewpoint_f", "rh", "precip_prob", "precip_in",
    "wind_mph", "gust_mph", "cloud_pct", "pressure_mb",
    "cape", "cin", "lifted_index",
]

# Subset persisted per (model, run, target-hour) for verification.
ARCHIVE_VARS = [
    "temp_f", "dewpoint_f", "rh", "precip_prob", "precip_in",
    "wind_mph", "gust_mph", "cloud_pct", "cape",
]

# Variables that can be verified against surface observations.
VERIFIABLE_VARS = ["temp_f", "dewpoint_f", "rh", "wind_mph", "gust_mph"]


@dataclass(frozen=True)
class ModelSpec:
    key: str                  # internal identifier
    label: str                # display name
    source: str               # "open-meteo" | "nws"
    om_model: str = ""        # Open-Meteo `models=` value
    forecast_days: int = 10
    is_ai: bool = False
    note: str = ""


MODELS: list[ModelSpec] = [
    ModelSpec("hrrr", "HRRR", "open-meteo", "gfs_hrrr", forecast_days=2,
              note="NOAA 3 km rapid-refresh, hourly updates, ~48 h range"),
    ModelSpec("gfs", "GFS", "open-meteo", "gfs_global", forecast_days=10,
              note="NOAA global model, 4 runs/day"),
    ModelSpec("ecmwf_ifs", "ECMWF IFS", "open-meteo", "ecmwf_ifs025", forecast_days=10,
              note="ECMWF physical global model, 0.25\u00b0 open data"),
    ModelSpec("ecmwf_aifs", "ECMWF AIFS", "open-meteo", "ecmwf_aifs025_single", forecast_days=10,
              is_ai=True, note="ECMWF data-driven AI model (AIFS Single)"),
    ModelSpec("nbm", "NWS NBM", "open-meteo", "ncep_nbm_conus", forecast_days=8,
              note="NWS National Blend of Models, CONUS"),
    ModelSpec("nws", "NWS Forecast", "nws", forecast_days=7,
              note="Official NWS gridpoint hourly forecast (FWD office)"),
    ModelSpec("pangu", "Pangu (local)", "local-ai", forecast_days=7, is_ai=True,
              note="Pangu-Weather 24 h ONNX model run locally on the GPU, "
                   "initialized from GFS analysis; daily resolution"),
]

MODELS_BY_KEY: dict[str, ModelSpec] = {m.key: m for m in MODELS}
