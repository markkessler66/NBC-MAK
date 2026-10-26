"""Environmental sampling around a tropical cyclone.

A track and intensity forecast only becomes interpretable next to the
environment producing it, so this module samples the parameters forecasters
actually reason about — deep-layer vertical wind shear, sea-surface
temperature, mid-level humidity, outflow temperature, and the pressure/height
pattern that steers the system — at the storm's current centre, at every
official forecast point, and across a grid around the storm.

Winds, humidity and outflow temperature are averaged around a ring at
`RING_RADIUS_KM`, not read at the centre. This matters: sampled at the centre
of a hurricane, the 850 hPa "environmental" wind is the eyewall itself, and the
implied shear is nonsense (a Category 4 reads ~40 kt of shear it does not
have). Vector-averaging around a closed ring cancels the storm's own
axisymmetric circulation and leaves the environmental flow, which is the same
reason SHIPS builds its predictors from a 200-800 km annulus.

Sources are GFS via Open-Meteo (upper air, MSLP, 500 hPa heights) and the
Open-Meteo marine feed (SST). These are global-model diagnostics sampled at the
storm, not NHC's own analysis; `services/tropical` turns them into categories
and prose.
"""
import asyncio
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..http_client import get_json
from ..util import iso, parse_iso_utc, round_hour, utcnow

log = logging.getLogger("weatherlab.tropical_env")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

WIND_LEVELS = ("850", "500", "200")

ENV_VARS = [
    "pressure_msl",
    "geopotential_height_500hPa",
    "wind_speed_850hPa", "wind_direction_850hPa",
    "wind_speed_500hPa", "wind_direction_500hPa",
    "wind_speed_200hPa", "wind_direction_200hPa",
    "relative_humidity_700hPa", "relative_humidity_500hPa",
    "temperature_850hPa", "temperature_200hPa",
]

MARINE_VARS = ["sea_surface_temperature", "wave_height"]

# Mass weights approximating the 850-200 hPa deep-layer mean from three levels,
# each standing in for the layer it sits nearest the middle of.
DLM_WEIGHTS = {"850": 0.30, "500": 0.40, "200": 0.30}

# Annulus used to strip the storm's own circulation out of the environment.
RING_RADIUS_KM = 500.0
RING_AZIMUTHS = 8

# Grid used to locate the surface high and nearest trough. Kept modest on
# purpose: Open-Meteo prices a request by locations x variables, and the
# steering direction itself comes free from the ring's height gradient.
GRID_HALF_STEPS = 3      # 7x7 points
GRID_STEP_DEG = 6.0
# The cyclone is itself the deepest low nearby, so height minima inside this
# radius are the storm, not a steering feature.
STORM_EXCLUSION_KM = 700.0

MAX_STOPS = 12
EARTH_RADIUS_KM = 6371.0

# Open-Meteo rate-limits by request weight; a storm needs a dozen samples and
# nothing here is latency critical, so cap how many are in flight at once.
_REQUESTS = asyncio.Semaphore(3)

# Open-Meteo's free tier bills one "call" per sampled location, and enforces
# three ceilings at once. Measured against the live API: 429s begin at roughly
# 600 locations in a minute, and separately once about 5,000 have gone out
# within the hour. A single map grid is a few hundred locations, so without
# pacing one careless refresh can exhaust the hour for the whole application —
# the dashboard models included. Callers wait for budget rather than fail,
# because a half-filled grid is worse than a slow one.
LOCATION_BUDGET_PER_MIN = 500
LOCATION_BUDGET_PER_HOUR = 4200
# The daily ceiling is the one that actually bites, and it is the least
# forgiving: exhausting it takes the environment layers out for the rest of the
# day rather than for a minute. Held below Open-Meteo's 10,000 so the dashboard
# models keep a working margin.
LOCATION_BUDGET_PER_DAY = 7000


