"""Native NOAA GRIB2 ingestion (Phase 2).

Pulls HRRR and GFS directly from NOAA instead of a third-party JSON API:

  1. Probe NOAA's open S3 buckets to find the newest *complete* model cycle
     (cheap HEAD requests against .idx files) — this gives the TRUE
     initialization time, which Open-Meteo does not expose.
  2. Download variable- and region-subsetted GRIB2 files from the NOMADS
     GRIB-filter CGI (server-side subsetting: ~0.1–1.5 MB per forecast hour
     for a North Texas box instead of ~150 MB CONUS files).
  3. Decode with cfgrib/ecCodes, assemble an xarray Dataset per run, and
     archive the grids to Zarr (spec §14: grids in Zarr, metadata in SQL).
  4. Extract the home-point series in dashboard units, keyed by true init
     time, which flows into the consensus engine and verification archive.

If any step fails, the scheduler falls back to the Open-Meteo feed for that
cycle so the dashboard never goes stale (spec §15: one failure must not take
down the system).
"""
import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import xarray as xr

from ..config import settings
from ..http_client import get_client
from ..util import iso, utcnow

log = logging.getLogger("weatherlab.noaa")

NOMADS = "https://nomads.ncep.noaa.gov/cgi-bin"


@dataclass(frozen=True)
class NativeModel:
    key: str                    # matches ModelSpec.key ("hrrr" / "gfs")
    label: str
    s3_base: str                # availability probing
    s3_path: str                # format: date=YYYYMMDD, hh=HH, fff=forecast hour
    filter_cgi: str             # NOMADS GRIB filter script
    filter_dir: str             # format: date, hh
    file_name: str              # format: hh, fff
    cycles: tuple[int, ...]     # UTC init hours
    forecast_hours: tuple[int, ...]
    step_hours: int             # native output interval we ingest
    avail_delay_min: int        # typical minutes after init before complete
    grib_vars: tuple[str, ...]
    grib_levels: tuple[str, ...]


_HRRR_HOURS = tuple(range(0, 19))          # f00–f18, hourly
_GFS_HOURS = tuple(range(0, 241, 3))       # f000–f240, 3-hourly

NATIVE_MODELS: dict[str, NativeModel] = {
    "hrrr": NativeModel(
        key="hrrr", label="HRRR",
        s3_base="https://noaa-hrrr-bdp-pds.s3.amazonaws.com",
        s3_path="hrrr.{date}/conus/hrrr.t{hh:02d}z.wrfsfcf{fff:02d}.grib2",
        filter_cgi=f"{NOMADS}/filter_hrrr_2d.pl",
        filter_dir="/hrrr.{date}/conus",
        file_name="hrrr.t{hh:02d}z.wrfsfcf{fff:02d}.grib2",
        cycles=tuple(range(24)),
        forecast_hours=_HRRR_HOURS,
        step_hours=1,
        avail_delay_min=55,
        grib_vars=("TMP", "DPT", "RH", "UGRD", "VGRD", "GUST", "APCP",
                   "TCDC", "CAPE", "CIN", "MSLMA", "REFC"),
        grib_levels=("2_m_above_ground", "10_m_above_ground", "surface",
                     "mean_sea_level", "entire_atmosphere"),
    ),
    "gfs": NativeModel(
        key="gfs", label="GFS",
        s3_base="https://noaa-gfs-bdp-pds.s3.amazonaws.com",
        s3_path="gfs.{date}/{hh:02d}/atmos/gfs.t{hh:02d}z.pgrb2.0p25.f{fff:03d}",
        filter_cgi=f"{NOMADS}/filter_gfs_0p25.pl",
        filter_dir="/gfs.{date}/{hh:02d}/atmos",
        file_name="gfs.t{hh:02d}z.pgrb2.0p25.f{fff:03d}",
        cycles=(0, 6, 12, 18),
        forecast_hours=_GFS_HOURS,
        step_hours=3,
        avail_delay_min=300,
        grib_vars=("TMP", "DPT", "RH", "UGRD", "VGRD", "GUST", "APCP",
                   "TCDC", "CAPE", "CIN", "PRMSL"),
        grib_levels=("2_m_above_ground", "10_m_above_ground", "surface",
                     "mean_sea_level", "entire_atmosphere"),
    ),
}



