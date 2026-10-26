"""NHC tropical ingestion: active storms, forecast cones/tracks, basin outlooks."""
import asyncio
import logging

from ..http_client import get_bytes, get_json
from ..units import kt_to_mph
from ..util import iso, utcnow
from . import nhc_gis

log = logging.getLogger("weatherlab.nhc")

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"

CLASSIFICATIONS = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "HU": "Hurricane",
    "MH": "Major Hurricane",
    "STD": "Subtropical Depression",
    "STS": "Subtropical Storm",
    "PTC": "Potential Tropical Cyclone",
    "PC": "Post-tropical Cyclone",
    "DB": "Disturbance",
    "LO": "Low",
    "EX": "Extratropical Cyclone",
    "WV": "Tropical Wave",
}

BASINS = {"al": "Atlantic", "ep": "East Pacific", "cp": "Central Pacific"}

# Static NHC graphical outlook products (updated in place by NHC). NHC blocks
# browser hotlinking, so the frontend loads them through our /api proxy.
OUTLOOKS = [
    {"basin": "Atlantic", "label": "7-Day Tropical Weather Outlook",
     "image": "/api/tropical/outlook/0.png",
     "source_image": "https://www.nhc.noaa.gov/xgtwo/two_atl_7d0.png",
     "link": "https://www.nhc.noaa.gov/gtwo.php?basin=atlc"},
    {"basin": "Atlantic", "label": "2-Day Tropical Weather Outlook",
     "image": "/api/tropical/outlook/1.png",
     "source_image": "https://www.nhc.noaa.gov/xgtwo/two_atl_2d0.png",
     "link": "https://www.nhc.noaa.gov/gtwo.php?basin=atlc"},
]


def _num(value) -> float | None:
    """NHC serves numbers inconsistently (strings vs numerics); normalize."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _storm_priority(storm: dict) -> int:
    order = ["MH", "HU", "TS", "STS", "TD", "STD", "PTC", "PC", "DB", "LO", "WV", "EX"]
    code = storm.get("classification") or "LO"
    return order.index(code) if code in order else len(order)


async def _fetch_geometry(storm: dict) -> None:
    """Attach the cone of uncertainty and official forecast track to a storm.

    Best-effort per product: NHC occasionally publishes a storm before its GIS
    assets land, and a missing cone must not cost us the position feed.
    """
    async def _load(url: str | None, parser, field: str):
        if not url:
            return
        try:
            storm[field] = parser(await get_bytes(url))
        except Exception as exc:
            log.warning("NHC %s for %s failed: %s", field, storm.get("id"), exc)

    await asyncio.gather(
        _load(storm.pop("_cone_kmz", None), nhc_gis.parse_cone_kmz, "cone"),
        _load(storm.pop("_track_kmz", None), nhc_gis.parse_track_kmz, "track"),
    )


async def fetch_tropical() -> dict:
    doc = await get_json(CURRENT_STORMS_URL)
    storms = []
    for s in doc.get("activeStorms", []):
        code = s.get("classification")
        intensity_kt = _num(s.get("intensity"))
        storm_id = (s.get("id") or "").lower()
        storms.append({
            "id": s.get("id"),
            "bin": s.get("binNumber"),
            "name": s.get("name"),
            "classification": code,
            "classification_label": CLASSIFICATIONS.get(code, code or "Unknown"),
            "basin": BASINS.get(storm_id[:2], "Unknown"),
            "lat": _num(s.get("latitudeNumeric")),
            "lon": _num(s.get("longitudeNumeric")),
            "intensity_kt": intensity_kt,
            "intensity_mph": kt_to_mph(intensity_kt),
            "category": nhc_gis.saffir_simpson(intensity_kt),
            "pressure_mb": _num(s.get("pressure")),
            "movement_dir_deg": _num(s.get("movementDir")),
            "movement_speed_kt": _num(s.get("movementSpeed")),
            "movement_speed_mph": kt_to_mph(_num(s.get("movementSpeed"))),
            "last_update": s.get("lastUpdate"),
            "advisory_num": (s.get("publicAdvisory") or {}).get("advNum"),
            "advisory_url": (s.get("publicAdvisory") or {}).get("url"),
            "advisory_issued": (s.get("publicAdvisory") or {}).get("issuance"),
            "forecast_advisory_url": (s.get("forecastAdvisory") or {}).get("url"),
            "discussion_url": (s.get("forecastDiscussion") or {}).get("url"),
            "wind_probabilities_url": (s.get("windSpeedProbabilities") or {}).get("url"),
            "graphics_url": (s.get("forecastGraphics") or {}).get("url"),
            "cone": None,
            "track": None,
            "_cone_kmz": (s.get("trackCone") or {}).get("kmzFile"),
            "_track_kmz": (s.get("forecastTrack") or {}).get("kmzFile"),
        })

    await asyncio.gather(*(_fetch_geometry(s) for s in storms))
    storms.sort(key=_storm_priority)
    return {
        "fetched_at": iso(utcnow()),
        "storms": storms,
        "atlantic_count": sum(1 for s in storms if s["basin"] == "Atlantic"),
        "outlooks": OUTLOOKS,
    }
