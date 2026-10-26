"""Open-Meteo ingestion: deterministic model forecasts + GEFS ensemble.

Open-Meteo re-serves operational NOAA/ECMWF output (HRRR, GFS, IFS, AIFS, NBM)
as point time series, which is the pragmatic Phase-1 path before native
GRIB2/Zarr ingestion (spec Phase 2+).
"""
from ..config import OM_VARIABLE_MAP, ModelSpec, settings
from ..http_client import get_json
from ..util import iso, parse_iso_utc, quantile, utcnow

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

_UNIT_PARAMS = {
    "temperature_unit": "fahrenheit",
    "wind_speed_unit": "mph",
    "precipitation_unit": "inch",
    "timezone": "UTC",
}


async def fetch_model_series(spec: ModelSpec) -> dict:
    """Fetch one model's hourly point forecast and normalize to internal keys."""
    params = {
        "latitude": settings.home_lat,
        "longitude": settings.home_lon,
        "hourly": ",".join(OM_VARIABLE_MAP.keys()),
        "models": spec.om_model,
        "forecast_days": spec.forecast_days,
        **_UNIT_PARAMS,
    }
    data = await get_json(FORECAST_URL, params=params)
    hourly = data.get("hourly") or {}
    times = [iso(parse_iso_utc(t)) for t in hourly.get("time", [])]

    values: dict[str, list] = {}
    for om_name, key in OM_VARIABLE_MAP.items():
        col = hourly.get(om_name)
        if col is None or all(v is None for v in col):
            continue
        values[key] = col

    if not values:
        raise RuntimeError(f"Open-Meteo returned no data for model {spec.om_model}")

    return {
        "key": spec.key,
        "label": spec.label,
        "source": "open-meteo",
        "is_ai": spec.is_ai,
        "fetched_at": iso(utcnow()),
        "times": times,
        "values": values,
    }


ENSEMBLE_VARS = {
    "temperature_2m": "temp_f",
    "precipitation": "precip_in",
    "wind_speed_10m": "wind_mph",
}

PERCENTILES = {"p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90}


async def fetch_gefs_ensemble() -> dict:
    """Fetch GEFS members and reduce to per-hour percentile bands."""
    params = {
        "latitude": settings.home_lat,
        "longitude": settings.home_lon,
        "hourly": ",".join(ENSEMBLE_VARS.keys()),
        "models": "gfs025",
        "forecast_days": 10,
        **_UNIT_PARAMS,
    }
    data = await get_json(ENSEMBLE_URL, params=params)
    hourly = data.get("hourly") or {}
    times = [iso(parse_iso_utc(t)) for t in hourly.get("time", [])]
    n_hours = len(times)

    # Columns come back as e.g. temperature_2m, temperature_2m_member01, ...
    member_cols: dict[str, list[list]] = {v: [] for v in ENSEMBLE_VARS.values()}
    for col_name, col in hourly.items():
        if col_name == "time" or col is None:
            continue
        base = col_name.split("_member")[0]
        key = ENSEMBLE_VARS.get(base)
        if key is not None:
            member_cols[key].append(col)

    percentiles: dict[str, dict[str, list]] = {}
    member_count = 0
    for key, cols in member_cols.items():
        if not cols:
            continue
        member_count = max(member_count, len(cols))
        bands: dict[str, list] = {p: [] for p in PERCENTILES}
        for i in range(n_hours):
            vals = sorted(c[i] for c in cols if c[i] is not None)
            for p, q in PERCENTILES.items():
                bands[p].append(round(quantile(vals, q), 2) if vals else None)
        percentiles[key] = bands

    if not percentiles:
        raise RuntimeError("GEFS ensemble returned no usable members")

    return {
        "label": "GEFS (31-member)",
        "fetched_at": iso(utcnow()),
        "members": member_count,
        "times": times,
        "percentiles": percentiles,
    }