# ---------------------------------------------------------------- cycle probing

async def _s3_exists(url: str) -> bool:
    try:
        resp = await get_client().head(url)
        return resp.status_code == 200
    except Exception:
        return False


async def find_latest_complete_cycle(model: NativeModel, lookback: int = 8) -> datetime | None:
    """Newest cycle whose FINAL forecast-hour file exists on S3."""
    now = utcnow()
    candidates = []
    t = now.replace(minute=0, second=0, microsecond=0)
    for _ in range(72):  # scan back hour by hour, collect valid cycle times
        if t.hour in model.cycles:
            candidates.append(t)
            if len(candidates) >= lookback:
                break
        t -= timedelta(hours=1)

    last_fff = model.forecast_hours[-1]
    for cycle in candidates:
        # Skip cycles that can't plausibly be complete yet.
        if now - cycle < timedelta(minutes=model.avail_delay_min - 15):
            continue
        idx_url = f"{model.s3_base}/" + model.s3_path.format(
            date=cycle.strftime("%Y%m%d"), hh=cycle.hour, fff=last_fff
        ) + ".idx"
        if await _s3_exists(idx_url):
            return cycle
    return None


def zarr_path(model: NativeModel, cycle: datetime) -> str:
    return os.path.join(settings.grid_dir, model.key, cycle.strftime("%Y%m%dT%HZ") + ".zarr")


# ------------------------------------------------------------------ downloading

async def _download_subset(model: NativeModel, cycle: datetime, fff: int, dest: str) -> int:
    """Fetch one forecast hour, variable/region-subsetted, from NOMADS."""
    params: dict[str, str] = {
        "dir": model.filter_dir.format(date=cycle.strftime("%Y%m%d"), hh=cycle.hour),
        "file": model.file_name.format(hh=cycle.hour, fff=fff),
        "subregion": "",
        "leftlon": str(settings.region_west),
        "rightlon": str(settings.region_east),
        "toplat": str(settings.region_north),
        "bottomlat": str(settings.region_south),
    }
    for v in model.grib_vars:
        params[f"var_{v}"] = "on"
    for lev in model.grib_levels:
        params[f"lev_{lev}"] = "on"

    resp = await get_client().get(model.filter_cgi, params=params, timeout=90)
    resp.raise_for_status()
    content = resp.content
    if not content.startswith(b"GRIB"):
        raise RuntimeError(f"NOMADS returned non-GRIB payload for f{fff:03d} "
                           f"({content[:80]!r})")
    with open(dest, "wb") as f:
        f.write(content)
    return len(content)


# --------------------------------------------------------------------- decoding

def _step_span(da: xr.DataArray) -> float | None:
    """Length in hours of an accumulation window, from GRIB stepRange 'a-b'."""
    rng = da.attrs.get("GRIB_stepRange", "")
    if "-" in str(rng):
        try:
            a, b = str(rng).split("-")
            return float(b) - float(a)
        except ValueError:
            return None
    return None


