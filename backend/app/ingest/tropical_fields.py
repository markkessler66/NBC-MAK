"""Gridded environmental fields for map shading.

`tropical_env` answers "what is the environment doing *at the storm*"; this
module answers "what does it look like *around* the storm", on a regular
latitude/longitude grid the frontend can interpolate into a smooth overlay.

The grid is deliberately regular in degrees rather than square in kilometres:
a lat/lon mesh is what makes bilinear interpolation on a canvas trivial, and
these are synoptic-scale fields where a couple of degrees of spacing is far
finer than the features being shaded.

Unlike the storm-centred diagnostics, values here are the raw model fields —
no annulus averaging. Near the centre the shear field therefore includes the
model's own vortex, which is genuine in the GFS grid and is how operational
shear analyses render it too.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime

from ..util import iso, round_hour
from .tropical_env import (
    FORECAST_URL,
    MARINE_URL,
    BudgetExhausted,
    _fetch_series,
    _hour_param,
    compass,
    uv_to_speed_from,
    wind_uv,
)

log = logging.getLogger("weatherlab.tropical_fields")

FIELD_VARS = [
    "pressure_msl",
    "geopotential_height_500hPa",
    "wind_speed_850hPa", "wind_direction_850hPa",
    "wind_speed_500hPa", "wind_direction_500hPa",
    "wind_speed_200hPa", "wind_direction_200hPa",
    "relative_humidity_700hPa",
]

# Open-Meteo takes many coordinates per call but the URL is a query string, so
# keep each batch well inside anything that might trip a length or weight cap.
BATCH = 150
MAX_POINTS = 400

# Wide enough that a five-day cone still lands inside the shading, coarse
# enough that one grid stays well inside the minutely location budget. Every
# extra point is a billed API call, and these are synoptic fields where two
# degrees is already far finer than the features being shaded.
DEFAULT_HALF_SPAN_DEG = 14.0
DEFAULT_STEP_DEG = 2.0

# Padding around the forecast track. Enough that the five-day cone and the
# steering features either side of it are shaded, without spending points on
# ocean the storm will never see.
TRACK_MARGIN_DEG = 7.0

# Sea-surface temperature is a slowly varying boundary condition: over a
# five-day forecast it moves by a few tenths of a degree. Sampling it once per
# storm over the whole track and reusing it for every lead hour costs one
# request instead of one per hour, which is what keeps switching lead times
# inside the rate limit.
SST_STEP_DEG = 3.0
SST_TTL_SECONDS = 6 * 3600
_sst_cache: dict[str, tuple[float, dict]] = {}
_sst_locks: dict[str, asyncio.Lock] = {}

# Same thresholds the written diagnostics use, so the map and the prose agree.
SST_FLOOR_C = 26.5
SHEAR_LOW_KT = 10.0
SHEAR_HIGH_KT = 30.0
RH_DRY_PCT = 45.0
RH_MOIST_PCT = 70.0


def _axis(centre: float, half_span: float, step: float,
          lo: float, hi: float) -> list[float]:
    n = int(round(half_span / step))
    values = [centre + i * step for i in range(-n, n + 1)]
    return [v for v in values if lo <= v <= hi]


def build_grid(lat: float, lon: float,
               half_span_deg: float = DEFAULT_HALF_SPAN_DEG,
               step_deg: float = DEFAULT_STEP_DEG) -> tuple[list[float], list[float]]:
    """Latitude and longitude axes for a storm-centred box, clamped to sane limits."""
    lats = _axis(lat, half_span_deg, step_deg, -80.0, 80.0)
    lons = _axis(lon, half_span_deg, step_deg, -359.0, 359.0)
    # Coarsen rather than truncate if the box would be too many API points.
    while len(lats) * len(lons) > MAX_POINTS:
        lats = lats[::2]
        lons = lons[::2]
    return lats, lons


async def _fetch_batched(url: str, coords: list[tuple[float, float]],
                         hourly: list[str], **extra) -> list[dict | None]:
    """Fetch a long coordinate list in chunks, keeping order and tolerating gaps.

    Batches go out one at a time rather than all at once. A whole grid is a few
    hundred locations across nine variables, and firing every chunk in parallel
    is enough to trip Open-Meteo's rate limiter — which fails as a half-empty
    grid, so it is worth a second or two to stay under it.
    """
    batches = [coords[i:i + BATCH] for i in range(0, len(coords), BATCH)]
    out: list[dict | None] = []

    for batch in batches:
        for attempt in range(2):
            try:
                out.extend(await _fetch_series(url, batch, hourly, **extra))
                break
            except BudgetExhausted:
                # Not a transient failure: retrying burns the rest of the quota
                # and still returns nothing. Let the caller say so in the UI.
                raise
            except Exception as exc:
                if attempt == 0:
                    await asyncio.sleep(2.0)
                    continue
                log.warning("field batch of %d points failed: %s", len(batch), exc)
                out.extend([None] * len(batch))
    return out


def _value(point: dict | None, var: str, index: int = 0) -> float | None:
    if point is None or index < 0:
        return None
    values = point.get("hourly", {}).get(var)
    if not values or index >= len(values):
        return None
    return values[index]


def _time_indices(points: list[dict | None], times: list[datetime]) -> list[int]:
    """Position of each wanted valid time within the returned hourly series.

    Open-Meteo decides its own step, so the series is matched by timestamp
    rather than assumed to be one row per hour.
    """
    stamps: list[str] | None = None
    for point in points:
        candidate = (point or {}).get("hourly", {}).get("time")
        if candidate:
            stamps = candidate
            break
    if not stamps:
        return [-1] * len(times)

    lookup = {stamp[:13]: i for i, stamp in enumerate(stamps)}
    return [lookup.get(round_hour(when).strftime("%Y-%m-%dT%H"), -1) for when in times]


def _shear(point: dict | None, index: int = 0) -> tuple[float | None, float | None]:
    """Magnitude and downshear bearing of the 850-200 hPa vector difference."""
    low = wind_uv(_value(point, "wind_speed_850hPa", index),
                  _value(point, "wind_direction_850hPa", index))
    high = wind_uv(_value(point, "wind_speed_200hPa", index),
                   _value(point, "wind_direction_200hPa", index))
    if low is None or high is None:
        return None, None
    du, dv = high[0] - low[0], high[1] - low[1]
    return math.hypot(du, dv), (math.degrees(math.atan2(du, dv)) + 360) % 360


def _steering(point: dict | None, index: int = 0) -> tuple[float | None, float | None]:
    """Deep-layer mean flow speed and the direction it is steering toward."""
    weights = {"850": 0.30, "500": 0.40, "200": 0.30}
    u = v = total = 0.0
    for level, weight in weights.items():
        uv = wind_uv(_value(point, f"wind_speed_{level}hPa", index),
                     _value(point, f"wind_direction_{level}hPa", index))
        if uv is None:
            return None, None
        u += weight * uv[0]
        v += weight * uv[1]
        total += weight
    speed, from_deg = uv_to_speed_from(u / total, v / total)
    return speed, (from_deg + 180) % 360


def _favourability(sst: float | None, shear: float | None,
                   rh: float | None) -> float | None:
    """0-100 composite of the three ingredients that gate intensification.

    Capped by its weakest ingredient rather than averaged, matching how the
    written intensity verdict treats a limiting factor: cool water does not
    become survivable because the shear happens to be slack.
    """
    scores: list[float] = []
    if sst is not None:
        scores.append(max(0.0, min(1.0, (sst - 24.0) / 5.0)))
    if shear is not None:
        scores.append(max(0.0, min(1.0, (SHEAR_HIGH_KT - shear)
                                   / (SHEAR_HIGH_KT - SHEAR_LOW_KT))))
    if rh is not None:
        scores.append(max(0.0, min(1.0, (rh - RH_DRY_PCT) / (RH_MOIST_PCT - RH_DRY_PCT))))
    if len(scores) < 3:
        return None
    mean = sum(scores) / len(scores)
    return round(100 * min(mean, 0.5 * (mean + min(scores))), 1)


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits) if digits else round(value)


def _bilinear(lats: list[float], lons: list[float],
              grid: list[list[float | None]], lat: float, lon: float) -> float | None:
    """Sample a regular lat/lon grid, renormalising over whichever corners exist.

    Holes are the ocean model's land mask, so they are dropped from the weights
    rather than filled: a point ringed by land stays unknown instead of
    inheriting a temperature from across a peninsula.
    """
    if len(lats) < 2 or len(lons) < 2:
        return None
    d_lat = lats[1] - lats[0]
    d_lon = lons[1] - lons[0]
    fy = (lat - lats[0]) / d_lat
    fx = (lon - lons[0]) / d_lon
    if fy < -0.5 or fy > len(lats) - 0.5 or fx < -0.5 or fx > len(lons) - 0.5:
        return None

    y0 = max(0, min(len(lats) - 2, int(math.floor(fy))))
    x0 = max(0, min(len(lons) - 2, int(math.floor(fx))))
    ty = max(0.0, min(1.0, fy - y0))
    tx = max(0.0, min(1.0, fx - x0))

    total = weight = 0.0
    for y, x, w in ((y0, x0, (1 - ty) * (1 - tx)), (y0, x0 + 1, (1 - ty) * tx),
                    (y0 + 1, x0, ty * (1 - tx)), (y0 + 1, x0 + 1, ty * tx)):
        value = grid[y][x]
        if value is None or w == 0:
            continue
        total += value * w
        weight += w
    return total / weight if weight >= 0.5 else None


async def sst_grid(storm_id: str, lat_range: tuple[float, float],
                   lon_range: tuple[float, float]) -> dict:
    """Coarse SST field covering a whole track, cached per storm."""
    lock = _sst_locks.setdefault(storm_id, asyncio.Lock())
    async with lock:
        cached = _sst_cache.get(storm_id)
        if cached and time.time() - cached[0] < SST_TTL_SECONDS:
            return cached[1]

        step = SST_STEP_DEG
        lats = [lat_range[0] + i * step
                for i in range(int((lat_range[1] - lat_range[0]) / step) + 1)]
        lons = [lon_range[0] + i * step
                for i in range(int((lon_range[1] - lon_range[0]) / step) + 1)]
        lats = [v for v in lats if -80 <= v <= 80]
        while len(lats) * len(lons) > MAX_POINTS:
            lats = lats[::2]
            lons = lons[::2]

        coords = [(la, ((lo + 180) % 360) - 180) for la in lats for lo in lons]
        points = await _fetch_batched(MARINE_URL, coords,
                                      ["sea_surface_temperature"], forecast_days=3)
        grid = [[_round(_value(points[r * len(lons) + c], "sea_surface_temperature"))
                 if r * len(lons) + c < len(points) else None
                 for c in range(len(lons))] for r in range(len(lats))]

        payload = {"lats": lats, "lons": lons, "grid": grid}
        _sst_cache[storm_id] = (time.time(), payload)
        return payload


def drop_sst_cache(active_ids: set[str]) -> None:
    for key in list(_sst_cache):
        if key not in active_ids:
            _sst_cache.pop(key, None)
            _sst_locks.pop(key, None)


def _extent_axes(lat_range: tuple[float, float], lon_range: tuple[float, float],
                 step: float) -> tuple[list[float], list[float]]:
    """Axes spanning a bounding box, coarsened until the point count is affordable."""
    def axis(lo: float, hi: float, clamp: float | None) -> list[float]:
        n = max(1, int(math.ceil((hi - lo) / step)))
        values = [lo + i * step for i in range(n + 1)]
        return [v for v in values if clamp is None or -clamp <= v <= clamp]

    lats = axis(lat_range[0], lat_range[1], 80.0)
    lons = axis(lon_range[0], lon_range[1], None)
    while len(lats) * len(lons) > MAX_POINTS and (len(lats) > 3 and len(lons) > 3):
        lats = lats[::2]
        lons = lons[::2]
    return lats, lons


async def sample_cube(lat_range: tuple[float, float], lon_range: tuple[float, float],
                      times: list[datetime], step_deg: float = DEFAULT_STEP_DEG,
                      sst: dict | None = None) -> dict:
    """Every mapped field, over a whole track, at every lead time — in one pass.

    Open-Meteo bills per *location*, not per timestep, and a single request
    returns the full hourly series for each point. Sampling the track extent
    once and slicing it per lead hour therefore costs what one lead hour used
    to, which is the difference between the map fitting in the daily quota and
    exhausting it in an afternoon.

    `sst` is a pre-sampled ocean grid from `sst_grid`, interpolated onto this
    mesh; it is time-invariant over a five-day forecast so it is reused for
    every frame.
    """
    lats, lons = _extent_axes(lat_range, lon_range, step_deg)
    coords = [(la, ((lo + 180) % 360) - 180) for la in lats for lo in lons]
    ordered = sorted(times)

    degraded: str | None = None
    try:
        atmosphere = await _fetch_batched(
            FORECAST_URL, coords, FIELD_VARS,
            models="gfs_global", wind_speed_unit="kn",
            start_hour=_hour_param(ordered[0]), end_hour=_hour_param(ordered[-1]))
    except BudgetExhausted as exc:
        # The ocean grid is already cached and costs nothing, so serve the SST
        # layer rather than blanking the map over an atmosphere we cannot fetch.
        log.warning("atmosphere grid unavailable, serving SST only: %s", exc)
        atmosphere = [None] * len(coords)
        degraded = str(exc)
    indices = _time_indices(atmosphere, times)

    ny, nx = len(lats), len(lons)
    keys = ("sst_c", "shear_kt", "shear_toward_deg", "rh_700_pct", "mslp_mb",
            "height_500_m", "steering_kt", "steering_toward_deg", "favourability")
    frames = [{key: [[None] * nx for _ in range(ny)] for key in keys} for _ in times]

    # The ocean grid is coarser and static, so interpolate it once per cell.
    sea = [[_bilinear(sst["lats"], sst["lons"], sst["grid"], lats[r], lons[c])
            if sst else None for c in range(nx)] for r in range(ny)]

    for cell, (row, col) in enumerate((r, c) for r in range(ny) for c in range(nx)):
        air = atmosphere[cell] if cell < len(atmosphere) else None
        sea_temp = sea[row][col]

        for frame, index in zip(frames, indices):
            shear_kt, shear_dir = _shear(air, index)
            steer_kt, steer_dir = _steering(air, index)
            rh = _value(air, "relative_humidity_700hPa", index)

            frame["sst_c"][row][col] = _round(sea_temp)
            frame["shear_kt"][row][col] = _round(shear_kt)
            frame["shear_toward_deg"][row][col] = _round(shear_dir, 0)
            frame["rh_700_pct"][row][col] = _round(rh, 0)
            frame["mslp_mb"][row][col] = _round(_value(air, "pressure_msl", index))
            frame["height_500_m"][row][col] = _round(
                _value(air, "geopotential_height_500hPa", index), 0)
            frame["steering_kt"][row][col] = _round(steer_kt)
            frame["steering_toward_deg"][row][col] = _round(steer_dir, 0)
            frame["favourability"][row][col] = _favourability(sea_temp, shear_kt, rh)

    return {
        "lats": [round(v, 3) for v in lats],
        "lons": [round(((v + 180) % 360) - 180, 3) for v in lons],
        "bounds": {
            "west": round(min(lons), 3), "east": round(max(lons), 3),
            "south": round(min(lats), 3), "north": round(max(lats), 3),
        },
        "step_deg": step_deg,
        "valid_times": [iso(round_hour(t)) for t in times],
        "frames": frames,
        "degraded": degraded,
        "source": "GFS via Open-Meteo; SST from the Open-Meteo marine feed",
        "note": ("Raw model fields, not annulus averages, so values within a few "
                 "hundred kilometres of the centre include the model's own vortex. "
                 "The whole track is sampled in one pass and sliced per lead time."),
    }


__all__ = ["sample_cube", "sst_grid", "drop_sst_cache", "build_grid", "compass"]