class _LocationBudget:
    """Token bucket over sampled locations, shared by every Open-Meteo caller."""

    def __init__(self, capacity: int, per_seconds: float):
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._rate = capacity / per_seconds
        self._updated = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    def wait_for(self, count: int) -> float:
        """Seconds until `count` tokens are available, without consuming them."""
        self._refill()
        want = min(float(count), self._capacity)
        return 0.0 if self._tokens >= want else (want - self._tokens) / self._rate

    def remaining(self) -> float:
        self._refill()
        return self._tokens

    def empty(self) -> None:
        self._refill()
        self._tokens = 0.0

    def spend(self, count: int) -> None:
        self._tokens -= min(float(count), self._capacity)


# Waiting out a minute of throttling is reasonable; waiting out a spent daily
# quota is not, so past this point callers are told no and can say so in the UI.
MAX_BUDGET_WAIT_S = 120.0


class BudgetExhausted(RuntimeError):
    """Raised when a request cannot be funded within a sensible wait."""


def _refusal_text(body: str) -> str:
    """Open-Meteo's prose reason, unwrapped from its JSON error envelope."""
    try:
        reason = json.loads(body).get("reason")
    except (ValueError, AttributeError):
        reason = None
    return str(reason or body).strip().rstrip(".")[:160] or "quota exhausted"


class _BudgetSet:
    """Enforces the minutely, hourly and daily ceilings together."""

    def __init__(self) -> None:
        self._buckets = (
            _LocationBudget(LOCATION_BUDGET_PER_MIN, 60.0),
            _LocationBudget(LOCATION_BUDGET_PER_HOUR, 3600.0),
            _LocationBudget(LOCATION_BUDGET_PER_DAY, 86400.0),
        )
        self._lock = asyncio.Lock()
        self._closed_until: datetime | None = None
        self._closed_reason = ""

    async def take(self, count: int) -> None:
        if self._closed_until and utcnow() < self._closed_until:
            raise BudgetExhausted(
                f"{self._closed_reason} — resets {iso(self._closed_until)}")

        async with self._lock:
            while True:
                delay = max(b.wait_for(count) for b in self._buckets)
                if delay <= 0:
                    for bucket in self._buckets:
                        bucket.spend(count)
                    return
                if delay > MAX_BUDGET_WAIT_S:
                    raise BudgetExhausted(
                        f"{count} locations would need a {delay / 60:.0f} min wait "
                        "against the Open-Meteo quota")
                if delay > 5:
                    log.info("Open-Meteo budget: waiting %.0fs for %d locations",
                             delay, count)
                await asyncio.sleep(min(delay, 30.0))

    def drain(self, reason: str) -> None:
        """Shut the door until upstream's counter actually rolls over.

        A spent quota is a scheduled event, not a slow leak. Letting the token
        bucket dribble back instead would make every later request sit through a
        multi-minute wait for a handful of locations, which reads as a hung page
        rather than an unavailable layer.
        """
        lowered = reason.lower()
        now = utcnow()
        if "dai" in lowered:
            index, until = 2, (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
        elif "hour" in lowered:
            index, until = 1, (now + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0)
        else:
            index, until = 0, now + timedelta(seconds=60)

        self._buckets[index].empty()
        self._closed_until = until
        self._closed_reason = _refusal_text(reason)
        log.warning("Open-Meteo refused the request (%s); pausing until %s",
                    self._closed_reason, iso(until))

    def snapshot(self) -> dict:
        """Remaining headroom, for status reporting."""
        names = ("minute", "hour", "day")
        out: dict = {name: int(max(0.0, bucket.remaining()))
                     for name, bucket in zip(names, self._buckets)}
        if self._closed_until and utcnow() < self._closed_until:
            out["paused_until"] = iso(self._closed_until)
            out["paused_reason"] = self._closed_reason
        return out


_BUDGET = _BudgetSet()


def budget_snapshot() -> dict:
    """Locations still spendable against each Open-Meteo ceiling."""
    return _BUDGET.snapshot()


# ---- geometry ----------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees true."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination(lat: float, lon: float, bearing: float, distance_km: float) -> tuple[float, float]:
    """Point reached by travelling `distance_km` along `bearing` from a position."""
    angular = distance_km / EARTH_RADIUS_KM
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(angular)
                   + math.cos(p1) * math.sin(angular) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(angular) * math.cos(p1),
                         math.cos(angular) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg: float | None) -> str | None:
    if deg is None:
        return None
    return COMPASS_16[round(deg / 22.5) % 16]


