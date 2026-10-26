"""NWS API ingestion: point metadata, observations, hourly forecast, alerts."""
import re

from ..config import settings
from ..http_client import get_json
from ..state import LATEST
from ..units import c_to_f, kmh_to_mph, m_to_mi, mm_to_in, pa_to_mb
from ..util import iso, parse_iso_utc, utcnow

API = "https://api.weather.gov"


async def resolve_point() -> dict:
    """Resolve and cache gridpoint/station metadata for the home location."""
    if LATEST.nws_point:
        return LATEST.nws_point
    data = await get_json(f"{API}/points/{settings.home_lat:.4f},{settings.home_lon:.4f}")
    props = data["properties"]

    stations_doc = await get_json(props["observationStations"])
    station_ids = [
        s["properties"]["stationIdentifier"]
        for s in stations_doc.get("features", [])[:5]
    ]

    LATEST.nws_point = {
        "grid_id": props["gridId"],
        "grid_x": props["gridX"],
        "grid_y": props["gridY"],
        "forecast_hourly_url": props["forecastHourly"],
        "forecast_url": props["forecast"],
        "stations": station_ids,
        "county": (props.get("county") or "").split("/")[-1],
        "zone": (props.get("forecastZone") or "").split("/")[-1],
        "city": props.get("relativeLocation", {}).get("properties", {}).get("city"),
    }
    return LATEST.nws_point


def _v(field: dict | None):
    """Extract .value from an NWS quantitative field."""
    return None if field is None else field.get("value")


async def fetch_observation() -> dict:
    """Latest surface observation from the nearest station reporting temperature."""
    point = await resolve_point()
    last_error = "no stations available"
    for station in point["stations"][:4]:
        try:
            doc = await get_json(f"{API}/stations/{station}/observations/latest", retries=1)
        except Exception as exc:  # station may be missing/stale; try the next one
            last_error = str(exc)
            continue
        p = doc.get("properties", {})
        temp_c = _v(p.get("temperature"))
        if temp_c is None:
            continue

        heat_index = c_to_f(_v(p.get("heatIndex")))
        wind_chill = c_to_f(_v(p.get("windChill")))
        temp_f = c_to_f(temp_c)
        clouds = p.get("cloudLayers") or []
        rh = _v(p.get("relativeHumidity"))
        return {
            "station": station,
            "obs_time": iso(parse_iso_utc(p["timestamp"])),
            "fetched_at": iso(utcnow()),
            "description": p.get("textDescription") or "",
            "temp_f": temp_f,
            "feels_like_f": heat_index or wind_chill or temp_f,
            "dewpoint_f": c_to_f(_v(p.get("dewpoint"))),
            "rh": round(rh, 0) if rh is not None else None,
            "wind_mph": kmh_to_mph(_v(p.get("windSpeed"))),
            "wind_dir_deg": _v(p.get("windDirection")),
            "gust_mph": kmh_to_mph(_v(p.get("windGust"))),
            "pressure_mb": pa_to_mb(_v(p.get("seaLevelPressure")) or _v(p.get("barometricPressure"))),
            "visibility_mi": m_to_mi(_v(p.get("visibility"))),
            "precip_last_hour_in": mm_to_in(_v(p.get("precipitationLastHour"))),
            "cloud_layer": clouds[0]["amount"] if clouds else None,
        }
    raise RuntimeError(f"No station produced a usable observation ({last_error})")


_WIND_RE = re.compile(r"(\d+)")


def _parse_wind_mph(text: str | None) -> float | None:
    """NWS wind is text like '10 mph' or '5 to 15 mph'; take the upper bound."""
    if not text:
        return None
    nums = _WIND_RE.findall(text)
    return float(nums[-1]) if nums else None


async def fetch_hourly_forecast() -> dict:
    """Official NWS gridpoint hourly forecast, shaped like a model series."""
    point = await resolve_point()
    doc = await get_json(point["forecast_hourly_url"], params={"units": "us"})
    periods = doc["properties"]["periods"]

    times, temp, dewpoint, rh, pop, wind, wind_dir, short = [], [], [], [], [], [], [], []
    for per in periods:
        times.append(iso(parse_iso_utc(per["startTime"])))
        temp.append(per.get("temperature"))
        dp_c = _v(per.get("dewpoint"))
        dewpoint.append(c_to_f(dp_c))
        rh.append(_v(per.get("relativeHumidity")))
        pop.append(_v(per.get("probabilityOfPrecipitation")))
        wind.append(_parse_wind_mph(per.get("windSpeed")))
        wind_dir.append(per.get("windDirection"))
        short.append(per.get("shortForecast"))

    return {
        "key": "nws",
        "label": "NWS Forecast",
        "source": "nws",
        "is_ai": False,
        "fetched_at": iso(utcnow()),
        "times": times,
        "values": {
            "temp_f": temp,
            "dewpoint_f": dewpoint,
            "rh": rh,
            "precip_prob": pop,
            "wind_mph": wind,
        },
        "extra": {"wind_dir_text": wind_dir, "short_forecast": short},
    }


async def fetch_alerts() -> list[dict]:
    """Active NWS alerts for the home point."""
    doc = await get_json(
        f"{API}/alerts/active",
        params={"point": f"{settings.home_lat:.4f},{settings.home_lon:.4f}"},
    )
    alerts = []
    for feat in doc.get("features", []):
        p = feat.get("properties", {})
        alerts.append({
            "id": p.get("id"),
            "event": p.get("event"),
            "severity": p.get("severity"),
            "urgency": p.get("urgency"),
            "headline": p.get("headline"),
            "onset": p.get("onset"),
            "ends": p.get("ends") or p.get("expires"),
            "area": p.get("areaDesc"),
            "description": (p.get("description") or "")[:1500],
            "instruction": (p.get("instruction") or "")[:800],
        })
    return alerts
