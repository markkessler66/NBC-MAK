"""Phase 4: Pangu-Weather running locally on the GPU.

Pangu-Weather (Huawei, Nature 2023) is a data-driven global model distributed
as ONNX graphs. We run the 24-hour model autoregressively:

    GFS analysis (f000, 0.25 deg global)  ->  initial conditions
    ONNX Runtime (CUDA)                   ->  step +24 h, fed back N times
    0.25 deg global output                ->  DFW point series ("pangu")

The series flows into the consensus, comparison table, and verification
archive exactly like any other model. Initial conditions come from GFS open
data (Pangu was trained on ERA5; GFS analysis is the standard operational
substitute and costs a small, known accuracy penalty).

Inference notes: the session is created per run and released afterwards so
VRAM is not held between 6-hourly cycles. Arena growth is capped to keep the
footprint inside 16 GB.
"""
import asyncio
import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone

import numpy as np

from ..config import settings
from ..http_client import get_client
from ..util import iso, utcnow

log = logging.getLogger("weatherlab.pangu")

MODEL_PATH = os.path.join("data", "ai", "pangu", "pangu_weather_24.onnx")
GFS_S3 = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"

# Pangu input specification (order matters).
PANGU_LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50]
G = 9.80665

# GRIB idx selectors: (VAR, LEVEL) for the surface inputs, in Pangu order.
SURFACE_SELECTORS = [
    ("PRMSL", "mean sea level"),
    ("UGRD", "10 m above ground"),
    ("VGRD", "10 m above ground"),
    ("TMP", "2 m above ground"),
]
UPPER_VARS = ["HGT", "SPFH", "TMP", "UGRD", "VGRD"]  # -> Z, Q, T, U, V


def model_available() -> bool:
    return os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 10**9


# ------------------------------------------------------------ initial conditions

def _ic_urls(cycle: datetime) -> tuple[str, str]:
    base = (f"{GFS_S3}/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos/"
            f"gfs.t{cycle:%H}z.pgrb2.0p25.f000")
    return base, base + ".idx"


async def find_latest_ic_cycle(lookback: int = 4) -> datetime | None:
    """Newest GFS cycle with an f000 analysis available on S3."""
    now = utcnow()
    t = now.replace(minute=0, second=0, microsecond=0)
    checked = 0
    while checked < lookback:
        if t.hour in (0, 6, 12, 18):
            checked += 1
            if now - t >= timedelta(minutes=210):  # analysis publishes ~3.5 h after init
                _, idx_url = _ic_urls(t)
                try:
                    resp = await get_client().head(idx_url)
                    if resp.status_code == 200:
                        return t
                except Exception:
                    pass
        t -= timedelta(hours=1)
    return None


def _parse_idx(idx_text: str) -> list[tuple[str, str, int, int | None]]:
    """Yield (var, level, start_byte, end_byte) for every idx entry."""
    lines = [ln for ln in idx_text.splitlines() if ln.strip()]
    entries = []
    for i, ln in enumerate(lines):
        parts = ln.split(":")
        if len(parts) < 6:
            continue
        start = int(parts[1])
        end = int(lines[i + 1].split(":")[1]) - 1 if i + 1 < len(lines) else None
        entries.append((parts[3], parts[4], start, end))
    return entries


async def fetch_initial_conditions(cycle: datetime) -> tuple[np.ndarray, np.ndarray]:
    """Download + decode the ~69 GFS analysis fields Pangu needs."""
    grib_url, idx_url = _ic_urls(cycle)
    idx_resp = await get_client().get(idx_url)
    idx_resp.raise_for_status()
    entries = _parse_idx(idx_resp.text)

    upper_levels = {f"{p} mb" for p in PANGU_LEVELS}
    wanted = [
        (var, lev, s, e) for (var, lev, s, e) in entries
        if (var in UPPER_VARS and lev in upper_levels) or (var, lev) in SURFACE_SELECTORS
    ]
    expected = len(UPPER_VARS) * len(PANGU_LEVELS) + len(SURFACE_SELECTORS)
    if len(wanted) != expected:
        raise RuntimeError(f"IC idx matched {len(wanted)} fields, expected {expected}")

    sem = asyncio.Semaphore(8)

    async def fetch_range(start: int, end: int | None) -> bytes:
        headers = {"Range": f"bytes={start}-{'' if end is None else end}"}
        async with sem:
            resp = await get_client().get(grib_url, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.content

    blobs = await asyncio.gather(*(fetch_range(s, e) for (_, _, s, e) in wanted))
    total = sum(len(b) for b in blobs)
    log.info("pangu IC: %d fields, %.1f MB from GFS %sZ", len(blobs), total / 1e6, f"{cycle:%H}")

    tmp = tempfile.NamedTemporaryFile(suffix=".grib2", delete=False, dir=_ensure_tmp())
    try:
        with tmp:
            for b in blobs:
                tmp.write(b)
        return await asyncio.to_thread(_decode_ic, tmp.name)
    finally:
        os.unlink(tmp.name)


def _decode_ic(path: str) -> tuple[np.ndarray, np.ndarray]:
    import warnings

    import cfgrib
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})

    upper_ds = None
    fields: dict[str, xr.DataArray] = {}
    for ds in datasets:
        if "isobaricInhPa" in ds.coords and ds["isobaricInhPa"].size > 1:
            upper_ds = ds
        for name in ("prmsl", "u10", "v10", "t2m"):
            if name in ds.data_vars:
                fields[name] = ds[name]
    if upper_ds is None or len(fields) != 4:
        raise RuntimeError(f"IC decode incomplete (surface fields: {sorted(fields)})")

    upper_ds = upper_ds.sel(isobaricInhPa=PANGU_LEVELS)  # enforce 1000 -> 50 order
    if float(upper_ds["latitude"][0]) < 0:
        upper_ds = upper_ds.isel(latitude=slice(None, None, -1))
        fields = {k: v.isel(latitude=slice(None, None, -1)) for k, v in fields.items()}

    upper = np.stack([
        upper_ds["gh"].values * G,       # geopotential height -> geopotential
        upper_ds["q"].values,
        upper_ds["t"].values,
        upper_ds["u"].values,
        upper_ds["v"].values,
    ]).astype(np.float32)                 # (5, 13, 721, 1440)

    surface = np.stack([
        fields["prmsl"].values,
        fields["u10"].values,
        fields["v10"].values,
        fields["t2m"].values,
    ]).astype(np.float32)                 # (4, 721, 1440)

    if upper.shape != (5, 13, 721, 1440) or surface.shape != (4, 721, 1440):
        raise RuntimeError(f"unexpected IC shapes {upper.shape} / {surface.shape}")
    return upper, surface