# ---- wind vectors ------------------------------------------------------------

def wind_uv(speed: float | None, from_deg: float | None) -> tuple[float, float] | None:
    """Vector components from a meteorological (blowing-from) direction."""
    if speed is None or from_deg is None:
        return None
    rad = math.radians(from_deg)
    return -speed * math.sin(rad), -speed * math.cos(rad)


def uv_to_speed_from(u: float, v: float) -> tuple[float, float]:
    """Vector components -> (speed, blowing-from direction)."""
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360) % 360


def toward(from_deg: float | None) -> float | None:
    """Flip a blowing-from direction into the direction air/steering is headed."""
    return None if from_deg is None else (from_deg + 180) % 360


def angular_diff(a: float | None, b: float | None) -> float | None:
    """Smallest absolute angle between two headings, 0-180."""
    if a is None or b is None:
        return None
    return abs((a - b + 180) % 360 - 180)


# ---- Open-Meteo plumbing ----------------------------------------------------

async def _fetch_series(url: str, coords: list[tuple[float, float]],
                        hourly: list[str], **extra) -> list[dict]:
    """One request for many points; Open-Meteo returns a list when given several."""
    params = {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in coords),
        "longitude": ",".join(f"{lon:.4f}" for _, lon in coords),
        "hourly": ",".join(hourly),
        **extra,
    }
    await _BUDGET.take(len(coords))
    try:
        async with _REQUESTS:
            doc = await get_json(url, params=params, retries=3)
    except httpx.HTTPStatusError as exc:
        # Our own buckets reset on restart while Open-Meteo's counters do not, so
        # a 429 is the only reliable signal that the real quota is gone. Drain
        # the local budget to match rather than retrying into a wall.
        if exc.response is not None and exc.response.status_code == 429:
            _BUDGET.drain(exc.response.text)
            raise BudgetExhausted(_refusal_text(exc.response.text)) from exc
        raise
    return doc if isinstance(doc, list) else [doc]


def _times(series: dict) -> list[datetime]:
    return [
        datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        for t in series.get("hourly", {}).get("time", [])
    ]


def _nearest_index(times: list[datetime], target: datetime) -> int | None:
    if not times:
        return None
    return min(range(len(times)), key=lambda i: abs((times[i] - target).total_seconds()))


def _at(series: dict | None, var: str, index: int | None) -> float | None:
    if series is None or index is None:
        return None
    values = series.get("hourly", {}).get(var)
    if not values or index >= len(values):
        return None
    return values[index]


# ---- ring averages -----------------------------------------------------------

def _ring_vector_mean(ring: list[dict], level: str) -> dict:
    """Vector-mean wind at one level around the annulus (vortex removed)."""
    us, vs = [], []
    for point in ring:
        uv = wind_uv(_at(point, f"wind_speed_{level}hPa", 0),
                     _at(point, f"wind_direction_{level}hPa", 0))
        if uv:
            us.append(uv[0])
            vs.append(uv[1])
    if not us:
        return {"speed_kt": None, "from_deg": None, "toward_deg": None, "toward_compass": None}
    u, v = sum(us) / len(us), sum(vs) / len(vs)
    speed, from_deg = uv_to_speed_from(u, v)
    return {
        "speed_kt": round(speed, 1),
        "from_deg": round(from_deg),
        "toward_deg": round(toward(from_deg)),
        "toward_compass": compass(toward(from_deg)),
        "u": u,
        "v": v,
    }


