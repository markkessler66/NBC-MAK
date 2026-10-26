"""Asynchronous ingestion scheduler.

Each source runs on its own periodic loop with error isolation: a failing
source records its failure (status + audit log) and retries on the next
cycle without affecting anything else.
"""
import asyncio
import logging
import time

from .config import MODELS, settings
from .db import session_scope
from .ingest import nhc, noaa, nws, open_meteo
from .models_ai import pangu
from .orm import IngestEvent
from .services import archiver
from .services import tropical as tropical_service
from .state import LATEST
from .util import utcnow

log = logging.getLogger("weatherlab.scheduler")


def _record_event(source: str, started, duration_ms: float, ok: bool, message: str, items: int) -> None:
    with session_scope() as session:
        session.add(IngestEvent(
            source=source, started_at=started, duration_ms=duration_ms,
            ok=ok, message=message[:500], items=items,
        ))


async def _run_once(source: str, label: str, work) -> None:
    """Run one ingestion cycle: fetch -> apply -> archive -> record status."""
    status = LATEST.status(source, label)
    started = utcnow()
    t0 = time.perf_counter()
    try:
        items = await work()
        duration = (time.perf_counter() - t0) * 1000
        status.ok = True
        status.fetched_at = started
        status.duration_ms = round(duration, 0)
        status.message = "ok"
        status.extra["items"] = items
        await asyncio.to_thread(_record_event, source, started, duration, True, "ok", items or 0)
    except Exception as exc:
        duration = (time.perf_counter() - t0) * 1000
        status.ok = False
        status.duration_ms = round(duration, 0)
        status.message = f"{type(exc).__name__}: {exc}"
        log.warning("ingest %s failed: %s", source, exc)
        try:
            await asyncio.to_thread(_record_event, source, started, duration, False, status.message, 0)
        except Exception:
            log.exception("failed to record ingest event for %s", source)


async def _loop(source: str, label: str, work, interval: int, initial_delay: float) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        await _run_once(source, label, work)
        await asyncio.sleep(interval)


# ---- per-source work functions ------------------------------------------------

async def _work_observation() -> int:
    obs = await nws.fetch_observation()
    LATEST.observation = obs
    return await asyncio.to_thread(archiver.archive_observation, obs)


async def _work_alerts() -> int:
    LATEST.alerts = await nws.fetch_alerts()
    return len(LATEST.alerts)


async def _work_nws_forecast() -> int:
    series = await nws.fetch_hourly_forecast()
    LATEST.model_series["nws"] = series
    return await asyncio.to_thread(archiver.archive_model_series, series)


def _make_model_work(spec):
    async def _work() -> int:
        series = await open_meteo.fetch_model_series(spec)
        LATEST.model_series[spec.key] = series
        return await asyncio.to_thread(archiver.archive_model_series, series)
    return _work


def _make_native_work(spec):
    """Native NOAA ingestion with automatic Open-Meteo fallback."""
    source = f"model_{spec.key}"

    async def _work() -> int:
        current = LATEST.model_series.get(spec.key) or {}
        try:
            series = await noaa.ingest_native(spec.key, current.get("init_time"))
        except Exception as exc:
            log.warning("native %s ingest failed (%s); using Open-Meteo fallback",
                        spec.key, exc)
            fallback = await open_meteo.fetch_model_series(spec)
            LATEST.model_series[spec.key] = fallback
            await asyncio.to_thread(archiver.archive_model_series, fallback)
            raise RuntimeError(f"native failed, Open-Meteo fallback applied: {exc}") from exc

        if series is None:
            return 0  # no new cycle yet; keep the current one
        LATEST.model_series[spec.key] = series
        status = LATEST.statuses.get(source)
        if status is not None and "ingest_meta" in series:
            status.extra.update(series["ingest_meta"])
        return await asyncio.to_thread(archiver.archive_model_series, series)

    return _work


async def _work_pangu() -> int:
    current = LATEST.model_series.get("pangu") or {}
    series = await pangu.run_forecast(settings.pangu_steps, current.get("init_time"))
    if series is None:
        return 0  # current GFS cycle already forecast
    LATEST.model_series["pangu"] = series
    status = LATEST.statuses.get("model_pangu")
    if status is not None:
        status.extra.update(series["ingest_meta"])
    return await asyncio.to_thread(archiver.archive_model_series, series)


async def _work_ensemble() -> int:
    ens = await open_meteo.fetch_gefs_ensemble()
    LATEST.ensemble = ens
    return ens["members"]


async def _work_tropical() -> int:
    trop = await nhc.fetch_tropical()
    LATEST.tropical = trop
    tropical_service.prune_cache({(s.get("id") or "").lower() for s in trop["storms"]})
    return len(trop["storms"])


async def _work_tropical_detail() -> int:
    """Pre-compute per-storm environmental diagnostics so detail views open warm.

    Sampling is sequential: a handful of storms times three upstream requests
    each is not worth bursting at Open-Meteo, and nothing here is latency
    sensitive.
    """
    for _ in range(20):
        if LATEST.tropical is not None:
            break
        await asyncio.sleep(3)  # positions loop starts seconds earlier
    storms = (LATEST.tropical or {}).get("storms") or []
    computed = 0
    for storm in storms:
        try:
            if await tropical_service.get_storm_detail(storm["id"]) is not None:
                computed += 1
        except Exception as exc:
            log.warning("tropical detail for %s failed: %s", storm.get("id"), exc)
        try:
            # Only the current hour is warmed; other lead times are a click away
            # and each one is a few hundred billed locations.
            await tropical_service.get_storm_fields(storm["id"], hour=0)
        except Exception as exc:
            log.warning("tropical fields for %s failed: %s", storm.get("id"), exc)
    return computed


def start_jobs() -> list[asyncio.Task]:
    """Start all ingestion loops; staggered so startup doesn't burst requests."""
    jobs = [
        ("nws_observations", "Surface observations (NWS)", _work_observation, settings.poll_observations),
        ("nws_alerts", "Active alerts (NWS)", _work_alerts, settings.poll_alerts),
        ("nws_forecast", "NWS hourly forecast", _work_nws_forecast, settings.poll_nws_forecast),
    ]
    for spec in MODELS:
        if spec.source != "open-meteo":
            continue
        if settings.native_ingest and spec.key in noaa.NATIVE_MODELS:
            jobs.append((f"model_{spec.key}", f"{spec.label} (NOAA native)",
                         _make_native_work(spec), settings.poll_native))
        else:
            jobs.append((f"model_{spec.key}", f"{spec.label} (Open-Meteo)",
                         _make_model_work(spec), settings.poll_models))
    jobs.append(("gefs_ensemble", "GEFS ensemble (Open-Meteo)", _work_ensemble, settings.poll_ensemble))
    jobs.append(("nhc_tropical", "NHC tropical (CurrentStorms + cones/tracks)",
                 _work_tropical, settings.poll_tropical))
    jobs.append(("tropical_environment", "Storm environment (GFS shear/SST/steering)",
                 _work_tropical_detail, settings.poll_tropical_detail))
    if settings.pangu_enabled:
        jobs.append(("model_pangu", "Pangu-Weather (local GPU)", _work_pangu, settings.poll_pangu))

    tasks = []
    for i, (source, label, work, interval) in enumerate(jobs):
        LATEST.status(source, label)  # register immediately so /api/status is complete
        tasks.append(asyncio.create_task(
            _loop(source, label, work, interval, initial_delay=i * 1.5),
            name=f"ingest:{source}",
        ))
    return tasks