# ------------------------------------------------------------------- inference

def _gpu_mem_used_mb() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def run_inference(upper: np.ndarray, surface: np.ndarray, steps: int) -> tuple[list[np.ndarray], dict]:
    """Run the 24 h model autoregressively; returns per-step surface fields."""
    import onnxruntime as ort

    try:
        ort.preload_dlls()
    except Exception:
        pass

    opts = ort.SessionOptions()
    # Per Pangu's reference inference code: trade a little speed for memory.
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False

    providers = [
        ("CUDAExecutionProvider", {"arena_extend_strategy": "kSameAsRequested"}),
        "CPUExecutionProvider",
    ]
    t0 = time.perf_counter()
    session = ort.InferenceSession(MODEL_PATH, sess_options=opts, providers=providers)
    load_s = time.perf_counter() - t0

    step_times, surfaces = [], []
    try:
        for _ in range(steps):
            t1 = time.perf_counter()
            upper, surface = session.run(
                None, {"input": upper, "input_surface": surface}
            )
            step_times.append(round(time.perf_counter() - t1, 1))
            surfaces.append(surface.copy())
        vram = _gpu_mem_used_mb()
        # Read providers AFTER running: ORT silently rebuilds the session on
        # CPU if the CUDA EP fails at first run, and we want the truth here.
        provider = session.get_providers()[0]
    finally:
        del session

    bench = {
        "provider": provider,
        "model_load_s": round(load_s, 1),
        "step_seconds": step_times,
        "gpu_mem_used_mb": vram,
    }
    return surfaces, bench


# ---------------------------------------------------------------- point series

def _point_indices() -> tuple[int, int]:
    i_lat = round((90.0 - settings.home_lat) / 0.25)
    i_lon = round((settings.home_lon % 360.0) / 0.25) % 1440
    return i_lat, i_lon


async def run_forecast(steps: int, have_init_iso: str | None = None) -> dict | None:
    """Produce the local Pangu point series, or None if no new GFS cycle."""
    cycle = await find_latest_ic_cycle()
    if cycle is None:
        raise RuntimeError("No GFS analysis cycle found for initial conditions")
    if have_init_iso is not None:
        have = datetime.fromisoformat(have_init_iso.replace("Z", "+00:00"))
        if have == cycle:
            return None
    if not model_available():
        raise RuntimeError(f"Pangu ONNX weights missing at {MODEL_PATH}")

    t0 = utcnow()
    upper, surface = await fetch_initial_conditions(cycle)
    surfaces, bench = await asyncio.to_thread(run_inference, upper, surface, steps)

    i_lat, i_lon = _point_indices()
    times, temp, wind, wdir, press = [], [], [], [], []
    for step, sfc in enumerate(surfaces, start=1):
        msl, u10, v10, t2m = (sfc[k, i_lat, i_lon] for k in range(4))
        times.append(iso(cycle + timedelta(hours=24 * step)))
        temp.append(round((float(t2m) - 273.15) * 9 / 5 + 32, 1))
        speed = float(np.hypot(u10, v10)) * 2.23694
        wind.append(round(speed, 1))
        wdir.append(round(float(np.degrees(np.arctan2(-u10, -v10))) % 360))
        press.append(round(float(msl) / 100.0, 1))

    return {
        "key": "pangu",
        "label": "Pangu (local)",
        "source": "local-ai",
        "is_ai": True,
        "fetched_at": iso(utcnow()),
        "init_time": iso(cycle),
        "times": times,
        "values": {
            "temp_f": temp,
            "wind_mph": wind,
            "wind_dir": wdir,
            "pressure_mb": press,
        },
        "ingest_meta": {
            "cycle": iso(cycle),
            "steps": steps,
            "wall_seconds": round((utcnow() - t0).total_seconds(), 1),
            "init_to_ingest_min": round((utcnow() - cycle).total_seconds() / 60),
            **bench,
        },
    }


def _ensure_tmp() -> str:
    path = os.path.join("data", "tmp")
    os.makedirs(path, exist_ok=True)
    return path