def _ring_scalar_mean(ring: list[dict], var: str) -> float | None:
    values = [v for v in (_at(point, var, 0) for point in ring) if v is not None]
    return sum(values) / len(values) if values else None


def _ring_gradient(ring: list[dict], var: str) -> dict | None:
    """Least-squares horizontal gradient of a field around the ring.

    With the samples evenly spaced in azimuth the normal equations collapse to
    a pair of sums, so this is just the projection of the ring values onto the
    east and north directions. The bearing it returns points up-gradient, which
    for 500 hPa height is the direction of the ridge — the steering feature
    most often asked about, and it comes free from a ring already fetched.
    """
    east = north = 0.0
    used = 0
    for i, point in enumerate(ring):
        value = _at(point, var, 0)
        if value is None:
            continue
        azimuth = math.radians(i * 360 / len(ring))
        east += value * math.sin(azimuth)
        north += value * math.cos(azimuth)
        used += 1
    if used < 4:
        return None
    scale = 2.0 / used / RING_RADIUS_KM
    d_east, d_north = east * scale, north * scale
    magnitude = math.hypot(d_east, d_north)
    if magnitude == 0:
        return None
    bearing = (math.degrees(math.atan2(d_east, d_north)) + 360) % 360
    return {
        "toward_higher_deg": round(bearing),
        "toward_higher_compass": compass(bearing),
        "per_1000km": round(magnitude * 1000, 1),
    }


def _round(value: float | None, digits: int = 1):
    if value is None:
        return None
    return round(value, digits) if digits else round(value)


def _diagnose_stop(center: dict | None, ring: list[dict]) -> dict:
    """Shear, steering and thermodynamics for one position and time.

    SST comes from the marine feed and is merged in by the caller.
    """
    flow = {level: _ring_vector_mean(ring, level) for level in WIND_LEVELS}

    shear = None
    if flow["850"].get("u") is not None and flow["200"].get("u") is not None:
        du = flow["200"]["u"] - flow["850"]["u"]
        dv = flow["200"]["v"] - flow["850"]["v"]
        # The shear vector points downshear: where convection gets displaced.
        downshear = (math.degrees(math.atan2(du, dv)) + 360) % 360
        shear = {
            "magnitude_kt": round(math.hypot(du, dv), 1),
            "toward_deg": round(downshear),
            "toward_compass": compass(downshear),
        }

    steering = None
    weighted = [(DLM_WEIGHTS[lvl], flow[lvl]) for lvl in WIND_LEVELS]
    if all(f.get("u") is not None for _, f in weighted):
        total = sum(w for w, _ in weighted)
        u = sum(w * f["u"] for w, f in weighted) / total
        v = sum(w * f["v"] for w, f in weighted) / total
        speed, from_deg = uv_to_speed_from(u, v)
        steering = {
            "speed_kt": round(speed, 1),
            "from_deg": round(from_deg),
            "toward_deg": round(toward(from_deg)),
            "toward_compass": compass(toward(from_deg)),
        }

    environmental_mslp = _ring_scalar_mean(ring, "pressure_msl")
    central_mslp = _at(center, "pressure_msl", 0)

    return {
        "shear": shear,
        "steering": steering,
        "flow": {level: {k: v for k, v in flow[level].items() if k not in ("u", "v")}
                 for level in WIND_LEVELS},
        "rh_700_pct": _round(_ring_scalar_mean(ring, "relative_humidity_700hPa"), 0),
        "rh_500_pct": _round(_ring_scalar_mean(ring, "relative_humidity_500hPa"), 0),
        "outflow_temp_c": _round(_ring_scalar_mean(ring, "temperature_200hPa")),
        "temp_850_c": _round(_ring_scalar_mean(ring, "temperature_850hPa")),
        "environmental_pressure_mb": _round(environmental_mslp),
        "model_central_pressure_mb": _round(central_mslp),
        "model_pressure_deficit_mb": (
            _round(environmental_mslp - central_mslp)
            if environmental_mslp is not None and central_mslp is not None else None),
        "height_500_m": _round(_ring_scalar_mean(ring, "geopotential_height_500hPa"), 0),
        "height_500_gradient": _ring_gradient(ring, "geopotential_height_500hPa"),
        "pressure_gradient": _ring_gradient(ring, "pressure_msl"),
    }