def _decode_file(path: str, model: NativeModel) -> xr.Dataset:
    """Decode one subset GRIB into a flat Dataset of known variables."""
    import warnings

    import cfgrib

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})
    out: dict[str, xr.DataArray] = {}
    valid_time = None
    lat = lon = None
    for ds in datasets:
        if valid_time is None and "valid_time" in ds.coords:
            valid_time = ds["valid_time"].values
        if lat is None and "latitude" in ds.coords:
            lat = ds["latitude"]
            lon = ds["longitude"]
        for name, da in ds.data_vars.items():
            if name == "tp":
                # Files can contain both run-total and per-step accumulations;
                # keep the shortest window (1 h HRRR / 3 h GFS).
                span = _step_span(da)
                if span is not None and span > model.step_hours:
                    continue
                out["tp"] = da
            elif name in ("t2m", "d2m", "r2", "u10", "v10", "gust", "i10fg",
                          "cape", "cin", "tcc", "refc", "prmsl", "mslma", "msl"):
                key = {"i10fg": "gust", "mslma": "prmsl", "msl": "prmsl"}.get(name, name)
                out.setdefault(key, da)

    if not out:
        raise RuntimeError(f"No known variables decoded from {os.path.basename(path)}")

    merged = xr.Dataset(
        {k: v.reset_coords(drop=True) for k, v in out.items()},
        attrs={"source_file": os.path.basename(path)},
    )
    merged = merged.assign_coords(valid_time=valid_time)
    if lat is not None:
        # reset_coords drops 2D lat/lon (HRRR Lambert grid); restore them.
        merged = merged.assign_coords(latitude=lat.reset_coords(drop=True),
                                      longitude=lon.reset_coords(drop=True))
    return merged


def _decode_run(paths: list[str], model: NativeModel, cycle: datetime) -> xr.Dataset:
    parts = []
    for p in paths:
        try:
            parts.append(_decode_file(p, model))
        except Exception as exc:
            log.warning("%s: skipping %s (%s)", model.key, os.path.basename(p), exc)
    if not parts:
        raise RuntimeError("No forecast hours decoded successfully")
    run = xr.concat(parts, dim="valid_time", coords="minimal", compat="override")
    run = run.sortby("valid_time")
    run.attrs.update({
        "model": model.key,
        "init_time": cycle.isoformat(),
        "region": f"{settings.region_south}-{settings.region_north}N "
                  f"{settings.region_west}-{settings.region_east}E",
    })
    return run


# ------------------------------------------------------------- point extraction

_K = 273.15


def _k_to_f(x):
    return (x - _K) * 9 / 5 + 32


def _nearest_indexers(ds: xr.Dataset) -> dict:
    """Nearest-grid-point indexers for the home location (1D or 2D coords)."""
    lat, lon = settings.home_lat, settings.home_lon
    lats = ds["latitude"]
    lons = ds["longitude"]
    lon_vals = xr.where(lons > 180, lons - 360, lons)  # normalize to [-180, 180]
    if lats.ndim == 2:
        dist = (lats - lat) ** 2 + (lon_vals - lon) ** 2
        flat = int(dist.argmin())
        j, i = np.unravel_index(flat, dist.shape)
        ydim, xdim = lats.dims
        return {ydim: int(j), xdim: int(i)}
    return {
        "latitude": int(abs(lats - lat).argmin()),
        "longitude": int(abs(lon_vals - lon).argmin()),
    }


def extract_point_series(run: xr.Dataset, model: NativeModel, cycle: datetime) -> dict:
    """Home-point forecast series in dashboard units, keyed by true init time."""
    pt = run.isel(_nearest_indexers(run))

    vt = np.atleast_1d(pt["valid_time"].values)
    times = [
        iso(datetime.fromisoformat(s).replace(tzinfo=timezone.utc))
        for s in np.datetime_as_string(vt, unit="s").tolist()
    ]

    def col(name, fn=lambda x: x, digits=2):
        if name not in pt:
            return None
        vals = pt[name].values
        out = []
        for v in np.atleast_1d(vals):
            out.append(None if np.isnan(v) else round(float(fn(v)), digits))
        return out

    n = len(times)
    values: dict[str, list] = {}

    def put(key, data):
        if data is not None and len(data) == n and any(v is not None for v in data):
            values[key] = data

    put("temp_f", col("t2m", _k_to_f, 1))
    put("dewpoint_f", col("d2m", _k_to_f, 1))
    put("rh", col("r2", digits=0))
    put("cloud_pct", col("tcc", digits=0))
    put("cape", col("cape", digits=0))
    put("cin", col("cin", digits=0))
    put("pressure_mb", col("prmsl", lambda x: x / 100.0, 1))
    put("gust_mph", col("gust", lambda x: x * 2.23694, 1))
    put("refc_dbz", col("refc", digits=0))

    if "u10" in pt and "v10" in pt:
        u = np.atleast_1d(pt["u10"].values)
        v = np.atleast_1d(pt["v10"].values)
        speed = np.sqrt(u ** 2 + v ** 2) * 2.23694
        wdir = (np.degrees(np.arctan2(-u, -v))) % 360
        put("wind_mph", [None if np.isnan(s) else round(float(s), 1) for s in speed])
        put("wind_dir", [None if np.isnan(d) else round(float(d)) for d in wdir])

    if "tp" in pt:
        # Normalize accumulations to inches-per-hour so HRRR (1 h) and
        # GFS (3 h) precip remain comparable in the consensus.
        tp = np.atleast_1d(pt["tp"].values)
        per_hour = tp / 25.4 / model.step_hours
        put("precip_in", [None if np.isnan(x) else round(float(x), 3) for x in per_hour])

    if not values:
        raise RuntimeError("Point extraction produced no variables")

    return {
        "key": model.key,
        "label": model.label,
        "source": "noaa-native",
        "is_ai": False,
        "fetched_at": iso(utcnow()),
        "init_time": iso(cycle),
        "times": times,
        "values": values,
    }


