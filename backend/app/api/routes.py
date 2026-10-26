"""HTTP API serving the dashboard, verification, tropical, and status views."""
import asyncio
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from ..config import MODELS, VERIFIABLE_VARS, settings
from ..db import session_scope
from ..ingest import tropical_env
from ..orm import IngestEvent, Observation, PointForecast
from ..services import scenario
from ..services import tropical as tropical_service
from ..services.engine import build_forecast_payload
from ..services.verification import compute_verification
from ..state import LATEST
from ..util import iso, utcnow

router = APIRouter(prefix="/api")


@router.get("/meta")
def meta():
    return {
        "app": "Personal Weather Lab",
        "phase": 1,
        "location": {
            "name": settings.home_name,
            "lat": settings.home_lat,
            "lon": settings.home_lon,
            "tz": settings.home_tz,
        },
        "models": [
            {"key": m.key, "label": m.label, "source": m.source,
             "is_ai": m.is_ai, "days": m.forecast_days, "note": m.note}
            for m in MODELS
        ],
        "nws_point": LATEST.nws_point,
    }


@router.get("/current")
def current():
    return {
        "observation": LATEST.observation,
        "alerts_count": len(LATEST.alerts),
        "server_time": iso(utcnow()),
    }


@router.get("/forecast")
def forecast(hours: int = Query(default=240, ge=24, le=240)):
    if not LATEST.model_series:
        raise HTTPException(status_code=503, detail="No model data ingested yet; try again shortly.")
    return build_forecast_payload(hours=hours)


@router.get("/alerts")
def alerts():
    return {"alerts": LATEST.alerts}


@router.get("/tropical")
def tropical():
    if LATEST.tropical is None:
        raise HTTPException(status_code=503, detail="Tropical data not ingested yet.")
    return LATEST.tropical


# NHC blocks browser hotlinking of outlook graphics; fetch server-side + cache.
_outlook_cache: dict[str, tuple[float, bytes]] = {}
_OUTLOOK_TTL = 600  # seconds


@router.get("/tropical/outlook/{idx}.png")
async def tropical_outlook_image(idx: int):
    from ..http_client import get_client
    from ..ingest.nhc import OUTLOOKS

    if not 0 <= idx < len(OUTLOOKS):
        raise HTTPException(status_code=404, detail="Unknown outlook index")
    url = OUTLOOKS[idx]["source_image"]

    cached = _outlook_cache.get(url)
    if cached and time.time() - cached[0] < _OUTLOOK_TTL:
        return Response(content=cached[1], media_type="image/png")

    resp = await get_client().get(url)
    resp.raise_for_status()
    _outlook_cache[url] = (time.time(), resp.content)
    return Response(content=resp.content, media_type="image/png",
                    headers={"Cache-Control": f"max-age={_OUTLOOK_TTL}"})


@router.get("/tropical/{storm_id}")
async def tropical_storm(storm_id: str, refresh: bool = Query(default=False)):
    """Everything known about one system: advisory, wind field, environment, reasoning."""
    detail = await tropical_service.get_storm_detail(storm_id, force=refresh)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No active storm with id {storm_id!r}")
    return detail


@router.get("/tropical/{storm_id}/scenario")
async def tropical_storm_scenario(
    storm_id: str,
    shear_delta_kt: float = Query(default=0.0),
    sst_delta_c: float = Query(default=0.0),
    rh_delta_pct: float = Query(default=0.0),
    ridge_factor: float = Query(default=1.0),
):
    """What-if sensitivity run: the effect of an environment change on NHC's forecast."""
    detail = await tropical_service.get_storm_detail(storm_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No active storm with id {storm_id!r}")
    return scenario.build_scenario(detail, {
        "shear_delta_kt": shear_delta_kt,
        "sst_delta_c": sst_delta_c,
        "rh_delta_pct": rh_delta_pct,
        "ridge_factor": ridge_factor,
    })


@router.get("/tropical/{storm_id}/fields")
async def tropical_storm_fields(
    storm_id: str,
    hour: int = Query(default=0, ge=0, le=120),
    refresh: bool = Query(default=False),
):
    """Gridded SST/shear/humidity/pressure around a storm, for map shading."""
    fields = await tropical_service.get_storm_fields(storm_id, hour=hour, force=refresh)
    if fields is None:
        raise HTTPException(status_code=404, detail=f"No active storm with id {storm_id!r}")
    return fields


@router.get("/verification")
async def verification(
    var: str = Query(default="temp_f"),
    days: int = Query(default=30, ge=1, le=365),
):
    if var not in VERIFIABLE_VARS:
        raise HTTPException(status_code=400, detail=f"var must be one of {VERIFIABLE_VARS}")
    return await asyncio.to_thread(compute_verification, var, days)


def _archive_counts() -> dict:
    with session_scope() as session:
        forecast_rows = session.execute(select(func.count(PointForecast.id))).scalar() or 0
        obs_rows = session.execute(select(func.count(Observation.id))).scalar() or 0
        first_run = session.execute(select(func.min(PointForecast.run_hour))).scalar()
        distinct_runs = session.execute(
            select(func.count(func.distinct(PointForecast.run_hour)))
        ).scalar() or 0
        recent_events = session.execute(
            select(IngestEvent).order_by(IngestEvent.id.desc()).limit(40)
        ).scalars().all()
    return {
        "forecast_rows": forecast_rows,
        "observation_rows": obs_rows,
        "distinct_runs": distinct_runs,
        "archiving_since": str(first_run) if first_run else None,
        "recent_events": [
            {
                "source": e.source,
                "started_at": str(e.started_at),
                "duration_ms": e.duration_ms,
                "ok": e.ok,
                "message": e.message,
                "items": e.items,
            }
            for e in recent_events
        ],
    }


@router.get("/status")
async def status():
    sources = []
    now = utcnow()
    for s in LATEST.statuses.values():
        age_s = (now - s.fetched_at).total_seconds() if s.fetched_at else None
        sources.append({
            "source": s.source,
            "label": s.label,
            "ok": s.ok,
            "fetched_at": iso(s.fetched_at) if s.fetched_at else None,
            "age_seconds": round(age_s) if age_s is not None else None,
            "duration_ms": s.duration_ms,
            "message": s.message,
            "items": s.extra.get("items"),
            "extra": {k: v for k, v in s.extra.items() if k != "items"},
        })
    archive = await asyncio.to_thread(_archive_counts)
    return {
        "server_time": iso(now),
        "sources": sources,
        "archive": archive,
        # The Open-Meteo quota gates the tropical map layers, so it is worth
        # being able to see how much of it is left before they go quiet.
        "api_budget": {"open_meteo_locations": tropical_env.budget_snapshot()},
    }