# ---- pressure / height pattern ----------------------------------------------

def _grid_coords(lat: float, lon: float) -> list[tuple[float, float, bool]]:
    """Roughly square grid in kilometres, centred on the storm.

    The third element flags boundary points: an extremum found there means the
    real centre lies outside the sampled area, so it must be reported as a
    gradient direction rather than a located feature.
    """
    dlon = GRID_STEP_DEG / max(0.35, math.cos(math.radians(lat)))
    coords = []
    for i in range(-GRID_HALF_STEPS, GRID_HALF_STEPS + 1):
        for j in range(-GRID_HALF_STEPS, GRID_HALF_STEPS + 1):
            glat = max(-85.0, min(85.0, lat + i * GRID_STEP_DEG))
            glon = (lon + j * dlon + 180) % 360 - 180
            on_edge = abs(i) == GRID_HALF_STEPS or abs(j) == GRID_HALF_STEPS
            coords.append((glat, glon, on_edge))
    return coords


async def _sample_pattern(lat: float, lon: float, when: datetime) -> dict | None:
    """Locate the surface high, mid-level ridge, and mid-level trough near the storm."""
    coords = _grid_coords(lat, lon)
    try:
        series = await _fetch_series(
            FORECAST_URL, [(a, b) for a, b, _ in coords],
            ["pressure_msl", "geopotential_height_500hPa"],
            models="gfs_global",
            start_hour=_hour_param(when), end_hour=_hour_param(when),
        )
    except Exception as exc:
        log.warning("pressure-pattern sampling failed: %s", exc)
        return None

    samples = []
    for (glat, glon, on_edge), point in zip(coords, series):
        pressure = _at(point, "pressure_msl", 0)
        height = _at(point, "geopotential_height_500hPa", 0)
        if pressure is None and height is None:
            continue
        samples.append({
            "lat": round(glat, 2),
            "lon": round(glon, 2),
            "pressure_mb": _round(pressure),
            "height_500_m": _round(height, 0),
            "distance_km": round(haversine_km(lat, lon, glat, glon)),
            "bearing_deg": round(bearing_deg(lat, lon, glat, glon)),
            "on_edge": on_edge,
        })
    if not samples:
        return None

    def _feature(candidates: list[dict], key: str, pick_max: bool) -> dict | None:
        usable = [s for s in candidates if s.get(key) is not None]
        if not usable:
            return None
        best = (max if pick_max else min)(usable, key=lambda s: s[key])
        return {**best, "bearing_compass": compass(best["bearing_deg"])}

    far = [s for s in samples if s["distance_km"] > STORM_EXCLUSION_KM]
    return {
        "grid_step_deg": GRID_STEP_DEG,
        "grid_extent_km": round(GRID_HALF_STEPS * GRID_STEP_DEG * 111.32),
        "exclusion_km": STORM_EXCLUSION_KM,
        "surface_high": _feature(samples, "pressure_mb", True),
        "mid_ridge": _feature(samples, "height_500_m", True),
        "mid_trough": _feature(far, "height_500_m", False),
        "surface_low": _feature(far, "pressure_mb", False),
        "samples": samples,
    }


# ---- entry point -------------------------------------------------------------

def _hour_param(when: datetime) -> str:
    return round_hour(when).strftime("%Y-%m-%dT%H:%M")