# ------------------------------------------------------------------- main entry

def _prune_old_runs(model: NativeModel) -> None:
    root = os.path.join(settings.grid_dir, model.key)
    if not os.path.isdir(root):
        return
    cutoff = utcnow() - timedelta(days=settings.grid_retention_days)
    for name in os.listdir(root):
        try:
            run_time = datetime.strptime(name.replace(".zarr", ""), "%Y%m%dT%HZ").replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
        if run_time < cutoff:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
            log.info("%s: pruned old run %s", model.key, name)


async def ingest_native(key: str, have_init_iso: str | None = None) -> dict | None:
    """Ingest the newest complete cycle.

    Returns the point series, or None when the in-memory series already holds
    this cycle. If the cycle's grids are already archived on disk (e.g. after
    a service restart), the series is re-extracted from Zarr without
    re-downloading anything.
    """
    model = NATIVE_MODELS[key]
    cycle = await find_latest_complete_cycle(model)
    if cycle is None:
        raise RuntimeError("No complete cycle found on S3 within lookback window")

    if have_init_iso is not None:
        have = datetime.fromisoformat(have_init_iso.replace("Z", "+00:00"))
        if have == cycle:
            return None  # current cycle already live

    zpath = zarr_path(model, cycle)
    if os.path.isdir(zpath):
        run = await asyncio.to_thread(lambda: xr.open_zarr(zpath).load())
        series = await asyncio.to_thread(extract_point_series, run, model, cycle)
        series["ingest_meta"] = {
            "cycle": iso(cycle),
            "files": 0,
            "bytes": 0,
            "from_cache": True,
            "init_to_ingest_min": round((utcnow() - cycle).total_seconds() / 60),
            "zarr": zpath,
        }
        return series

    t0 = utcnow()
    tmp = tempfile.mkdtemp(prefix=f"{model.key}_", dir=_ensure_dir("./data/tmp"))
    try:
        paths, total_bytes = [], 0
        for fff in model.forecast_hours:
            dest = os.path.join(tmp, f"f{fff:03d}.grib2")
            total_bytes += await _download_subset(model, cycle, fff, dest)
            paths.append(dest)
            await asyncio.sleep(0.4)  # stay well under NOMADS rate limits

        run = await asyncio.to_thread(_decode_run, paths, model, cycle)

        _ensure_dir(os.path.dirname(zpath))
        await asyncio.to_thread(lambda: run.to_zarr(zpath, mode="w"))

        series = await asyncio.to_thread(extract_point_series, run, model, cycle)
        series["ingest_meta"] = {
            "cycle": iso(cycle),
            "files": len(paths),
            "bytes": total_bytes,
            "download_started": iso(t0),
            "completed": iso(utcnow()),
            "init_to_ingest_min": round((utcnow() - cycle).total_seconds() / 60),
            "zarr": zpath,
        }
        await asyncio.to_thread(_prune_old_runs, model)
        return series
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