async def _sample_stop(stop: dict) -> dict:
    """Centre + annulus sample for a single position and valid time."""
    lat, lon = stop["lat"], stop["lon"]
    ring_coords = [destination(lat, lon, i * 360 / RING_AZIMUTHS, RING_RADIUS_KM)
                   for i in range(RING_AZIMUTHS)]
    when = parse_iso_utc(stop["valid_time"])
    try:
        series = await _fetch_series(
            FORECAST_URL, [(lat, lon), *ring_coords], ENV_VARS,
            models="gfs_global", wind_speed_unit="kn",
            start_hour=_hour_param(when), end_hour=_hour_param(when),
        )
    except Exception as exc:
        log.warning("environment sampling at %+.1f/%+.1f failed: %s", lat, lon, exc)
        # Keep the shape so consumers never have to test for missing keys.
        return _diagnose_stop(None, [])
    return _diagnose_stop(series[0], series[1:])


async def sample_environment(storm: dict, track_points: list[dict] | None) -> dict:
    """Environmental diagnostics now and at each official forecast point."""
    now = utcnow()
    lat, lon = storm.get("lat"), storm.get("lon")
    if lat is None or lon is None:
        raise ValueError("storm has no position to sample")

    # Guard against an advisory NHC stopped updating: don't ask for hours the
    # forecast feed no longer carries.
    floor = now - timedelta(hours=36)
    stops: list[dict] = [{"fcst_hour": 0, "lat": lat, "lon": lon, "valid_time": iso(now),
                          "nhc_wind_kt": storm.get("intensity_kt")}]
    for point in (track_points or []):
        if point["fcst_hour"] == 0 or point["lat"] is None or point["lon"] is None:
            continue
        valid = parse_iso_utc(point["valid_time"]) if point.get("valid_time") else now
        stops.append({
            "fcst_hour": point["fcst_hour"],
            "lat": point["lat"],
            "lon": point["lon"],
            "valid_time": iso(max(valid, floor)),
            "nhc_wind_kt": point.get("wind_kt"),
            "nhc_stage": point.get("stage"),
        })
    stops = stops[:MAX_STOPS]  # 5-day advisories publish at most nine points
    centres = [(s["lat"], s["lon"]) for s in stops]

    async def _marine():
        try:
            return await _fetch_series(MARINE_URL, centres, MARINE_VARS, forecast_days=7)
        except Exception as exc:
            log.warning("marine SST sampling failed: %s", exc)
            return None

    *samples, marine, pattern = await asyncio.gather(
        *(_sample_stop(stop) for stop in stops),
        _marine(),
        _sample_pattern(lat, lon, now),
    )

    along_track = []
    for i, (stop, sample) in enumerate(zip(stops, samples)):
        ocean = marine[i] if marine and i < len(marine) else None
        index = _nearest_index(_times(ocean), parse_iso_utc(stop["valid_time"])) if ocean else None
        sst = _at(ocean, "sea_surface_temperature", index)
        along_track.append({
            **stop,
            **sample,
            "sst_c": _round(sst),
            "sst_f": _round(sst * 9 / 5 + 32) if sst is not None else None,
            # The marine grid is ocean-only, so a missing SST is the land mask.
            "over_land": ocean is not None and sst is None,
            "wave_height_m": _round(_at(ocean, "wave_height", index)),
        })

    return {
        "computed_at": iso(now),
        "source": "GFS via Open-Meteo (upper air, MSLP, 500 hPa heights) + Open-Meteo marine SST",
        "method": (f"Winds, humidity and outflow temperature are vector/scalar means over "
                   f"{RING_AZIMUTHS} points on a {RING_RADIUS_KM:.0f} km ring around the centre, "
                   "which removes the storm's own circulation the way SHIPS' annulus averages do. "
                   "SST is read at the centre."),
        "ring_radius_km": RING_RADIUS_KM,
        "current": along_track[0],
        "along_track": along_track,
        "pattern": pattern,
    }
